"""Explicitly prepare the official OpenCLIP checkpoint for local inference."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.retrieval import CLIP_MODEL_REPO, CLIP_WEIGHT_FILENAME


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "data" / "models")
    options = parser.parse_args()
    try:
        from huggingface_hub import HfApi, hf_hub_download
    except ImportError:
        raise SystemExit("Install requirements-clip.txt first.")
    directory = options.output_dir.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / CLIP_WEIGHT_FILENAME
    if destination.exists() and destination.stat().st_size > 100_000_000:
        print(f"Local checkpoint already exists: {destination}")
        return
    print(f"Downloading official checkpoint from {CLIP_MODEL_REPO} (approximately 605 MB).", flush=True)
    # Resolve main once so the downloaded weight's exact repository commit is
    # recorded for methods reporting and repeatability.
    revision = HfApi(token=False).model_info(CLIP_MODEL_REPO).sha
    cached = Path(hf_hub_download(repo_id=CLIP_MODEL_REPO, filename=CLIP_WEIGHT_FILENAME,
                                revision=revision, cache_dir=directory / ".hub", token=False))
    temporary = directory / f"{CLIP_WEIGHT_FILENAME}.partial"
    shutil.copyfile(cached, temporary)
    digest = hashlib.sha256()
    with temporary.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    temporary.replace(destination)
    metadata = {"repo_id": CLIP_MODEL_REPO, "revision": revision, "filename": CLIP_WEIGHT_FILENAME,
                "sha256": digest.hexdigest(), "size_bytes": destination.stat().st_size,
                "downloaded_at": datetime.now(timezone.utc).isoformat()}
    (directory / "checkpoint.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    print(f"Ready for local inference: {destination}")


if __name__ == "__main__":
    main()
