"""Meaningful checks for temporal filtering; no model or network dependency."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import sys

import cv2
import numpy as np

try:
    from app.frame_quality import assess_temporal_window, analyze_video_quality, QUALITY_VERSION
except ModuleNotFoundError:
    from frame_quality import assess_temporal_window, analyze_video_quality, QUALITY_VERSION


def solid(value):
    return np.full((80, 120, 3), value, dtype=np.uint8)


class TemporalWindowTests(unittest.TestCase):
    def test_stable_white_and_black_and_low_contrast_are_kept(self):
        for value in (0, 5, 120, 249, 255):
            result = assess_temporal_window(solid(value), solid(value), solid(value))
            self.assertTrue(result["eligible"], result)
            self.assertEqual(result["reasons"], [])
            self.assertEqual(result["version"], QUALITY_VERSION)

    def test_bright_and_dark_temporal_flash_are_flagged(self):
        bright = assess_temporal_window(solid(70), solid(255), solid(80))
        self.assertFalse(bright["eligible"])
        self.assertIn("temporal_bright_flash", bright["reasons"])
        dark = assess_temporal_window(solid(180), solid(0), solid(190))
        self.assertFalse(dark["eligible"])
        self.assertIn("temporal_dark_flash", dark["reasons"])

    def test_cut_requires_stable_side_and_strong_change(self):
        cut = assess_temporal_window(solid(40), solid(42), solid(200))
        self.assertFalse(cut["eligible"])
        self.assertIn("near_strong_cut", cut["reasons"])
        gradual = assess_temporal_window(solid(70), solid(110), solid(150))
        self.assertTrue(gradual["eligible"])

    def test_boundary_frame_is_kept_without_complete_context(self):
        result = assess_temporal_window(None, solid(250), solid(50))
        self.assertTrue(result["eligible"])
        self.assertEqual(result["reason"], "boundary_or_insufficient_context_kept")
        self.assertIsNone(result["prev_diff"])

    def test_blended_detailed_endpoints_have_mixture_evidence(self):
        a = np.zeros((160, 160, 3), np.uint8)
        a[::2] = 255
        b = 255 - a
        middle = ((a.astype(np.float32) + b) / 2).astype(np.uint8)
        result = assess_temporal_window(a, middle, b)
        self.assertFalse(result["eligible"])
        self.assertIn("temporal_blend_with_detail_loss", result["reasons"])

    def test_invalid_image_inputs_are_rejected(self):
        for image in (None, np.zeros((10, 10)), np.zeros((10, 10, 3)), np.zeros((0, 3, 3), np.uint8)):
            with self.subTest(image=type(image)), self.assertRaises(ValueError):
                assess_temporal_window(solid(70), image, solid(70))


class VideoProbeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary.name) / "stable.avi"
        writer = cv2.VideoWriter(str(self.path), cv2.VideoWriter_fourcc(*"MJPG"), 10, (120, 80))
        if not writer.isOpened():
            self.skipTest("Local OpenCV has no MJPG writer.")
        for _ in range(20):
            writer.write(solid(240))
        writer.release()

    def tearDown(self):
        self.temporary.cleanup()

    def test_order_and_boundary_and_actual_times(self):
        results = analyze_video_quality(self.path, [1.0, 0.0, 1.9])
        self.assertEqual([result["timestamp"] for result in results], [1.0, 0.0, 1.9])
        self.assertTrue(all(result["eligible"] for result in results))
        self.assertEqual(results[1]["diagnostics"]["boundary_probes_skipped"], ["previous"])
        self.assertEqual(results[2]["diagnostics"]["boundary_probes_skipped"], ["next"])
        self.assertAlmostEqual(results[0]["actual_probe_times"]["current"], 1.0, places=3)

    def test_out_of_bounds_current_decode_failure_is_explicit(self):
        result = analyze_video_quality(self.path, [100])[0]
        self.assertFalse(result["eligible"])
        self.assertEqual(result["reason"], "current_probe_decode_failed")

    def test_forward_seek_rounding_does_not_replace_the_candidate_frame(self):
        class ForwardRoundedCapture:
            def __init__(self):
                self.index = 0
                self.actual = 0.0

            def isOpened(self):
                return True

            def get(self, prop):
                return {cv2.CAP_PROP_FPS: 10.0, cv2.CAP_PROP_FRAME_COUNT: 20.0,
                        cv2.CAP_PROP_POS_MSEC: self.actual * 1000}.get(prop, 0)

            def set(self, prop, value):
                self.index = round(value / 1000 * 10) + 1
                return True

            def read(self):
                if self.index >= 20:
                    return False, None
                self.actual = self.index / 10
                self.index += 1
                return True, solid(120)

            def release(self):
                pass

        module = sys.modules[analyze_video_quality.__module__]
        with patch.object(module.cv2, "VideoCapture", return_value=ForwardRoundedCapture()):
            result = analyze_video_quality(Path("mock.mp4"), [1.0])[0]
        self.assertEqual(result["actual_probe_times"]["current"], 1.0)
        self.assertEqual(result["diagnostics"]["probe_alignment_errors"]["current"], 0.0)

    def test_bad_video_timing_and_offsets_are_rejected(self):
        for timestamps, offset in (([-1], .15), ([float("nan")], .15), ([True], .15), ([1], 0), ([1], float("inf"))):
            with self.assertRaises(ValueError):
                analyze_video_quality(self.path, timestamps, offset)
        with self.assertRaises(ValueError):
            analyze_video_quality(self.path.parent / "missing.mp4", [1])
        with self.assertRaises(ValueError):
            analyze_video_quality(None, [1])


if __name__ == "__main__":
    unittest.main()
