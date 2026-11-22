"""Conservative temporal-window quality diagnostics for a controlled experiment.

Brightness and sharpness are reported, not used as stand-alone exclusion rules.
The heuristic can miss transitions and can flag intentional edits or fast light
changes. Its output is not a human quality/relevance label or an accuracy score.
All thresholds are fixed in version temporal-window-v1, before the second pilot.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from pathlib import Path
from typing import Sequence

import cv2
import numpy as np


QUALITY_VERSION = "temporal-window-v1"
DIAGNOSTIC_SIZE = (160, 160)


@dataclass(frozen=True)
class QualityThresholds:
    # All luminance/difference values use [0, 1], except Laplacian variance.
    near_white: int = 245
    near_black: int = 10
    flash_mean_excursion: float = 0.18
    flash_fraction: float = 0.35
    flash_fraction_excursion: float = 0.25
    flash_side_difference: float = 0.16
    cut_stable_side: float = 0.04
    cut_changed_side: float = 0.24
    cut_endpoint_difference: float = 0.24
    cut_asymmetry: float = 0.20
    blend_endpoint_difference: float = 0.24
    blend_each_side_difference: float = 0.07
    blend_residual: float = 0.025
    blend_alpha_min: float = 0.20
    blend_alpha_max: float = 0.80
    blend_detail_ratio: float = 0.85


DEFAULT_THRESHOLDS = QualityThresholds()


def _gray(image: np.ndarray) -> np.ndarray:
    if not isinstance(image, np.ndarray) or image.ndim != 3 or image.shape[2] != 3:
        raise ValueError("Temporal quality inputs must be H×W×3 RGB arrays.")
    if image.dtype != np.uint8 or min(image.shape[:2]) < 2:
        raise ValueError("Temporal quality inputs must be uint8 RGB arrays with dimensions >= 2.")
    # Resize all probes in the same way; this is only for temporal diagnostics.
    rgb = cv2.resize(image, DIAGNOSTIC_SIZE, interpolation=cv2.INTER_AREA)
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)


def _statistics(gray: np.ndarray, thresholds: QualityThresholds) -> dict:
    return {
        "mean_luma": float(gray.mean() / 255.0),
        "white_fraction": float(np.mean(gray >= thresholds.near_white)),
        "black_fraction": float(np.mean(gray <= thresholds.near_black)),
        "laplacian_variance": float(cv2.Laplacian(gray, cv2.CV_64F).var()),
        "luma_std": float(gray.std() / 255.0),
    }


def assess_temporal_window(
    previous_rgb: np.ndarray | None,
    current_rgb: np.ndarray,
    next_rgb: np.ndarray | None,
    *,
    thresholds: QualityThresholds = DEFAULT_THRESHOLDS,
) -> dict:
    """Assess a fixed three-probe temporal window without changing its images.

    A missing neighbour is allowed at a clip boundary. Such a frame is kept,
    with insufficient-context diagnostics; stable bright/dark images are kept.
    """
    current = _gray(current_rgb)
    stats = _statistics(current, thresholds)
    result = {
        **stats,
        "prev_diff": None,
        "next_diff": None,
        "eligible": True,
        "reasons": [],
        "reason": "stable_or_no_transition_evidence",
        "version": QUALITY_VERSION,
        "diagnostics": {"size": list(DIAGNOSTIC_SIZE), "thresholds": asdict(thresholds)},
    }
    previous = None if previous_rgb is None else _gray(previous_rgb)
    following = None if next_rgb is None else _gray(next_rgb)
    if previous is not None:
        result["prev_diff"] = float(np.abs(previous.astype(np.float32) - current).mean() / 255)
    if following is not None:
        result["next_diff"] = float(np.abs(following.astype(np.float32) - current).mean() / 255)
    if previous is None or following is None:
        result["reason"] = "boundary_or_insufficient_context_kept"
        result["diagnostics"]["context_complete"] = False
        return result

    before = _statistics(previous, thresholds)
    after = _statistics(following, thresholds)
    prev_diff, next_diff = result["prev_diff"], result["next_diff"]
    endpoint_diff = float(np.abs(previous.astype(np.float32) - following).mean() / 255)
    result["diagnostics"].update(context_complete=True, previous=before, following=after, endpoint_diff=endpoint_diff)

    changed_both_sides = min(prev_diff, next_diff) >= thresholds.flash_side_difference
    bright_excursion = (
        stats["mean_luma"] - max(before["mean_luma"], after["mean_luma"]) >= thresholds.flash_mean_excursion
        and stats["white_fraction"] >= thresholds.flash_fraction
        and stats["white_fraction"] - max(before["white_fraction"], after["white_fraction"]) >= thresholds.flash_fraction_excursion
    )
    dark_excursion = (
        min(before["mean_luma"], after["mean_luma"]) - stats["mean_luma"] >= thresholds.flash_mean_excursion
        and stats["black_fraction"] >= thresholds.flash_fraction
        and stats["black_fraction"] - max(before["black_fraction"], after["black_fraction"]) >= thresholds.flash_fraction_excursion
    )
    if changed_both_sides and bright_excursion:
        result["reasons"].append("temporal_bright_flash")
    if changed_both_sides and dark_excursion:
        result["reasons"].append("temporal_dark_flash")

    # Require one locally stable side and a large, asymmetric change on the
    # other side. Large motion on both sides is not alone grounds for removal.
    if (min(prev_diff, next_diff) <= thresholds.cut_stable_side
            and max(prev_diff, next_diff) >= thresholds.cut_changed_side
            and endpoint_diff >= thresholds.cut_endpoint_difference
            and abs(prev_diff - next_diff) >= thresholds.cut_asymmetry):
        result["reasons"].append("near_strong_cut")

    # Conservative blend evidence: two distinct endpoints, an intermediate
    # mixture and reduced fine detail. This does not label every smooth fade.
    p, c, n = [gray.astype(np.float64) / 255 for gray in (previous, current, following)]
    direction = p - n
    denominator = float(np.square(direction).sum())
    alpha = float(np.sum((c - n) * direction) / denominator) if denominator > 1e-12 else 0.5
    alpha_clipped = float(np.clip(alpha, 0, 1))
    blend_residual = float(np.mean(np.abs(c - (alpha_clipped * p + (1 - alpha_clipped) * n))))
    endpoint_detail = min(before["laplacian_variance"], after["laplacian_variance"])
    detail_ratio = stats["laplacian_variance"] / endpoint_detail if endpoint_detail > 1e-6 else None
    result["diagnostics"].update(blend_alpha=alpha, blend_residual=blend_residual, blend_detail_ratio=detail_ratio)
    if (endpoint_diff >= thresholds.blend_endpoint_difference
            and min(prev_diff, next_diff) >= thresholds.blend_each_side_difference
            and thresholds.blend_alpha_min <= alpha <= thresholds.blend_alpha_max
            and blend_residual <= thresholds.blend_residual
            and detail_ratio is not None and detail_ratio <= thresholds.blend_detail_ratio):
        result["reasons"].append("temporal_blend_with_detail_loss")

    result["eligible"] = not result["reasons"]
    if result["reasons"]:
        result["reason"] = ";".join(result["reasons"])
    return result


def analyze_video_quality(
    video_path: Path,
    timestamps: Sequence[float],
    probe_offset: float = 0.15,
) -> list[dict]:
    """Read t-offset, t, t+offset probes for each supplied timestamp in order.

    The source/sample collection is left unchanged. Actual decoder PTS is
    reported for each successful probe. A failed centre or an unexpected
    interior neighbour failure is explicitly ineligible, never silently filled.
    """
    if isinstance(probe_offset, bool) or not math.isfinite(probe_offset) or probe_offset <= 0:
        raise ValueError("probe_offset must be a finite positive number.")
    if video_path is None:
        raise ValueError("A source video path is required.")
    if any(isinstance(timestamp, (bool, np.bool_)) for timestamp in timestamps):
        raise ValueError("Timestamps must be numeric seconds, not booleans.")
    times = [float(timestamp) for timestamp in timestamps]
    if any(not math.isfinite(timestamp) or timestamp < 0 for timestamp in times):
        raise ValueError("Timestamps must be finite, non-negative seconds.")
    capture = cv2.VideoCapture(str(Path(video_path)))
    if not capture.isOpened():
        capture.release()
        raise ValueError("The source video cannot be opened for quality probes.")
    fps = float(capture.get(cv2.CAP_PROP_FPS))
    count = float(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    if not math.isfinite(fps) or fps <= 0 or not math.isfinite(count) or count <= 0:
        capture.release()
        raise ValueError("The source video has no reliable nominal timing for boundary probes.")
    nominal_end = max(0.0, (count - 1) / fps)
    results = []

    def read_at(timestamp):
        # Seeking to t can land one frame after t. Decode a small neighbourhood
        # from just before it, then report/select the nearest actual PTS.
        capture.set(cv2.CAP_PROP_POS_MSEC, max(0.0, timestamp - 2 / fps) * 1000)
        candidates = []
        unknown_time_image = None
        for _ in range(8):
            ok, bgr = capture.read()
            if not ok:
                break
            actual = float(capture.get(cv2.CAP_PROP_POS_MSEC)) / 1000
            rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
            if not math.isfinite(actual) or actual < 0:
                unknown_time_image = rgb
                break
            candidates.append((abs(actual - timestamp), actual, rgb))
            if actual >= timestamp + 1 / fps:
                break
        if not candidates:
            return unknown_time_image, None
        _, actual, rgb = min(candidates, key=lambda item: (item[0], item[1]))
        if abs(actual - timestamp) > max(0.1, 3 / fps):
            return None, None
        return rgb, actual

    try:
        for timestamp in times:
            requested = {"previous": timestamp - probe_offset, "current": timestamp, "next": timestamp + probe_offset}
            images, actuals, skipped = {}, {}, []
            for name, requested_time in requested.items():
                if name != "current" and (requested_time < 0 or requested_time > nominal_end):
                    images[name], actuals[name] = None, None
                    skipped.append(name)
                else:
                    images[name], actuals[name] = read_at(requested_time)
            failed = [name for name in requested if images[name] is None and name not in skipped]
            if images["current"] is None:
                result = {"eligible": False, "reasons": ["current_probe_decode_failed"], "reason": "current_probe_decode_failed",
                          "mean_luma": None, "white_fraction": None, "black_fraction": None,
                          "laplacian_variance": None, "prev_diff": None, "next_diff": None,
                          "version": QUALITY_VERSION, "diagnostics": {"failed_probes": failed}}
            else:
                result = assess_temporal_window(images["previous"], images["current"], images["next"])
                if failed:
                    result.update(eligible=False, reasons=["interior_context_decode_failed"], reason="interior_context_decode_failed")
                    result["diagnostics"]["failed_probes"] = failed
                valid_actuals = [value for value in actuals.values() if value is not None]
                if not failed and len(valid_actuals) >= 2 and len(set(valid_actuals)) < len(valid_actuals):
                    result.update(eligible=True, reasons=[], reason="insufficient_unique_probe_times_kept")
                if not failed and any(actuals[name] is None for name in images if images[name] is not None):
                    result.update(eligible=True, reasons=[], reason="probe_timestamps_unavailable_kept")
                result["diagnostics"]["boundary_probes_skipped"] = skipped
            result.update(timestamp=timestamp, actual_probe_times=actuals, requested_probe_times=requested,
                          probe_offset=probe_offset, nominal_boundary_source="frame_count_and_fps_estimate")
            result["diagnostics"]["probe_alignment_errors"] = {
                name: None if actual is None else actual - requested[name]
                for name, actual in actuals.items()
            }
            results.append(result)
    finally:
        capture.release()
    return results
