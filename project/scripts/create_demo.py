"""Create deterministic geometric test footage, not participant/research data."""

from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]


def scene(index: int, phase: float = 0) -> Image.Image:
    palettes = [
        ("#ddd9c7", "#9aab9b", "#3d6058", "#be6844"),
        ("#e9cc9e", "#cf744a", "#334e62", "#f1e5c9"),
        ("#b9ced2", "#5c8790", "#213d4b", "#f1bb69"),
        ("#ddd2bf", "#9ba693", "#293f3d", "#c49a71"),
        ("#d9c5d6", "#a68aa7", "#544a69", "#e6c1a3"),
        ("#c9d9bd", "#71916c", "#344f45", "#e2cf99"),
    ]
    sky, ground, dark, accent = palettes[index % len(palettes)]
    image = Image.new("RGB", (640, 400), sky)
    draw = ImageDraw.Draw(image)
    horizon = 240 + int(8 * np.sin(phase))
    draw.rectangle((0, horizon, 640, 400), fill=ground)
    draw.ellipse((445, 60, 515, 130), fill=accent)
    draw.polygon([(0, horizon), (120, 140), (260, horizon), (375, 185), (520, horizon)], fill=dark)
    draw.polygon([(250, 400), (360, horizon), (390, horizon), (490, 400)], fill=accent)
    draw.rectangle((70, 275, 112, 350), fill=sky)
    draw.rectangle((80, 240, 101, 278), fill=dark)
    return image


def ensure_demo(output_dir: Path | None = None) -> dict:
    directory = output_dir or ROOT / "data" / "demo"
    directory.mkdir(parents=True, exist_ok=True)
    video = directory / "video.mp4"
    reference = directory / "reference.png"
    manifest = directory / "manifest.json"
    if video.exists() and reference.exists() and manifest.exists():
        return {"video": video, "reference": reference}
    scene(1).save(reference)
    # H.264 is compatible with browser playback. Use mp4v only when the local
    # OpenCV build has no H.264 encoder; the manifest records the actual codec.
    writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*"avc1"), 12, (640, 400))
    codec = "avc1"
    if not writer.isOpened():
        writer.release()
        writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*"mp4v"), 12, (640, 400))
        codec = "mp4v"
    if not writer.isOpened():
        raise RuntimeError("OpenCV could not create the synthetic MP4 demo.")
    try:
        # Each four-second scene is a controlled palette variation. The query
        # matches scene 1 at t=4..8; this only checks plumbing and colour ranking.
        for frame_index in range(24 * 12):
            image = scene(frame_index // 48, (frame_index % 48) / 48 * np.pi * 2)
            writer.write(cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2BGR))
    finally:
        writer.release()
    manifest.write_text(json.dumps({
        "kind": "synthetic_test_fixture",
        "description": "Deterministic geometric palette scenes. Not real artwork, personal footage or research evidence.",
        "duration_seconds": 24,
        "fps": 12,
        "codec": codec,
        "query_scene_seconds": [4, 8],
        "generator": "scripts/create_demo.py",
    }, indent=2) + "\n", encoding="utf-8")
    return {"video": video, "reference": reference}


if __name__ == "__main__":
    paths = ensure_demo()
    print(f"Synthetic demo ready: {paths['video'].parent}")
