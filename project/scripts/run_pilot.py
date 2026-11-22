"""Reproducible first real-footage pilot for Frame Echo. No model training."""
from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import html
import importlib.metadata
import io
import json
import os
import platform
import shutil
import ssl
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageOps

PLAN = [
    ("A01", 20684, "Urban buildings, walking figures, muted colours and street perspective"),
    ("A02", 28560, "Warm/cool interior colours, furniture and architectural perspective"),
    ("A03", 27992, "Green outdoor space, groups of figures and leisure"),
    ("A04", 16568, "Green/blue repetition and texture; an exploratory thematic contrast"),
    ("A05", 111442, "Indoor figures, warm colours, patterned surfaces and close interaction"),
]
MET_PLAN = [
    ("A01", 437310, "Urban buildings, walking figures, muted colours and street perspective"),
    ("A02", 438817, "Indoor figures, architecture, wooden surfaces and spatial depth"),
    ("A03", 436965, "Green outdoor space, human figures and leisure"),
    ("A04", 436535, "Green/blue landscape, repeated organic shapes and painterly texture"),
    ("A05", 437878, "Seated indoor figure, warm colours, patterned surfaces and door perspective"),
]
VIDEO_DESCRIPTIONS = [
    ("edited urban/vehicle/people footage", "Portrait-format edited video: cars, tall buildings, a woman and a cafe; visible platform marks and subtitles."),
    ("museum/interior/people footage", "Museum-style interiors with wooden display cabinets, objects, books and people; visible platform marks and subtitles."),
    ("historic-house exhibition/garden footage", "Historic-house exhibition, contemporary objects, patterned floors, garden and brick passage; visible platform marks and subtitles."),
]


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".partial")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def write_csv(path, rows):
    if not rows:
        return
    with Path(path).open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def fetch(url):
    request = urllib.request.Request(url, headers={"User-Agent": "FrameEcho-student-research/0.1", "Accept": "*/*"})
    # Use the OS certificate store on this Mac; certificate checks stay enabled.
    try:
        import truststore
        context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    except ImportError:
        context = ssl.create_default_context()
    last_error = None
    for attempt in range(2):
        try:
            with urllib.request.urlopen(request, timeout=15, context=context) as response:
                return response.read()
        except Exception as error:
            last_error = error
            if isinstance(error, urllib.error.HTTPError) and error.code in {400, 401, 403, 404}:
                break
            if attempt < 1:
                time.sleep(1 + attempt)
    raise RuntimeError(f"Could not retrieve official source {url}: {last_error}")


def prepare(root, run, args):
    from app.main import _prepare_reference
    from app.video import extract_frames, probe_video
    art_dir = root / "data" / "raw" / "artworks" / f"pilot-{args.date}"
    art_dir.mkdir(parents=True, exist_ok=True)
    artworks = []
    selection = MET_PLAN if args.art_source == "met" else PLAN
    institution = "The Metropolitan Museum of Art" if args.art_source == "met" else "Art Institute of Chicago"
    for asset_id, object_id, rationale in selection:
        metadata_file = run / "sources" / f"{asset_id}_{args.art_source}.json"
        if metadata_file.exists():
            response = json.loads(metadata_file.read_text(encoding="utf-8"))
        else:
            if args.art_source == "met":
                raw = json.loads(fetch(f"https://collectionapi.metmuseum.org/public/collection/v1/objects/{object_id}"))
                keep = ["objectID", "title", "artistDisplayName", "objectDate", "isPublicDomain", "primaryImage", "primaryImageSmall", "objectURL", "creditLine", "accessionNumber"]
                response = {"data": {key: raw.get(key) for key in keep}, "retrieved_for_pilot": args.date}
                write_json(metadata_file, response)
            else:
                response = json.loads(fetch(f"https://api.artic.edu/api/v1/artworks/{object_id}"))
            # Do not retain the API's long-form interpretive descriptions.
                source = response["data"]
                keep = ["id", "title", "artist_display", "date_display", "image_id", "is_public_domain", "copyright_notice", "main_reference_number", "dimensions"]
                response = {"data": {key: source.get(key) for key in keep}, "config": response.get("config", {}),
                            "license_links": response.get("license_links", []), "retrieved_for_pilot": args.date}
                write_json(metadata_file, response)
        data = response["data"]
        if args.art_source == "met":
            valid = data.get("isPublicDomain") is True and bool(data.get("primaryImageSmall") or data.get("primaryImage"))
            image_url = data.get("primaryImageSmall") or data.get("primaryImage")
            artist, date = data.get("artistDisplayName"), data.get("objectDate")
            object_url = data.get("objectURL") or f"https://www.metmuseum.org/art/collection/search/{object_id}"
            api_url = f"https://collectionapi.metmuseum.org/public/collection/v1/objects/{object_id}"
        else:
            valid = data.get("is_public_domain") is True and bool(data.get("image_id"))
            image_url = f"https://www.artic.edu/iiif/2/{data['image_id']}/full/843,/0/default.jpg"
            artist, date = data["artist_display"], data["date_display"]
            object_url = f"https://www.artic.edu/artworks/{object_id}"
            api_url = f"https://api.artic.edu/api/v1/artworks/{object_id}"
        if not valid:
            raise RuntimeError(f"{asset_id}: the institution has not marked this image public domain; stop rather than substitute silently.")
        fallback_source = ""
        original = art_dir / f"{asset_id}_{args.art_source}_{object_id}.jpg"
        if not original.exists():
            temporary = original.with_suffix(".partial")
            try:
                image_bytes = fetch(image_url)
            except RuntimeError as error:
                if args.art_source != "artic" or "403" not in str(error):
                    raise
                # Alternate institutional IIIF host documented in ArtIC's own
                # mobile CMS source, retaining the same image identifier.
                image_url = f"https://lakeimagesweb.artic.edu/iiif/2/{data['image_id']}/full/843,/0/default.jpg"
                fallback_source = "https://github.com/art-institute-of-chicago/aic-mobile-cms/blob/main/sites/all/modules/custom/aicapp/aicapp.module"
                print(f"Primary image service returned 403; trying documented institutional host for {asset_id}", flush=True)
                image_bytes = fetch(image_url)
            temporary.write_bytes(image_bytes)
            with Image.open(temporary) as image:
                image.verify()
            temporary.replace(original)
            time.sleep(1)
        normalized = run / "queries" / f"{asset_id}.png"
        normalized.parent.mkdir(parents=True, exist_ok=True)
        _prepare_reference(original, normalized)
        artwork = {"asset_id": asset_id, "institution": institution, "object_id": object_id,
                   "title": data["title"], "artist": artist, "date": date,
                   "object_url": object_url, "api_url": api_url, "image_url": image_url,
                   "alternate_image_host_source": fallback_source,
                   "is_public_domain": True, "usage_basis": "Institution API public-domain flag=true; institutional Open Access/CC0 image",
                   "selection_rationale": rationale, "original_path": str(original.relative_to(root)),
                   "normalized_path": str(normalized.relative_to(root)), "original_sha256": sha256(original),
                   "normalized_sha256": sha256(normalized)}
        artworks.append(artwork)
        print(f"ART {asset_id}: {artwork['title']} | {artwork['artist']} | public domain confirmed", flush=True)
    candidates = sorted(path for path in (root / "data" / "raw" / "videos").iterdir()
                        if path.is_file() and path.suffix.lower() in {".mp4", ".mov", ".m4v", ".avi", ".webm", ".mkv"})
    if len(candidates) != 3:
        raise RuntimeError("The predeclared pilot expects exactly the three inspected videos. Review the selection before changing it.")
    videos = []
    for index, source in enumerate(candidates, 1):
        video_id = f"V{index:02d}"
        source_hash = sha256(source)
        frame_index_path = run / "frames" / video_id / "index.json"
        if frame_index_path.exists():
            cached = json.loads(frame_index_path.read_text(encoding="utf-8"))
            if cached["source_sha256"] != source_hash or cached["interval"] != args.interval:
                raise RuntimeError("Cached frame inputs changed. Choose a new run date/directory instead of overwriting an experiment.")
            info, frames = cached["info"], cached["frames"]
            if any(not (root / frame["path"]).exists() or sha256(root / frame["path"]) != frame["sha256"] for frame in frames):
                raise RuntimeError("A cached sampled frame is missing or modified.")
        else:
            info, sampled = extract_frames(source, run / "frames" / video_id, args.interval)
            frames = [{"path": str(frame["path"].relative_to(root)), "timestamp": frame["timestamp"], "sha256": sha256(frame["path"])} for frame in sampled]
            write_json(frame_index_path, {"source_sha256": source_hash, "interval": args.interval, "info": info, "frames": frames})
        category, description = VIDEO_DESCRIPTIONS[index - 1]
        videos.append({"asset_id": video_id, "filename": source.name, "path": str(source.relative_to(root)),
                       "sha256": source_hash, "category": category, "description": description, "info": info,
                       "frames": frames, "provenance": "User-confirmed online reference video; original URL and creator pending",
                       "source_url": "", "capture_date": "unknown", "identity_match_status": "not assessed"})
        print(f"VIDEO {video_id}: {len(frames)} shared frames | {info['duration']:.2f}s | {info['timestamp_source']}", flush=True)
    metadata = {"date": args.date, "status": "prepared", "design": "Exploratory pilot, not participant evaluation",
                "artwork_source": args.art_source,
                "source_selection_note": "ArtIC primary images returned 403 and its documented alternate host did not return; switched to Met before any rankings were computed." if args.art_source == "met" else "ArtIC pilot selection",
                "settings": {"interval": args.interval, "top_k": args.top_k, "min_gap": args.min_gap},
                "selection_frozen_before_ranking": True, "artworks": artworks, "videos": videos}
    write_json(run / "manifest.json", metadata)
    # Keep the general source manifest consistent without discarding unrelated rows.
    manifest = root / "docs" / "data-manifest.csv"
    with manifest.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        columns, existing = reader.fieldnames, list(reader)
    additions = []
    for video in videos:
        additions.append(dict(asset_id=video["asset_id"], asset_type="video", filename=video["path"], video_category=video["category"],
                              title_or_description=video["description"], creator="unconfirmed", source_url="", captured_or_accessed_date=args.date,
                              duration_seconds=video["info"]["duration"], usage_notes="User-confirmed online reference; original link pending; local pilot",
                              query_artwork_present_in_video="unknown", related_video_id="", notes="Date is local access date, not capture date."))
    for artwork in artworks:
        additions.append(dict(asset_id=artwork["asset_id"], asset_type="artwork", filename=artwork["original_path"], video_category="",
                              title_or_description=artwork["title"], creator=artwork["artist"], source_url=artwork["object_url"], captured_or_accessed_date=args.date,
                              duration_seconds="", usage_notes=artwork["usage_basis"], query_artwork_present_in_video="unknown", related_video_id="V01;V02;V03",
                              notes=artwork["selection_rationale"]))
    ids = {row["asset_id"] for row in additions}
    retained = [row for row in existing if row["asset_id"] not in ids]
    with manifest.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(retained + additions)
    ignored = root / ".gitignore"
    text = ignored.read_text(encoding="utf-8")
    if "data/pilots/" not in text.splitlines():
        ignored.write_text(text.rstrip() + "\ndata/pilots/\n", encoding="utf-8")
    return metadata


def encode_images(encoder, paths, batch_size):
    values = []
    for start in range(0, len(paths), batch_size):
        images = []
        try:
            for path in paths[start:start + batch_size]:
                with Image.open(path) as opened:
                    images.append(opened.convert("RGB"))
            values.append(encoder.encode(images))
        finally:
            for image in images:
                image.close()
    return np.concatenate(values, axis=0)


def run_retrieval(root, run, args):
    from app.retrieval import get_encoder, rank_matches
    from app.video import timestamp_label
    import torch
    torch.set_num_threads(min(4, os.cpu_count() or 1))
    metadata = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    if metadata["settings"] != {"interval": args.interval, "top_k": args.top_k, "min_gap": args.min_gap}:
        raise RuntimeError("Settings differ from the prepared pilot.")
    for video in metadata["videos"]:
        if sha256(root / video["path"]) != video["sha256"]:
            raise RuntimeError("A source video changed after preparation.")
        if any(sha256(root / frame["path"]) != frame["sha256"] for frame in video["frames"]):
            raise RuntimeError("A shared sampled frame changed after preparation.")
    for artwork in metadata["artworks"]:
        if sha256(root / artwork["original_path"]) != artwork["original_sha256"] or sha256(root / artwork["normalized_path"]) != artwork["normalized_sha256"]:
            raise RuntimeError("An artwork query changed after preparation.")
    rows, cases, timings = [], [], []
    for method in ("colour", "clip"):
        started = time.perf_counter()
        encoder = get_encoder(method, root / "data" / "models" / "open_clip_model.safetensors")
        timings.append({"stage": "load_model", "method": method, "video_id": "", "seconds": time.perf_counter() - started})
        preprocess = str(getattr(encoder, "preprocess", "RGB -> resize144x144 -> HSV global+3x3 histograms"))
        started = time.perf_counter()
        queries = encode_images(encoder, [root / art["normalized_path"] for art in metadata["artworks"]], 8)
        timings.append({"stage": "encode_queries", "method": method, "video_id": "", "seconds": time.perf_counter() - started})
        for video in metadata["videos"]:
            started = time.perf_counter()
            features = encode_images(encoder, [root / frame["path"] for frame in video["frames"]], 16 if method == "clip" else 32)
            elapsed = time.perf_counter() - started
            timings.append({"stage": "encode_video", "method": method, "video_id": video["asset_id"], "seconds": elapsed})
            feature_file = run / "features" / f"{video['asset_id']}_{method}.npz"
            feature_file.parent.mkdir(parents=True, exist_ok=True)
            np.savez_compressed(feature_file, frames=features, queries=queries,
                                timestamps=np.asarray([frame["timestamp"] for frame in video["frames"]]))
            assert np.isfinite(features).all() and np.allclose(np.linalg.norm(features, axis=1), 1, atol=1e-5)
            for art, query in zip(metadata["artworks"], queries):
                matches = rank_matches(query, features, [frame["timestamp"] for frame in video["frames"]], args.top_k, args.min_gap)
                result = []
                for rank, match in enumerate(matches, 1):
                    frame = video["frames"][match["index"]]
                    row = {"video_id": video["asset_id"], "artwork_id": art["asset_id"], "artwork_title": art["title"],
                           "method": method, "model_id": encoder.model_id, "rank": rank, "timestamp_seconds": match["timestamp"],
                           "timestamp_label": timestamp_label(match["timestamp"]), "cosine_similarity": match["score"],
                           "interval_seconds": args.interval, "minimum_gap_seconds": args.min_gap, "requested_top_k": args.top_k,
                           "sampled_frames": len(video["frames"]), "frame_path": frame["path"], "frame_sha256": frame["sha256"],
                           "video_sha256": video["sha256"], "artwork_sha256": art["original_sha256"],
                           "normalized_query_sha256": art["normalized_sha256"], "timestamp_source": video["info"]["timestamp_source"],
                           "duration_source": video["info"]["duration_source"], "synthetic": False, "identity_match_status": "not assessed"}
                    rows.append(row)
                    result.append(row)
                cases.append({"video_id": video["asset_id"], "artwork_id": art["asset_id"], "method": method,
                              "preprocess": preprocess, "matches": result})
            print(f"ENCODED {video['asset_id']} / {method}: {len(video['frames'])} frames in {elapsed:.2f}s, all five queries ranked", flush=True)
    overlap = []
    for video in metadata["videos"]:
        for art in metadata["artworks"]:
            selected = {method: {row["timestamp_seconds"] for row in rows if row["video_id"] == video["asset_id"] and row["artwork_id"] == art["asset_id"] and row["method"] == method} for method in ("colour", "clip")}
            intersection = len(selected["colour"] & selected["clip"])
            union = len(selected["colour"] | selected["clip"])
            overlap.append({"video_id": video["asset_id"], "artwork_id": art["asset_id"], "exact_timestamp_overlap": intersection,
                            "colour_results": len(selected["colour"]), "clip_results": len(selected["clip"]),
                            "timestamp_set_jaccard": intersection / union if union else 0})
    packages = {name: importlib.metadata.version(name) for name in ["numpy", "Pillow", "opencv-python-headless", "torch", "open_clip_torch"]}
    checkpoint = json.loads((root / "data" / "models" / "checkpoint.json").read_text(encoding="utf-8"))
    actual_checkpoint_hash = sha256(root / "data" / "models" / "open_clip_model.safetensors")
    if actual_checkpoint_hash != checkpoint["sha256"]:
        raise RuntimeError("The local model checksum differs from the download record.")
    metadata.update(status="complete", cases=cases, timings=timings, overlap=overlap,
                    environment={"python": sys.version, "platform": platform.platform(), "packages": packages,
                                 "device": "cpu", "torch_threads": torch.get_num_threads()}, checkpoint=checkpoint,
                    code_hashes={name: sha256(root / name) for name in ["app/retrieval.py", "app/video.py", "app/main.py", "scripts/run_pilot.py"]})
    assert len(cases) == len(metadata["videos"]) * len(metadata["artworks"]) * 2
    assert all(0 < len(case["matches"]) <= args.top_k for case in cases)
    write_csv(run / "rankings.csv", rows)
    write_csv(run / "method-overlap.csv", overlap)
    write_csv(run / "timings.csv", timings)
    write_json(run / "results.json", metadata)
    render_report(root, run, metadata, encoder)
    print(f"COMPLETE: {len(cases)} retrieval conditions, {len(rows)} ranked records. {run / 'index.html'}", flush=True)


def image_uri(path, size=(480, 320)):
    with Image.open(path) as opened:
        image = opened.convert("RGB")
        image.thumbnail(size, Image.Resampling.LANCZOS)
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=86)
    return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def render_report(root, run, data, clip_encoder):
    escape = html.escape
    heading = f"Frame Echo · First real-footage pilot · {data['date']}"
    settings = data["settings"]
    ranked_records = sum(len(case["matches"]) for case in data["cases"])
    parts = [f'<!doctype html><html lang="zh"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{heading}</title>',
             '<style>body{font:15px/1.6 system-ui,sans-serif;background:#f5f2e9;color:#242722;margin:0}main{max-width:1280px;margin:auto;padding:32px}h1{font-size:32px}h2{font-size:23px;margin:0}h3{font-size:16px}a{color:#a7472f}.note{background:#e6ebdf;padding:16px;border-left:3px solid #7a8868}.case{border:1px solid #d8d8cb;background:#fcfaf5;padding:20px;margin:28px 0}.reference{display:flex;align-items:center;gap:24px}.reference img{width:220px;height:180px;object-fit:contain;background:#e8e8de}.grid{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:10px}.match img{width:100%;height:160px;object-fit:contain;background:#e9e8dd}.match{font-size:12px}small{color:#66705d}nav{position:sticky;top:0;background:#f5f2e9eb;padding:10px;backdrop-filter:blur(6px)}nav button{padding:8px 14px;margin:4px;border:1px solid #b9bcae;background:#fffaf0;color:#242722;cursor:pointer}nav button.active{background:#a7472f;color:white}@media(max-width:760px){main{padding:16px}.grid{grid-template-columns:repeat(2,1fr)}.reference{display:block}.reference img{width:100%}}[hidden]{display:none!important}</style><main>',
             f'<h1>{heading}</h1><p class="note">{len(data["videos"])} 段真实网络参考视频 × {len(data["artworks"])} 张公开域艺术作品 × 2 种检索方法，共 {len(data["cases"])} 个条件、{ranked_records} 条排名记录。此为探索性程序试验；尚无用户评分或检索准确率。视频原链接及创作者待补。</p>',
             f'<p>固定参数：每 {settings["interval"]:g} 秒抽帧；每个条件至多返回 {settings["top_k"]} 帧；结果时间最小间隔 {settings["min_gap"]:g} 秒。两种方法共享同一批抽取帧。分数仅用于各方法内部排序，不能当作概率或美学评分。下列画面均按完整图像显示。</p>',
             '<nav>按视频查看：<button class="active" data-video="all">全部</button><button data-video="V01">V01 城市/汽车/人物</button><button data-video="V02">V02 馆内展柜</button><button data-video="V03">V03 展览/庭园</button></nav>']
    for video in data["videos"]:
        parts.append(f'<section data-section="{video["asset_id"]}"><h2>{video["asset_id"]} · {escape(video["description"])}</h2><p>{escape(video["filename"])} · {video["info"]["duration"]:.2f}s · {len(video["frames"])} sampled frames · {escape(video["info"]["timestamp_source"])}</p>')
        for art in data["artworks"]:
            parts.append(f'<article class="case"><div class="reference"><img src="{image_uri(root / art["normalized_path"])}" alt="Reference artwork"><div><h2>{art["asset_id"]} · {escape(art["title"])}</h2><p>{escape(art["artist"])} · {escape(art["date"])}</p><p>{escape(art["selection_rationale"])}</p><a href="{escape(art["object_url"])}">Official artwork source · Public Domain</a></div></div>')
            for method in ("colour", "clip"):
                case = next(case for case in data["cases"] if case["video_id"] == video["asset_id"] and case["artwork_id"] == art["asset_id"] and case["method"] == method)
                parts.append(f'<h3>{"Colour + spatial layout" if method == "colour" else "OpenCLIP image features"}</h3><div class="grid">')
                for match in case["matches"]:
                    parts.append(f'<div class="match"><img loading="lazy" src="{image_uri(root / match["frame_path"])}" alt="Video frame"><b>#{match["rank"]} · {match["timestamp_label"]}</b><br><small>cosine {match["cosine_similarity"]:.4f}</small></div>')
                parts.append('</div>')
            parts.append('</article>')
        parts.append('</section>')
    parts.append('<p class="note">限制：视频带有字幕/水印；原始来源待补。CLIP 默认使用中心裁剪，颜色方法使用整图；方法差异包含预处理差异。时间间隔并不保证镜头内容去重。馆内是否出现查询作品本身尚未逐帧确认。</p><script>document.querySelectorAll("nav button").forEach(button=>button.addEventListener("click",()=>{document.querySelectorAll("nav button").forEach(other=>other.classList.toggle("active",other===button));document.querySelectorAll("[data-section]").forEach(section=>section.hidden=button.dataset.video!=="all"&&section.dataset.section!==button.dataset.video)}));</script></main></html>')
    (run / "index.html").write_text("\n".join(parts), encoding="utf-8")
    # Compact full-frame overview: each row compares the two top-ranked moments
    # for one artwork against all three videos. This is an inspection aid only.
    board = Image.new("RGB", (1680, 5 * 215 + 50), "#f5f2e9")
    draw = ImageDraw.Draw(board)
    draw.text((12, 10), "REFERENCE | V01 colour / CLIP | V02 colour / CLIP | V03 colour / CLIP — top-ranked full frames", fill="#242722")
    for row, art in enumerate(data["artworks"]):
        paths = [(root / art["normalized_path"], art["asset_id"] + " reference")]
        for video in data["videos"]:
            for method in ("colour", "clip"):
                case = next(case for case in data["cases"] if case["video_id"] == video["asset_id"] and case["artwork_id"] == art["asset_id"] and case["method"] == method)
                match = case["matches"][0]
                paths.append((root / match["frame_path"], f"{video['asset_id']} {method} {match['timestamp_label']}"))
        for column, (path, label) in enumerate(paths):
            with Image.open(path) as image:
                tile = ImageOps.contain(image.convert("RGB"), (230, 174))
            x, y = column * 240 + (240 - tile.width) // 2, 40 + row * 215 + (174 - tile.height) // 2
            board.paste(tile, (x, y))
            draw.text((column * 240 + 6, 40 + row * 215 + 181), label, fill="#242722")
    board.save(run / "top1-overview.jpg", quality=94)
    # Show exactly which content the model sees under its default centre crop.
    crop_board = Image.new("RGB", (1200, 3 * 260 + 40), "#f5f2e9")
    crop_draw = ImageDraw.Draw(crop_board)
    crop_draw.text((12, 10), "CLIP preprocessing diagnostic: full sampled frame (left) / actual centre crop (right)", fill="#242722")
    for index, video in enumerate(data["videos"]):
        frame = video["frames"][len(video["frames"]) // 2]
        with Image.open(root / frame["path"]) as image:
            original = image.convert("RGB")
            spatial = original
            for transform in clip_encoder.preprocess.transforms:
                if transform.__class__.__name__ in {"Resize", "CenterCrop"}:
                    spatial = transform(spatial)
        for column, image in enumerate((original, spatial)):
            tile = ImageOps.contain(image, (570, 220))
            crop_board.paste(tile, (column * 600 + (600 - tile.width) // 2, 38 + index * 260))
        crop_draw.text((12, 38 + index * 260 + 225), f"{video['asset_id']} | {frame['timestamp']:.3f}s | left full frame; right actual CLIP crop", fill="#242722")
    crop_board.save(run / "clip-crop-diagnostic.jpg", quality=94)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--date", default="2026-11-10")
    parser.add_argument("--phase", choices=["prepare", "run", "all"], default="all")
    parser.add_argument("--art-source", choices=["met", "artic"], default="met")
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument("--top-k", type=int, default=6)
    parser.add_argument("--min-gap", type=float, default=3.0)
    args = parser.parse_args()
    root = args.project_root.resolve()
    if not (root / "app" / "retrieval.py").is_file():
        raise SystemExit("Project root does not contain Frame Echo.")
    sys.path.insert(0, str(root))
    run = root / "data" / "pilots" / args.date
    run.mkdir(parents=True, exist_ok=True)
    target = root / "scripts" / "run_pilot.py"
    if Path(__file__).resolve() != target.resolve():
        shutil.copyfile(__file__, target)
    if args.phase in {"prepare", "all"}:
        prepare(root, run, args)
    if args.phase in {"run", "all"}:
        run_retrieval(root, run, args)


if __name__ == "__main__":
    main()
