"""Deterministic checks of experimental ranking and complete-frame input."""
from pathlib import Path
import importlib.util
import sys
import unittest

import numpy as np
from PIL import Image, ImageDraw

try:
    from app.visual_similarity import (cosine_scores, full_frame_preprocess, global_and_layout_features,
                                       select_scored_frames, weighted_rank_fusion)
except ModuleNotFoundError as error:
    if error.name not in {"app", "app.visual_similarity"}:
        raise
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from visual_similarity import (cosine_scores, full_frame_preprocess, global_and_layout_features,
                                   select_scored_frames, weighted_rank_fusion)


class SignalTests(unittest.TestCase):
    def test_global_colour_is_invariant_to_reversed_layout(self):
        from app.retrieval import ColourEncoder
        image = Image.new("RGB", (120, 120), "blue")
        ImageDraw.Draw(image).rectangle((0, 0, 119, 59), fill="red")
        reversed_image = image.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
        global_features, layout = global_and_layout_features(ColourEncoder().encode([image, reversed_image]))
        self.assertEqual(global_features.shape, (2, 192))
        self.assertEqual(layout.shape, (2, 1728))
        np.testing.assert_allclose(global_features[0], global_features[1], atol=1e-6)
        self.assertLess(float(layout[0] @ layout[1]), 0.6)
        np.testing.assert_allclose(np.linalg.norm(global_features, axis=1), 1, atol=1e-6)
        np.testing.assert_allclose(np.linalg.norm(layout, axis=1), 1, atol=1e-6)

    def test_histogram_block_validation_and_empty_rows(self):
        vector = np.ones(1920)
        self.assertEqual(global_and_layout_features(vector)[0].shape, (192,))
        self.assertEqual(global_and_layout_features(np.empty((0, 1920)))[1].shape, (0, 1728))
        for invalid in (np.ones((1, 192)), np.zeros(1920), -vector, vector * np.nan):
            with self.subTest(shape=invalid.shape), self.assertRaises(ValueError):
                global_and_layout_features(invalid)

    def test_cosine_normalisation_and_empty_candidates(self):
        scores = cosine_scores([[3, 0]], [[9, 0], [0, 7], [-5, 0]])
        np.testing.assert_allclose(scores, [1, 0, -1])
        self.assertEqual(cosine_scores([1, 0], np.empty((0, 2))).shape, (0,))
        for query, frames in [([0, 0], [[1, 0]]), ([1, 0], [[0, 0]]), ([1, 0], [[1]]),
                              ([1, np.nan], [[1, 0]]), ([[1, 0], [0, 1]], [[1, 0]])]:
            with self.subTest(query=query), self.assertRaises(ValueError):
                cosine_scores(query, frames)


class RankFusionTests(unittest.TestCase):
    def test_average_ties_and_candidate_permutation_invariance(self):
        scores = {"content": [.9, .9, .1], "colour": [.1, .9, .9], "layout": [.9, .1, .9]}
        weights = {key: 1 for key in scores}
        original = weighted_rank_fusion(scores, weights)
        np.testing.assert_allclose(original, np.repeat(original[0], 3), atol=1e-15, rtol=0)
        permutation = np.array([2, 0, 1])
        permuted = weighted_rank_fusion({name: np.array(value)[permutation] for name, value in scores.items()}, weights)
        np.testing.assert_allclose(permuted, original[permutation], atol=1e-15, rtol=0)

    def test_signal_scale_does_not_change_fusion_and_weights_are_relative(self):
        scores = {"content": [0.2, 0.8, 0.3], "colour": [.9, .4, .2], "layout": [.1, .7, .2]}
        expected = weighted_rank_fusion(scores)
        changed = {name: np.array(values) * 13 + 400 for name, values in scores.items()}
        np.testing.assert_allclose(weighted_rank_fusion(changed), expected, atol=1e-15)
        np.testing.assert_allclose(weighted_rank_fusion(scores, {"content": 2, "colour": 1, "layout": 1}), expected)
        self.assertGreater(expected[1], expected[2])

    def test_fusion_validation(self):
        valid = {"content": [1, 2], "colour": [2, 1], "layout": [1, 2]}
        self.assertEqual(weighted_rank_fusion({name: [] for name in valid}).shape, (0,))
        invalid_calls = [({}, None, 60), (valid, {"content": 1}, 60),
                         (valid, {"content": 0, "colour": 1, "layout": 1}, 60),
                         (valid, {"content": -1, "colour": 1, "layout": 1}, 60),
                         (valid, {"content": np.nan, "colour": 1, "layout": 1}, 60),
                         (valid, None, 0), (valid, None, np.inf), (valid, None, True),
                         (valid, None, "60"), (valid, {"content": "0.5", "colour": .25, "layout": .25}, 60),
                         ({**valid, "colour": [1]}, None, 60),
                         ({**valid, "layout": [[1, 2]]}, None, 60),
                         ({**valid, "content": [1, np.nan]}, None, 60)]
        for values, weights, constant in invalid_calls:
            with self.subTest(values=values, weights=weights, k=constant), self.assertRaises(ValueError):
                weighted_rank_fusion(values, weights, constant)


class SelectionTests(unittest.TestCase):
    def test_eligibility_precedes_temporal_suppression_and_keeps_source_indices(self):
        result = select_scored_frames([.99, .98, .97, .96], [0, 1, 3, 6], 4, 3,
                                      np.array([False, True, True, True]))
        self.assertEqual([item["index"] for item in result], [1, 3])
        self.assertEqual(select_scored_frames([1, 2], [0, 4], 5, 3, [False, False]), [])

    def test_equal_boundary_tie_policy_and_native_score_scale(self):
        result = select_scored_frames([12, 12, 12, -5], [6, 0, 3, 9], 4, 3)
        self.assertEqual([item["index"] for item in result], [1, 2, 0, 3])
        self.assertEqual(result[0]["score"], 12)
        self.assertEqual(select_scored_frames([], [], 5, 3), [])

    def test_selection_validation(self):
        cases = [([1], [0], 0, 0, None), ([1], [0], True, 0, None),
                 ([1], [0], 1, -1, None), ([1], [0], 1, np.inf, None), ([1], [0], 1, "3", None),
                 ([1], [-1], 1, 0, None), ([np.nan], [0], 1, 0, None),
                 ([1, 2], [0], 1, 0, None), ([1], [0], 1, 0, [1]),
                 ([1], [0], 1, 0, ["false"]), ([1], [0], 1, 0, [])]
        for args in cases:
            with self.subTest(args=args), self.assertRaises(ValueError):
                select_scored_frames(*args)


@unittest.skipUnless(importlib.util.find_spec("torchvision"), "Optional torchvision is not installed.")
class FullFramePreprocessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from torchvision.transforms import Compose, Resize, CenterCrop, ToTensor, Normalize, InterpolationMode
        cls.mean = (0.48145466, 0.4578275, 0.40821073)
        cls.std = (0.26862954, 0.26130258, 0.27577711)
        cls.original = Compose([Resize(224, interpolation=InterpolationMode.BICUBIC), CenterCrop(224),
                                ToTensor(), Normalize(cls.mean, cls.std)])
        cls.complete = full_frame_preprocess(cls.original)

    def restore_rgb(self, tensor):
        return np.clip(tensor.numpy().transpose(1, 2, 0) * self.std + self.mean, 0, 1)

    def assert_edge_colours_retained(self, image):
        baseline = self.restore_rgb(self.original(image))
        complete = self.restore_rgb(self.complete(image))
        self.assertEqual(complete.shape, (224, 224, 3))
        red = lambda pixels: (pixels[..., 0] > .9) & (pixels[..., 1] < .1) & (pixels[..., 2] < .1)
        blue = lambda pixels: (pixels[..., 2] > .9) & (pixels[..., 0] < .1) & (pixels[..., 1] < .1)
        self.assertFalse(red(baseline).any())
        self.assertFalse(blue(baseline).any())
        self.assertTrue(red(complete).any())
        self.assertTrue(blue(complete).any())

    def test_portrait_retains_top_and_bottom_lost_by_center_crop(self):
        image = Image.new("RGB", (100, 300), "green")
        draw = ImageDraw.Draw(image)
        draw.rectangle((0, 0, 99, 59), fill="red")
        draw.rectangle((0, 240, 99, 299), fill="blue")
        self.assert_edge_colours_retained(image)
        # The leftmost column is padding close to zero after model normalisation.
        self.assertLess(float(abs(self.complete(image)[:, :, 0]).max()), .02)

    def test_landscape_retains_left_and_right_lost_by_center_crop(self):
        image = Image.new("RGB", (300, 100), "green")
        draw = ImageDraw.Draw(image)
        draw.rectangle((0, 0, 59, 99), fill="red")
        draw.rectangle((240, 0, 299, 99), fill="blue")
        self.assert_edge_colours_retained(image)

    def test_square_equivalence_and_original_pipeline_is_unchanged(self):
        import torch
        pixels = np.random.default_rng(19).integers(0, 256, (300, 300, 3), dtype=np.uint8)
        image = Image.fromarray(pixels)
        torch.testing.assert_close(self.original(image), self.complete(image), rtol=0, atol=0)
        self.assertEqual(len(self.original.transforms), 4)
        self.assertEqual(self.original.transforms[1].__class__.__name__, "CenterCrop")
        self.assertIs(self.original.transforms[-1], self.complete.transforms[-1])
        self.assertIn("fill_rgb=(123, 117, 104)", repr(self.complete))

    def test_unknown_preprocessing_is_rejected(self):
        from torchvision.transforms import Compose, Resize, ToTensor
        for pipeline in (None, Compose([Resize(224), ToTensor()])):
            with self.subTest(pipeline=pipeline), self.assertRaises(ValueError):
                full_frame_preprocess(pipeline)


if __name__ == "__main__":
    unittest.main()
