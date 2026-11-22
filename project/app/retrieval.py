"""Explicit, comparable image retrieval methods for Frame Echo.

The colour baseline measures the distribution of colours globally and in a 3x3
grid. It does not recognise objects, infer artistic influence, or predict beauty.
CLIP is an optional, locally loaded pretrained image-feature method. Neither
method trains on the uploaded videos, and neither silently substitutes the other.
"""

from __future__ import annotations

import importlib.util
from numbers import Integral, Real
from pathlib import Path
from typing import Protocol, Sequence

import numpy as np
from PIL import Image, ImageOps


CLIP_MODEL_NAME = "ViT-B-32"
CLIP_PRETRAINED = "laion2b_s34b_b79k"
CLIP_MODEL_REPO = "laion/CLIP-ViT-B-32-laion2B-s34B-b79K"
CLIP_WEIGHT_FILENAME = "open_clip_model.safetensors"


class Encoder(Protocol):
    def encode(self, images: Sequence[Image.Image]) -> np.ndarray:
        """Return one finite L2-normalised feature vector per input image."""


def _rgb(image: Image.Image) -> Image.Image:
    if not isinstance(image, Image.Image):
        raise TypeError("Encoders require PIL images.")
    if image.width < 1 or image.height < 1:
        raise ValueError("Images must have a positive width and height.")
    image = ImageOps.exif_transpose(image)
    if "A" in image.getbands() or "transparency" in image.info:
        rgba = image.convert("RGBA")
        background = Image.new("RGBA", rgba.size, "white")
        return Image.alpha_composite(background, rgba).convert("RGB")
    return image.convert("RGB")


class ColourEncoder:
    """50% global + 50% spatial HSV colour histograms, square-root embedded.

    Images are resized to 144x144 (relative positions, with no centre crop).
    Each cell has 12 hue x 4 saturation x 4 value bins. Each histogram is L1
    normalised and square-rooted, making its dot product a histogram affinity.
    The concatenated, weighted feature has 1920 dimensions and unit L2 norm.
    """

    name = "colour"
    dimension = 1920
    model_id = "spatial-hsv-12x4x4-grid3-global50-v1"

    @staticmethod
    def _histogram(pixels: np.ndarray) -> np.ndarray:
        # Pillow's HSV channels each use integer values in [0, 255]. Use uint16
        # before multiplying so that quantisation cannot overflow uint8.
        values = pixels.astype(np.uint16)
        hue = np.minimum(values[..., 0] * 12 // 256, 11)
        saturation = np.minimum(values[..., 1] * 4 // 256, 3)
        value = np.minimum(values[..., 2] * 4 // 256, 3)
        bins = hue * 16 + saturation * 4 + value
        histogram = np.bincount(bins.ravel(), minlength=192).astype(np.float32)
        return np.sqrt(histogram / histogram.sum())

    def encode(self, images: Sequence[Image.Image]) -> np.ndarray:
        features = []
        for image in images:
            resized = _rgb(image).resize((144, 144), Image.Resampling.BILINEAR)
            pixels = np.asarray(resized.convert("HSV"))
            parts = [self._histogram(pixels) * np.sqrt(0.5)]
            for row in range(3):
                for column in range(3):
                    tile = pixels[row * 48:(row + 1) * 48,
                                  column * 48:(column + 1) * 48]
                    parts.append(self._histogram(tile) * np.sqrt(0.5 / 9))
            feature = np.concatenate(parts).astype(np.float32)
            feature /= np.linalg.norm(feature)
            features.append(feature)
        if not features:
            return np.empty((0, self.dimension), dtype=np.float32)
        return np.stack(features)


def available_clip(model_path: Path) -> dict:
    """Check package/weight presence without importing torch or making requests.

    Presence is a capability hint, not a guarantee that a particular installation
    can load its weights; a load failure is reported by ClipEncoder explicitly.
    """
    missing = []
    for module in ("torch", "open_clip", "safetensors"):
        try:
            found = importlib.util.find_spec(module) is not None
        except (ImportError, ValueError, ModuleNotFoundError):
            found = False
        if not found:
            missing.append(module)
    if missing:
        return {
            "available": False,
            "reason": "CLIP is not set up on this computer yet. The colour method is ready to use.",
            "missing": missing,
        }
    path = Path(model_path)
    if not path.is_file() or path.stat().st_size == 0:
        return {
            "available": False,
            "reason": "The CLIP model has not been downloaded for offline use yet.",
            "missing": ["weights"],
        }
    return {"available": True, "reason": "Ready for local image-feature retrieval.", "missing": []}


class ClipEncoder:
    """ViT-B-32 image features from an explicitly supplied local checkpoint."""

    name = "clip"
    dimension = 512
    model_id = f"{CLIP_MODEL_NAME}/{CLIP_PRETRAINED}"

    def __init__(self, model_path: Path, device: str = "cpu") -> None:
        capability = available_clip(model_path)
        if not capability["available"]:
            raise RuntimeError(capability["reason"])
        # Optional dependencies are imported only when this method is selected.
        try:
            import torch
            import open_clip

            self._torch = torch
            self.device = device
            self.model, _, self.preprocess = open_clip.create_model_and_transforms(
                CLIP_MODEL_NAME,
                pretrained=str(Path(model_path).resolve()),
                device=device,
                precision="fp32",
                weights_only=True,
                pretrained_image=False,
                pretrained_text=False,
            )
            self.model.eval()
        except Exception as exc:
            raise RuntimeError(
                "CLIP could not load its local model. Check the optional installation and model file."
            ) from exc

    def encode(self, images: Sequence[Image.Image]) -> np.ndarray:
        if not images:
            return np.empty((0, self.dimension), dtype=np.float32)
        processed = [self.preprocess(_rgb(image)) for image in images]
        batch = self._torch.stack(processed).to(self.device)
        with self._torch.inference_mode():
            vectors = self.model.encode_image(batch)
            vectors = vectors / vectors.norm(dim=-1, keepdim=True).clamp_min(1e-12)
        result = vectors.detach().cpu().float().numpy()
        if not np.isfinite(result).all() or np.any(np.linalg.norm(result, axis=1) == 0):
            raise RuntimeError("CLIP returned invalid image features.")
        return result


def get_encoder(method: str, model_path: Path) -> Encoder:
    if method == "colour":
        return ColourEncoder()
    if method == "clip":
        return ClipEncoder(model_path)
    raise ValueError(f"Unknown retrieval method: {method!r}.")


def rank_matches(
    query_features: np.ndarray,
    frame_features: np.ndarray,
    timestamps: Sequence[float],
    top_k: int,
    min_gap: float,
    min_score: float | None = None,
) -> list[dict]:
    """Rank by cosine similarity, then greedily apply temporal suppression.

    Equal scores are ordered by earlier video timestamp, then input index.
    A difference exactly equal to min_gap is allowed. Fewer than top_k results
    can be returned when the video contains too few time-separated candidates
    or when a configured minimum score excludes candidates. The threshold is
    inclusive; None disables it. An empty list is a valid no-match outcome.
    Scores are raw cosine similarities, not calibrated probabilities.
    """
    if isinstance(top_k, bool) or not isinstance(top_k, Integral) or top_k < 1:
        raise ValueError("top_k must be a positive integer.")
    if isinstance(min_gap, bool) or not np.isfinite(min_gap) or min_gap < 0:
        raise ValueError("min_gap must be a finite, non-negative number.")
    if min_score is not None:
        if (isinstance(min_score, (bool, np.bool_)) or not isinstance(min_score, Real)
                or not np.isfinite(min_score) or not -1 <= min_score <= 1):
            raise ValueError("min_score must be None or a finite number between -1 and 1.")
    query = np.asarray(query_features, dtype=np.float64)
    frames = np.asarray(frame_features, dtype=np.float64)
    times = np.asarray(timestamps, dtype=np.float64)
    if query.ndim == 2 and query.shape[0] == 1:
        query = query[0]
    if query.ndim != 1 or query.size == 0:
        raise ValueError("Query features must contain exactly one non-empty vector.")
    if frames.ndim != 2 or frames.shape[1] != query.size:
        raise ValueError("Frame features must be a matrix matching the query dimension.")
    if times.ndim != 1 or len(times) != len(frames):
        raise ValueError("Each frame must have exactly one timestamp.")
    if not np.isfinite(query).all() or not np.isfinite(frames).all():
        raise ValueError("Features must contain finite numbers.")
    if not np.isfinite(times).all() or np.any(times < 0):
        raise ValueError("Timestamps must be finite, non-negative seconds.")
    query_norm = np.linalg.norm(query)
    frame_norms = np.linalg.norm(frames, axis=1)
    if query_norm == 0 or np.any(frame_norms == 0):
        raise ValueError("Zero-length feature vectors cannot be compared.")
    if not len(frames):
        return []
    scores = np.clip((frames / frame_norms[:, None]) @ (query / query_norm), -1, 1)
    order = np.lexsort((np.arange(len(frames)), times, -scores))
    selected: list[dict] = []
    for index in order:
        if min_score is not None and float(scores[index]) < min_score:
            break
        time = float(times[index])
        if any(abs(time - match["timestamp"]) + 1e-9 < min_gap for match in selected):
            continue
        selected.append({"index": int(index), "timestamp": time, "score": float(scores[index])})
        if len(selected) == top_k:
            break
    return selected
