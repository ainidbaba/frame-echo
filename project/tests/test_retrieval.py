"""Small, deterministic checks of retrieval behaviour; no model download."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image, ImageDraw

from app.retrieval import ColourEncoder, ClipEncoder, available_clip, get_encoder, rank_matches


def split_image(top: str, bottom: str) -> Image.Image:
    image = Image.new("RGB", (120, 120), bottom)
    ImageDraw.Draw(image).rectangle((0, 0, 119, 59), fill=top)
    return image


class ColourRetrievalTests(unittest.TestCase):
    def test_colour_and_relative_layout_affect_ranking(self):
        encoder = ColourEncoder()
        query = split_image("#e6c8a0", "#186c8a")
        images = [
            Image.new("RGB", (120, 120), "#8a1830"),
            split_image("#186c8a", "#e6c8a0"),
            query.copy(),
        ]
        vectors = encoder.encode(images)
        matches = rank_matches(encoder.encode([query]), vectors, [0, 5, 10], 3, 0)
        self.assertEqual([match["index"] for match in matches], [2, 1, 0])
        self.assertAlmostEqual(matches[0]["score"], 1, places=6)
        self.assertGreater(matches[0]["score"], matches[1]["score"])
        np.testing.assert_allclose(np.linalg.norm(vectors, axis=1), 1, atol=1e-6)

    def test_resize_and_transparency_are_supported(self):
        encoder = ColourEncoder()
        transparent = Image.new("RGBA", (10, 20), (20, 10, 100, 0))
        white = Image.new("RGB", (200, 300), "white")
        np.testing.assert_allclose(encoder.encode([transparent]), encoder.encode([white]), atol=1e-6)
        self.assertEqual(encoder.encode([]).shape, (0, encoder.dimension))

    def test_invalid_image_is_rejected(self):
        with self.assertRaises(TypeError):
            ColourEncoder().encode([np.zeros((10, 10, 3))])


class RankingTests(unittest.TestCase):
    def test_temporal_suppression_and_exact_boundary(self):
        frames = np.array([[1, 0], [.99, .01], [.9, .1], [.8, .2]])
        matches = rank_matches([1, 0], frames, [0, 1, 3, 6], 4, 3)
        self.assertEqual([match["timestamp"] for match in matches], [0, 3, 6])

    def test_ties_use_earlier_timestamp_then_input_index(self):
        frames = np.array([[1, 0]] * 4)
        matches = rank_matches([1, 0], frames, [9, 1, 5, 1], 4, 0)
        self.assertEqual([match["index"] for match in matches], [1, 3, 2, 0])

    def test_empty_candidates_and_unnormalised_vectors(self):
        self.assertEqual(rank_matches([1, 0], np.empty((0, 2)), [], 5, 2), [])
        matches = rank_matches([3, 0], np.array([[6, 0], [-3, 0]]), [0, 10], 2, 0)
        self.assertEqual([match["score"] for match in matches], [1, -1])

    def test_minimum_score_none_preserves_existing_ranking(self):
        query = np.array([1.0, 0.0])
        frames = np.array([[0.6, 0.8], [0, 1], [-1, 0], [1, 0]])
        expected = rank_matches(query, frames, [0, 5, 10, 15], 4, 0)
        actual = rank_matches(query, frames, [0, 5, 10, 15], 4, 0, min_score=None)
        self.assertEqual(actual, expected)
        self.assertEqual([match["index"] for match in actual], [3, 0, 1, 2])

    def test_minimum_score_filters_partial_and_all_candidates(self):
        query = np.array([1.0, 0.0])
        frames = np.array([[0.6, 0.8], [0, 1], [-1, 0]])
        partial = rank_matches(query, frames, [0, 5, 10], 3, 0, min_score=0.5)
        self.assertEqual([match["index"] for match in partial], [0])
        self.assertTrue(all(match["score"] >= 0.5 for match in partial))
        self.assertEqual(rank_matches(query, frames, [0, 5, 10], 3, 0, min_score=0.7), [])
        self.assertEqual(rank_matches(query, np.empty((0, 2)), [], 3, 0, min_score=0.7), [])

    def test_minimum_score_is_inclusive_and_accepts_cosine_endpoints(self):
        frames = np.array([[1, 0], [0, 1], [-1, 0]])
        self.assertEqual(
            [match["index"] for match in rank_matches([1, 0], frames, [0, 5, 10], 3, 0, min_score=1.0)],
            [0],
        )
        self.assertEqual(
            [match["index"] for match in rank_matches([1, 0], frames, [0, 5, 10], 3, 0, min_score=0.0)],
            [0, 1],
        )
        self.assertEqual(
            [match["index"] for match in rank_matches([1, 0], frames, [0, 5, 10], 3, 0, min_score=-1.0)],
            [0, 1, 2],
        )

    def test_score_filter_and_temporal_selection_work_together(self):
        frames = np.array([[1, 0], [.99, .01], [.8, .6], [.6, .8]])
        matches = rank_matches([1, 0], frames, [0, 1, 3, 6], 4, 3, min_score=0.75)
        self.assertEqual([match["timestamp"] for match in matches], [0, 3])
        self.assertTrue(all(match["score"] >= 0.75 for match in matches))

    def test_invalid_minimum_scores_are_rejected(self):
        invalid = [True, False, np.bool_(True), np.nan, np.inf, -np.inf,
                   "0.5", "not a score", -1.01, 1.01, [0.5], complex(0.5, 0)]
        for threshold in invalid:
            with self.subTest(min_score=threshold), self.assertRaises(ValueError):
                rank_matches([1, 0], [[1, 0]], [0], 1, 0, min_score=threshold)

    def test_invalid_inputs(self):
        cases = [
            ([0, 0], [[1, 0]], [0], 1, 0),
            ([1, 0], [[0, 0]], [0], 1, 0),
            ([1, 0], [[1, float("nan")]], [0], 1, 0),
            ([1, 0], [[1, 0]], [-1], 1, 0),
            ([1, 0], [[1, 0]], [float("inf")], 1, 0),
            ([1, 0], [[1, 0]], [], 1, 0),
            ([1, 0], [[1]], [0], 1, 0),
            ([[1, 0], [1, 0]], [[1, 0]], [0], 1, 0),
            ([1, 0], [[1, 0]], [0], 0, 0),
            ([1, 0], [[1, 0]], [0], True, 0),
            ([1, 0], [[1, 0]], [0], 1, -1),
            ([1, 0], [[1, 0]], [0], 1, float("nan")),
        ]
        for args in cases:
            with self.subTest(args=args), self.assertRaises(ValueError):
                rank_matches(*args)


class OptionalClipTests(unittest.TestCase):
    def test_missing_dependencies_do_not_trigger_fallback(self):
        with patch("app.retrieval.importlib.util.find_spec", return_value=None):
            capability = available_clip(Path("missing.safetensors"))
            self.assertFalse(capability["available"])
            with self.assertRaises(RuntimeError):
                get_encoder("clip", Path("missing.safetensors"))
        with self.assertRaises(ValueError):
            get_encoder("unknown", Path("missing.safetensors"))

    def test_missing_weights_do_not_load_or_download_a_model(self):
        with patch("app.retrieval.importlib.util.find_spec", return_value=object()):
            with tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / "weights.safetensors"
                self.assertEqual(available_clip(path)["missing"], ["weights"])
                with self.assertRaises(RuntimeError):
                    ClipEncoder(path)
                path.write_bytes(b"")
                self.assertFalse(available_clip(path)["available"])


if __name__ == "__main__":
    unittest.main()
