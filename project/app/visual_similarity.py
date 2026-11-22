"""Explicit experimental signals for balanced visual retrieval.

The layout signal measures coarse spatial colour distribution, not complete
composition understanding. Default rank-fusion weights are predeclared
heuristics, not learned or validated measures of relevance. Fusion scores are
not cosine similarities, probabilities or aesthetic scores.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from numbers import Integral, Real

import numpy as np
from PIL import Image

DEFAULT_WEIGHTS = {"content": 0.5, "colour": 0.25, "layout": 0.25}
BALANCED_MODEL_ID = "weighted-rrf-clip-full50-globalhsv25-spatialhsv25-k60-v1"
FULL_FRAME_PREPROCESS_ID = "aspect-preserving-longest-edge-model-mean-pad-v1"


def _finite_array(value, name: str) -> np.ndarray:
    try:
        array = np.asarray(value, dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a numeric array.") from exc
    if not np.isfinite(array).all():
        raise ValueError(f"{name} must contain finite numbers.")
    return array


def _normalise_rows(array: np.ndarray, name: str) -> np.ndarray:
    with np.errstate(over="ignore", invalid="ignore"):
        norms = np.linalg.norm(array, axis=-1, keepdims=True)
    if np.any(norms == 0) or not np.isfinite(norms).all():
        raise ValueError(f"{name} must contain non-zero, finite-length vectors.")
    return array / norms


def _finite_scalar(value, name: str, *, allow_zero: bool = False) -> float:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
        raise ValueError(f"{name} must be a real number.")
    number = float(value)
    if not np.isfinite(number) or number < 0 or (number == 0 and not allow_zero):
        condition = "non-negative" if allow_zero else "positive"
        raise ValueError(f"{name} must be {condition} and finite.")
    return number


def global_and_layout_features(colour_vectors: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Separate the current 1920-D colour representation into unit blocks.

    Coordinates 0:192 are the global HSV histogram; 192:1920 are the 3x3
    spatial histograms. Independently normalising removes the existing global
    versus spatial block weights. The weighting *between spatial cells* stays
    unchanged. A vector or a row matrix is accepted; its leading shape is kept.
    """
    vectors = _finite_array(colour_vectors, "Colour features")
    if vectors.ndim not in (1, 2) or vectors.shape[-1] != 1920:
        raise ValueError("Colour features must have shape (1920,) or (n, 1920).")
    if np.any(vectors < 0):
        raise ValueError("The histogram representation cannot contain negative coordinates.")
    global_features = _normalise_rows(vectors[..., :192], "Global histogram block")
    layout_features = _normalise_rows(vectors[..., 192:], "Spatial histogram block")
    return global_features.astype(np.float32), layout_features.astype(np.float32)


def cosine_scores(query, frames) -> np.ndarray:
    """Compare one query with a feature matrix without assuming input norms."""
    query = _finite_array(query, "Query features")
    frames = _finite_array(frames, "Frame features")
    if query.ndim == 2 and query.shape[0] == 1:
        query = query[0]
    if query.ndim != 1 or query.size == 0:
        raise ValueError("Query features must contain one non-empty vector.")
    if frames.ndim != 2 or frames.shape[1] != query.size:
        raise ValueError("Frame features must be a matrix matching the query dimension.")
    normal_query = _normalise_rows(query, "Query features")
    normal_frames = _normalise_rows(frames, "Frame features")
    return np.clip(normal_frames @ normal_query, -1.0, 1.0)


def _average_descending_ranks(scores: np.ndarray) -> np.ndarray:
    """Use average one-based ranks for exact ties, independent of input order."""
    order = np.argsort(-scores, kind="stable")
    ranks = np.empty(len(scores), dtype=np.float64)
    ordered = scores[order]
    boundaries = np.r_[0, np.flatnonzero(ordered[1:] != ordered[:-1]) + 1, len(scores)]
    for start, end in zip(boundaries[:-1], boundaries[1:]):
        ranks[order[start:end]] = ((start + 1) + end) / 2.0
    return ranks


def weighted_rank_fusion(
    score_vectors: Mapping[str, Sequence[float]],
    weights: Mapping[str, float] | None = None,
    k: float = 60.0,
) -> np.ndarray:
    """Weighted reciprocal-rank fusion, with positive weights normalised to 1.

    The default requires content/colour/layout scores and weights them .5/.25/
    .25. Explicit positive weights may name any non-empty, exactly matching set
    of signals. Exact ties receive average ranks rather than arbitrary ranks.
    Every input signal must describe the same candidate ordering and count.
    """
    if not isinstance(score_vectors, Mapping) or not score_vectors:
        raise ValueError("At least one named score vector is required.")
    k = _finite_scalar(k, "The rank-fusion constant")
    active_weights = DEFAULT_WEIGHTS if weights is None else weights
    if not isinstance(active_weights, Mapping) or set(active_weights) != set(score_vectors):
        raise ValueError("Weights must name exactly the same signals as the score vectors.")
    names = list(score_vectors)
    if any(not isinstance(name, str) or not name for name in names):
        raise ValueError("Signals must have non-empty string names.")
    numeric_weights = []
    arrays = []
    count = None
    for name in names:
        value = _finite_scalar(active_weights[name], f"The {name} fusion weight")
        scores = _finite_array(score_vectors[name], f"{name} scores")
        if scores.ndim != 1:
            raise ValueError("Each score vector must be one-dimensional.")
        if count is None:
            count = len(scores)
        if len(scores) != count:
            raise ValueError("All signals must contain the same number of candidates.")
        arrays.append(scores)
        numeric_weights.append(float(value))
    total_weight = sum(numeric_weights)
    if not np.isfinite(total_weight):
        raise ValueError("The total fusion weight must be finite.")
    fused = np.zeros(count, dtype=np.float64)
    for weight, scores in zip(numeric_weights, arrays):
        fused += (weight / total_weight) / (float(k) + _average_descending_ranks(scores))
    return fused


def select_scored_frames(
    scores,
    timestamps,
    top_k: int,
    min_gap: float,
    eligible: Sequence[bool] | None = None,
) -> list[dict]:
    """Rank arbitrary finite scores and apply eligibility and time separation.

    Scores retain their native scale. Exact ties use earlier timestamps and then
    input index. Eligibility is applied before ranking. All-false masks return
    no candidates; this function never silently restores rejected frames.
    """
    if isinstance(top_k, (bool, np.bool_)) or not isinstance(top_k, Integral) or top_k < 1:
        raise ValueError("top_k must be a positive integer.")
    min_gap = _finite_scalar(min_gap, "min_gap", allow_zero=True)
    values = _finite_array(scores, "Scores")
    times = _finite_array(timestamps, "Timestamps")
    if values.ndim != 1 or times.ndim != 1 or values.shape != times.shape:
        raise ValueError("Scores and timestamps must be matching one-dimensional arrays.")
    if np.any(times < 0):
        raise ValueError("Timestamps must be non-negative.")
    if eligible is None:
        mask = np.ones(len(values), dtype=bool)
    else:
        mask = np.asarray(eligible)
        if mask.ndim != 1 or mask.shape != values.shape or mask.dtype.kind != "b":
            raise ValueError("Eligibility must be a boolean vector matching the candidates.")
    indices = np.flatnonzero(mask)
    order = indices[np.lexsort((indices, times[indices], -values[indices]))]
    selected = []
    for index in order:
        timestamp = float(times[index])
        if any(abs(timestamp - item["timestamp"]) + 1e-9 < min_gap for item in selected):
            continue
        selected.append({"index": int(index), "timestamp": timestamp, "score": float(values[index])})
        if len(selected) == top_k:
            break
    return selected


class ResizeAndPad:
    """Fit a complete RGB image into the target without geometric distortion.

    Rounding can change the fitted ratio by at most one output pixel. Padding
    uses the model's mean RGB rounded to integer pixels, so its normalised values
    are near zero. This is a proposed input policy, not a validated improvement.
    """
    def __init__(self, size, interpolation, fill, antialias=True):
        self.size = tuple(int(value) for value in size)
        if len(self.size) != 2 or any(value < 1 for value in self.size):
            raise ValueError("The target image size must contain two positive dimensions.")
        self.interpolation = interpolation
        self.fill = tuple(int(value) for value in fill)
        if len(self.fill) != 3 or any(value < 0 or value > 255 for value in self.fill):
            raise ValueError("Padding must be a valid RGB colour.")
        self.antialias = antialias

    def __call__(self, image):
        from torchvision.transforms import functional as functional
        if not isinstance(image, Image.Image) or image.width < 1 or image.height < 1:
            raise ValueError("Full-frame preprocessing requires a non-empty PIL image.")
        image = image.convert("RGB")
        height, width = self.size
        scale = min(width / image.width, height / image.height)
        fitted_width = min(width, max(1, round(image.width * scale)))
        fitted_height = min(height, max(1, round(image.height * scale)))
        resized = functional.resize(image, [fitted_height, fitted_width], interpolation=self.interpolation,
                                    antialias=self.antialias)
        result = Image.new("RGB", (width, height), self.fill)
        result.paste(resized, ((width - fitted_width) // 2, (height - fitted_height) // 2))
        return result

    def __repr__(self):
        return (f"{self.__class__.__name__}(size={self.size}, interpolation={self.interpolation}, "
                f"fill_rgb={self.fill}, antialias={self.antialias})")


def full_frame_preprocess(existing_preprocess):
    """Replace a known CLIP Resize/CenterCrop pair, keeping every other step.

    Reject unfamiliar spatial pipelines rather than silently changing their
    meaning. The original Compose and its transforms are not mutated. RGB
    conversion, ToTensor and the existing Normalize remain in the same order.
    """
    from torchvision.transforms import CenterCrop, Compose, Normalize, Resize
    transforms = getattr(existing_preprocess, "transforms", None)
    if not isinstance(transforms, (list, tuple)):
        raise ValueError("Expected a Compose-style preprocessing pipeline.")
    resize_indices = [i for i, value in enumerate(transforms) if isinstance(value, Resize)]
    crop_indices = [i for i, value in enumerate(transforms) if isinstance(value, CenterCrop)]
    normalizers = [value for value in transforms if isinstance(value, Normalize)]
    if len(resize_indices) != 1 or len(crop_indices) != 1 or len(normalizers) != 1:
        raise ValueError("Expected one Resize, one CenterCrop and one Normalize step.")
    resize_index, crop_index = resize_indices[0], crop_indices[0]
    if crop_index != resize_index + 1:
        raise ValueError("Resize and CenterCrop must be consecutive.")
    resize, crop, normalize = transforms[resize_index], transforms[crop_index], normalizers[0]
    mean = _finite_array(normalize.mean, "Normalisation mean")
    std = _finite_array(normalize.std, "Normalisation standard deviation")
    if mean.shape != (3,) or np.any(mean < 0) or np.any(mean > 1):
        raise ValueError("Expected three RGB normalisation means between zero and one.")
    if std.shape != (3,) or np.any(std <= 0):
        raise ValueError("Expected three positive RGB normalisation standard deviations.")
    fill = tuple(int(round(value * 255)) for value in mean)
    size = crop.size if isinstance(crop.size, (tuple, list)) else (crop.size, crop.size)
    replacement = ResizeAndPad(size, resize.interpolation, fill, getattr(resize, "antialias", True))
    return Compose([*transforms[:resize_index], replacement, *transforms[crop_index + 1:]])
