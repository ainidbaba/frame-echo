"""Check real decoding and timing failure boundaries without external footage."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import cv2
import numpy as np
from PIL import Image

from app.video import extract_frames, probe_video, timestamp_label


def write_video(path: Path, frames: int, fps: float = 4) -> None:
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), fps, (64, 48))
    if not writer.isOpened():
        raise RuntimeError("The local OpenCV build cannot write the MJPG test fixture.")
    try:
        for index in range(frames):
            pixels = np.zeros((48, 64, 3), dtype=np.uint8)
            pixels[..., 2] = 30 + index * 10
            writer.write(pixels)
    finally:
        writer.release()


class FakeCapture:
    """A declared 4 FPS clip with controllable decoder presentation times."""

    def __init__(self, pts_ms: list[float], declared_count: int | None = None):
        self.pts_ms = pts_ms
        self.declared_count = declared_count if declared_count is not None else len(pts_ms)
        self.index = 0
        self.released = False

    def isOpened(self):
        return not self.released

    def get(self, prop):
        values = {
            cv2.CAP_PROP_FPS: 4.0,
            cv2.CAP_PROP_FRAME_COUNT: self.declared_count,
            cv2.CAP_PROP_FRAME_WIDTH: 24,
            cv2.CAP_PROP_FRAME_HEIGHT: 24,
            cv2.CAP_PROP_POS_FRAMES: self.index,
        }
        if prop == cv2.CAP_PROP_POS_MSEC:
            return self.pts_ms[max(0, self.index - 1)]
        return values.get(prop, 0)

    def read(self):
        if self.index >= len(self.pts_ms):
            return False, None
        pixels = np.full((24, 24, 3), self.index * 30, dtype=np.uint8)
        self.index += 1
        return True, pixels

    def release(self):
        self.released = True


class VideoSamplingTests(unittest.TestCase):
    def test_sampling_uses_actual_decoded_frame_times(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            video = root / "clip.avi"
            write_video(video, 12)
            progress = []
            info, frames = extract_frames(video, root / "frames", .6, lambda value, count: progress.append((value, count)))
            np.testing.assert_allclose([frame["timestamp"] for frame in frames], [0, .75, 1.25, 2, 2.5], atol=1e-6)
            self.assertEqual(info["decoded_frames"], 12)
            self.assertAlmostEqual(info["duration"], 3)
            self.assertIn("estimate", info["duration_source"])
            self.assertEqual(len(progress), len(frames))
            self.assertEqual(progress[-1][1], 5)
            for frame in frames:
                with Image.open(frame["path"]) as image:
                    self.assertEqual(image.size, (64, 48))

    def test_single_frame_clip_and_no_duplicated_frames_when_interval_is_small(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            video = root / "one.avi"
            write_video(video, 1)
            info, frames = extract_frames(video, root / "frames", 1)
            self.assertEqual(info["decoded_frames"], 1)
            self.assertEqual([frame["timestamp"] for frame in frames], [0])
            longer = root / "four.avi"
            write_video(longer, 4)
            _, frames = extract_frames(longer, root / "more", .1)
            self.assertEqual(len(frames), 4)
            np.testing.assert_allclose([frame["timestamp"] for frame in frames], [0, .25, .5, .75])

    def test_bad_file_and_invalid_intervals_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            invalid = root / "invalid.mp4"
            invalid.write_bytes(b"This is not a video.")
            with self.assertRaises(ValueError):
                probe_video(invalid)
            for interval in (0, -1, float("nan"), float("inf")):
                with self.subTest(interval=interval), self.assertRaises(ValueError):
                    extract_frames(invalid, root / "frames", interval)

    def test_estimated_oversampling_is_rejected_before_writing_frames(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            video = root / "eight.avi"
            write_video(video, 8)
            with patch("app.video.MAX_SAMPLED_FRAMES", 3), self.assertRaisesRegex(ValueError, "over 3 frames"):
                extract_frames(video, root / "frames", .25)
            self.assertFalse((root / "frames").exists())

    def test_invalid_presentation_times_restart_on_one_consistent_fps_axis(self):
        # The initial PTS clock runs ahead of declared FPS, then resets. An
        # in-place fallback would lose frames or mix clocks. The retry must
        # sample all four frames from the beginning using FPS-derived times.
        captures = []

        def capture_factory(_path):
            capture = FakeCapture([0, 2000, 2100, 0])
            captures.append(capture)
            return capture

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with patch("app.video.cv2.VideoCapture", side_effect=capture_factory):
                info, frames = extract_frames(root / "clock-reset.mp4", root / "frames", .25)
            np.testing.assert_allclose([frame["timestamp"] for frame in frames], [0, .25, .5, .75])
            self.assertEqual(info["timestamp_source"], "frame_index_and_fps_fallback")
            self.assertTrue(info["sampling_restarted"])
            self.assertAlmostEqual(info["decoded_last_timestamp"], .75)
            self.assertEqual(len(captures), 3)  # probe + first pass + one retry
            self.assertTrue(all(capture.released for capture in captures))
            self.assertEqual(len(list((root / "frames").glob("*.jpg"))), 4)

    def test_live_sampling_cap_applies_when_declared_duration_underestimates_pts(self):
        captures = []

        def capture_factory(_path):
            capture = FakeCapture([0, 1000, 2000, 3000])
            captures.append(capture)
            return capture

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with patch("app.video.cv2.VideoCapture", side_effect=capture_factory), patch("app.video.MAX_SAMPLED_FRAMES", 3):
                with self.assertRaisesRegex(ValueError, "sampling limit"):
                    extract_frames(root / "vfr.mp4", root / "frames", 1)
            self.assertEqual(len(list((root / "frames").glob("*.jpg"))), 3)
            self.assertTrue(all(capture.released for capture in captures))

    def test_truncated_decode_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with patch("app.video.cv2.VideoCapture", side_effect=lambda _: FakeCapture([0, 250], declared_count=10)):
                with self.assertRaisesRegex(ValueError, "stopped decoding"):
                    extract_frames(root / "truncated.mp4", root / "frames", 1)

    def test_timestamp_labels_round_at_minute_and_hour_boundaries(self):
        self.assertEqual(timestamp_label(0), "00:00.000")
        self.assertEqual(timestamp_label(59.9996), "01:00.000")
        self.assertEqual(timestamp_label(3600), "01:00:00.000")


if __name__ == "__main__":
    unittest.main()
