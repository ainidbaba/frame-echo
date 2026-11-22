"""Local-only Frame Echo web application and reproducible retrieval jobs."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import os
import shutil
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Literal

import numpy as np
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.retrieval import available_clip, get_encoder, rank_matches
from app.video import extract_frames, timestamp_label
from scripts.create_demo import ensure_demo

ROOT = Path(__file__).resolve().parents[1]
MAX_VIDEO_MB = 500
MAX_IMAGE_MB = 20
VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
LOGGER = logging.getLogger("frame_echo")


class SearchSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    interval: float = Field(default=1.0, ge=0.25, le=10, allow_inf_nan=False)
    top_k: int = Field(default=6, ge=1, le=20)
    min_gap: float = Field(default=3.0, ge=0, le=60, allow_inf_nan=False)
    method: Literal["colour", "clip"] = "colour"
    min_score: float | None = Field(default=None, ge=-1, le=1, allow_inf_nan=False)

    @field_validator("min_score", mode="before")
    @classmethod
    def reject_boolean_threshold(cls, value):
        if isinstance(value, bool):
            raise ValueError("min_score must be a number or null, not a boolean.")
        return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _display_filename(filename: str | None, fallback: str) -> str:
    return "".join(c for c in Path(filename or fallback).name if c.isprintable())[:200] or fallback


def _prepare_reference(source: Path, destination: Path) -> None:
    try:
        with Image.open(source) as opened:
            if opened.width * opened.height > 40_000_000:
                raise ValueError("The reference image is too large. Please use an image below 40 megapixels.")
            image = ImageOps.exif_transpose(opened)
            image.load()
            if "A" in image.getbands() or "transparency" in image.info:
                rgba = image.convert("RGBA")
                background = Image.new("RGBA", rgba.size, "white")
                image = Image.alpha_composite(background, rgba).convert("RGB")
            else:
                image = image.convert("RGB")
            image.thumbnail((2048, 2048), Image.Resampling.LANCZOS)
            image.save(destination, format="PNG")
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError("The reference image cannot be read. Please choose a JPG, PNG or WebP image.") from exc


async def _save_upload(upload: UploadFile, destination: Path, limit_mb: int) -> None:
    size = 0
    try:
        with destination.open("wb") as output:
            while chunk := await upload.read(1024 * 1024):
                size += len(chunk)
                if size > limit_mb * 1024 * 1024:
                    raise HTTPException(413, f"This file exceeds the {limit_mb} MB limit.")
                output.write(chunk)
        if size == 0:
            raise HTTPException(422, "Please choose a non-empty file.")
    finally:
        await upload.close()


class JobManager:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.runtime = data_dir / "runtime"
        self.runtime.mkdir(parents=True, exist_ok=True)
        self.model_path = data_dir / "models" / "open_clip_model.safetensors"
        self.jobs: dict[str, dict] = {}
        self.lock = threading.Lock()
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="frame-echo")
        self.encoders: dict = {}

    def check_method(self, method: str) -> None:
        if method == "clip":
            capability = available_clip(self.model_path)
            if not capability["available"]:
                raise HTTPException(409, capability["reason"])

    def new(self, settings: SearchSettings, video_name: str, art_name: str, synthetic: bool) -> tuple[str, Path]:
        self.check_method(settings.method)
        job_id = uuid.uuid4().hex
        directory = self.runtime / job_id
        directory.mkdir()
        record = {
            "job_id": job_id, "status": "queued", "stage": "queued", "progress": 0,
            "message": "Waiting to process your video.", "error": None,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "synthetic": synthetic, "settings": settings.model_dump(),
            "video": {"filename": video_name}, "reference": {"filename": art_name},
            "frames_total": 0, "results": [], "export_url": None,
        }
        with self.lock:
            self.jobs[job_id] = record
        return job_id, directory

    def update(self, job_id: str, **updates) -> None:
        with self.lock:
            self.jobs[job_id].update(updates)

    def get(self, job_id: str) -> dict:
        if len(job_id) != 32 or any(c not in "0123456789abcdef" for c in job_id):
            raise HTTPException(404, "This search could not be found.")
        with self.lock:
            record = self.jobs.get(job_id)
            if record is not None:
                return json.loads(json.dumps(record))
        # Completed records remain reviewable after restarting the local app.
        metadata = self.runtime / job_id / "results.json"
        if metadata.is_file():
            return json.loads(metadata.read_text(encoding="utf-8"))
        raise HTTPException(404, "This search could not be found.")

    def submit(self, job_id: str, video: Path, art: Path) -> None:
        self.executor.submit(self.process, job_id, video, art)

    def process(self, job_id: str, video: Path, art: Path) -> None:
        started = time.perf_counter()
        directory = self.runtime / job_id
        public_root = f"/media/{job_id}"
        settings = self.get(job_id)["settings"]
        try:
            self.update(job_id, status="processing", stage="reference", progress=2, message="Preparing your reference image.")
            reference_path = directory / "reference.png"
            _prepare_reference(art, reference_path)
            record = self.get(job_id)
            reference = {**record["reference"], "url": f"{public_root}/reference.png", "sha256": _sha256(art)}
            self.update(job_id, reference=reference, stage="sampling", progress=5, message="Sampling video frames.")

            def report(fraction: float, count: int) -> None:
                self.update(job_id, progress=round(5 + 50 * fraction, 1), frames_total=count,
                            message=f"Sampled {count} video frames.")

            info, frames = extract_frames(video, directory / "frames", settings["interval"], report)
            video_record = {**record["video"], **info, "url": f"{public_root}/{video.name}", "sha256": _sha256(video)}
            self.update(job_id, video=video_record, frames_total=len(frames), progress=57,
                        stage="features", message="Preparing image features.")
            method = settings["method"]
            if method not in self.encoders:
                self.encoders[method] = get_encoder(method, self.model_path)
            encoder = self.encoders[method]
            with Image.open(reference_path) as image:
                query = encoder.encode([image])
            vectors = []
            batch_size = 16 if method == "clip" else 32
            for start in range(0, len(frames), batch_size):
                images = []
                try:
                    for frame in frames[start:start + batch_size]:
                        with Image.open(frame["path"]) as image:
                            images.append(image.convert("RGB"))
                    vectors.append(encoder.encode(images))
                finally:
                    for image in images:
                        image.close()
                done = min(start + batch_size, len(frames))
                self.update(job_id, progress=round(58 + 36 * done / len(frames), 1),
                            message=f"Compared {done} of {len(frames)} frames.")
            features = np.concatenate(vectors, axis=0)
            np.savez_compressed(directory / "features.npz", query=query, frames=features,
                                timestamps=np.asarray([f["timestamp"] for f in frames]))
            self.update(job_id, stage="ranking", progress=96, message="Ranking time-separated matches.")
            matches = rank_matches(
                query, features, [f["timestamp"] for f in frames],
                settings["top_k"], settings["min_gap"], min_score=settings.get("min_score"),
            )
            results = []
            for rank, match in enumerate(matches, start=1):
                frame = frames[match["index"]]
                thumbnail = directory / f"match_{rank:02d}.jpg"
                with Image.open(frame["path"]) as image:
                    image.thumbnail((480, 480), Image.Resampling.LANCZOS)
                    image.save(thumbnail, quality=90)
                results.append({
                    "rank": rank, "timestamp": match["timestamp"],
                    "timestamp_label": timestamp_label(match["timestamp"]), "score": match["score"],
                    "thumbnail_url": f"{public_root}/{thumbnail.name}",
                    "frame_url": f"{public_root}/frames/{frame['path'].name}",
                })
            match_status = "matches_found" if results else "no_match"
            message = f"Found {len(results)} time-separated matches." if results else "No sufficiently similar frames found"
            self.update(job_id, status="complete", stage="complete", progress=100,
                        message=message, match_status=match_status, results=results,
                        model_id=encoder.model_id, elapsed_seconds=round(time.perf_counter() - started, 3),
                        export_url=f"/api/jobs/{job_id}/export.csv",
                        metadata_url=f"/api/jobs/{job_id}/export.json")
            completed = self.get(job_id)
            (directory / "results.json").write_text(json.dumps(completed, indent=2) + "\n", encoding="utf-8")
        except Exception as exc:
            LOGGER.exception("Search %s failed", job_id)
            message = str(exc) if isinstance(exc, (ValueError, RuntimeError)) else "This search could not be completed. Please try a different file."
            self.update(job_id, status="error", stage="error", error=message, message=message,
                        elapsed_seconds=round(time.perf_counter() - started, 3))


def _csv_text(value) -> str:
    text = str(value)
    return "'" + text if text.startswith(("=", "+", "-", "@", "\t", "\r")) else text


def create_app(data_dir: Path | None = None) -> FastAPI:
    data_dir = Path(data_dir or os.environ.get("FRAME_ECHO_DATA_DIR", ROOT / "data"))
    manager = JobManager(data_dir)
    demo_dir = data_dir / "demo"
    demo_dir.mkdir(parents=True, exist_ok=True)

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        # The fixture is deterministic and explicitly labelled; no media download.
        ensure_demo(demo_dir)
        yield
        manager.executor.shutdown(wait=True, cancel_futures=True)

    application = FastAPI(title="Frame Echo", version="0.1.0", lifespan=lifespan)
    application.state.manager = manager
    application.mount("/assets", StaticFiles(directory=ROOT / "web", check_dir=False), name="assets")
    application.mount("/media", StaticFiles(directory=manager.runtime), name="media")
    application.mount("/demo", StaticFiles(directory=demo_dir), name="demo")

    @application.get("/")
    def index():
        return FileResponse(ROOT / "web" / "index.html")

    @application.get("/api/capabilities")
    def capabilities():
        clip = available_clip(manager.model_path)
        return {
            "app_name": "Frame Echo", "version": "0.1.0", "default_method": "colour",
            "methods": [
                {"id": "colour", "name": "Colour & layout", "available": True,
                 "reason": "Compare global colours and their distribution across a 3 × 3 grid."},
                {"id": "clip", "name": "CLIP image features", **clip},
            ],
            "max_video_mb": MAX_VIDEO_MB, "max_image_mb": MAX_IMAGE_MB,
            "demo": {"available": True, "video_url": "/demo/video.mp4", "reference_url": "/demo/reference.png"},
        }

    @application.post("/api/search", status_code=202)
    async def search(
        video_file: Annotated[UploadFile, File()], art_file: Annotated[UploadFile, File()],
        interval: Annotated[float, Form(ge=0.25, le=10, allow_inf_nan=False)] = 1.0,
        top_k: Annotated[int, Form(ge=1, le=20)] = 6,
        min_gap: Annotated[float, Form(ge=0, le=60, allow_inf_nan=False)] = 3.0,
        method: Annotated[Literal["colour", "clip"], Form()] = "colour",
        min_score: Annotated[float | None, Form(ge=-1, le=1, allow_inf_nan=False)] = None,
    ):
        video_name = _display_filename(video_file.filename, "video.mp4")
        art_name = _display_filename(art_file.filename, "reference.png")
        video_ext = Path(video_name).suffix.lower()
        art_ext = Path(art_name).suffix.lower()
        if video_ext not in VIDEO_EXTENSIONS:
            raise HTTPException(422, "Choose an MP4, MOV, M4V, AVI, MKV or WebM video.")
        if art_ext not in IMAGE_EXTENSIONS:
            raise HTTPException(422, "Choose a JPG, PNG, WebP, BMP or TIFF reference image.")
        settings = SearchSettings(interval=interval, top_k=top_k, min_gap=min_gap, method=method, min_score=min_score)
        job_id, directory = manager.new(settings, video_name, art_name, synthetic=False)
        video_path = directory / f"video{video_ext}"
        art_path = directory / f"artwork{art_ext}"
        try:
            await _save_upload(video_file, video_path, MAX_VIDEO_MB)
            await _save_upload(art_file, art_path, MAX_IMAGE_MB)
        except Exception:
            manager.update(job_id, status="error", stage="error", error="The upload did not finish.")
            raise
        manager.submit(job_id, video_path, art_path)
        return {"job_id": job_id}

    @application.post("/api/demo/search", status_code=202)
    def demo_search(settings: SearchSettings):
        fixture = ensure_demo(demo_dir)
        job_id, directory = manager.new(settings, "Synthetic palette scenes.mp4", "Synthetic reference.png", synthetic=True)
        video_path = directory / "video.mp4"
        art_path = directory / "artwork.png"
        shutil.copyfile(fixture["video"], video_path)
        shutil.copyfile(fixture["reference"], art_path)
        manager.submit(job_id, video_path, art_path)
        return {"job_id": job_id}

    @application.get("/api/jobs/{job_id}")
    def job(job_id: str):
        return manager.get(job_id)

    @application.get("/api/jobs/{job_id}/export.json")
    def export_metadata(job_id: str):
        record = manager.get(job_id)
        if record["status"] != "complete":
            raise HTTPException(409, "The search record is available after the search finishes.")
        return Response(json.dumps(record, ensure_ascii=False, indent=2) + "\n", media_type="application/json",
                        headers={"Content-Disposition": f'attachment; filename="frame-echo-{job_id[:8]}.json"'})

    @application.get("/api/jobs/{job_id}/export.csv")
    def export(job_id: str):
        record = manager.get(job_id)
        if record["status"] != "complete":
            raise HTTPException(409, "Results are available after the search finishes.")
        output = io.StringIO(newline="")
        columns = ["job_id", "synthetic", "video_filename", "video_sha256", "reference_filename", "reference_sha256",
                   "method", "model_id", "min_score", "match_status", "interval_seconds", "min_gap_seconds", "requested_top_k", "sampled_frames",
                   "timestamp_source", "duration_source", "decoded_last_timestamp", "sampling_restarted",
                   "rank", "timestamp_seconds", "timestamp_label", "cosine_similarity"]
        writer = csv.DictWriter(output, fieldnames=columns)
        writer.writeheader()
        for result in record["results"]:
            writer.writerow({
                "job_id": job_id, "synthetic": record["synthetic"],
                "video_filename": _csv_text(record["video"]["filename"]), "video_sha256": record["video"]["sha256"],
                "reference_filename": _csv_text(record["reference"]["filename"]), "reference_sha256": record["reference"]["sha256"],
                "method": record["settings"]["method"], "model_id": record["model_id"],
                "min_score": "" if record["settings"].get("min_score") is None else record["settings"]["min_score"],
                "match_status": record.get("match_status", "matches_found" if record["results"] else "no_match"),
                "interval_seconds": record["settings"]["interval"], "min_gap_seconds": record["settings"]["min_gap"],
                "requested_top_k": record["settings"]["top_k"], "sampled_frames": record["frames_total"],
                "timestamp_source": record["video"]["timestamp_source"],
                "duration_source": record["video"].get("duration_source", ""),
                "decoded_last_timestamp": record["video"].get("decoded_last_timestamp", ""),
                "sampling_restarted": record["video"].get("sampling_restarted", False),
                "rank": result["rank"],
                "timestamp_seconds": f"{result['timestamp']:.6f}", "timestamp_label": result["timestamp_label"],
                "cosine_similarity": f"{result['score']:.8f}",
            })
        return Response("\ufeff" + output.getvalue(), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="frame-echo-{job_id[:8]}.csv"'})

    return application


app = create_app()
