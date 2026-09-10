"""Tests for the blend models (opaque average, slicer pigment, translucent)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scad_fullspectrum.color import (  # noqa: E402
    EXPERIMENTAL_MODELS,
    MIX_MODELS,
    blend_pigment,
    blend_rgb,
    blend_transmission,
    hex_to_rgb,
    mix_model,
)

BLUE = hex_to_rgb("#002185")   # 0, 33, 133 from the model's own doc example
YELLOW = hex_to_rgb("#FCD300")  # 252, 211, 0
MAGENTA = hex_to_rgb("#FF00FF")
CYAN = hex_to_rgb("#00FFFF")
GREY = hex_to_rgb("#808080")


class PigmentModelTests(unittest.TestCase):
    def test_matches_the_reference_implementation(self) -> None:
        # Documented example of FilamentMixerModel.hpp: blue + yellow -> green.
        self.assertEqual(blend_pigment([(BLUE, 1.0), (YELLOW, 1.0)]), (47, 141, 56))

    def test_matches_the_swatches_snapmaker_orca_draws(self) -> None:
        # Recipes from a project written by this tool, opened in Snapmaker Orca
        # 2.3.6; the expected values are the swatch pixels the slicer painted
        # (sampled from a screenshot of its filament panel).
        cmy = [hex_to_rgb(c) for c in ("#FF00FF", "#00FFFF", "#808080", "#FFFF00")]
        cases = [
            ([(cmy[0], 33.0), (cmy[1], 34.0), (cmy[3], 33.0)], (155, 187, 125)),
            ([(cmy[0], 36.0), (cmy[1], 44.0), (cmy[3], 20.0)], (134, 174, 166)),
        ]
        for components, swatch in cases:
            predicted = blend_pigment(components)
            self.assertLessEqual(max(abs(a - b) for a, b in zip(predicted, swatch)), 2)

    def test_endpoints_are_exact(self) -> None:
        self.assertEqual(blend_pigment([(BLUE, 1.0), (YELLOW, 0.0)]), BLUE)
        self.assertEqual(blend_pigment([(BLUE, 0.0), (YELLOW, 1.0)]), YELLOW)

    def test_single_component_passes_through(self) -> None:
        self.assertEqual(blend_pigment([(MAGENTA, 1.0)]), MAGENTA)

    def test_three_components_follow_the_slicer_accumulation(self) -> None:
        # The slicer folds the components pairwise, weighted by accumulation order.
        expected = blend_pigment(
            [blend_pigment([(MAGENTA, 33.0), (CYAN, 34.0)]), (0, 0, 0)]
        ) if False else None
        del expected
        blended = blend_pigment([(MAGENTA, 33.0), (CYAN, 34.0), (GREY, 33.0)])
        two_way = blend_pigment([(MAGENTA, 33.0), (CYAN, 34.0)])
        self.assertEqual(blended, blend_pigment([(two_way, 67.0), (GREY, 33.0)]))

    def test_pigment_differs_from_the_plain_average(self) -> None:
        self.assertNotEqual(blend_pigment([(BLUE, 1.0), (YELLOW, 1.0)]), blend_rgb([(BLUE, 1.0), (YELLOW, 1.0)]))


class TransmissionModelTests(unittest.TestCase):
    """Documents the *assumed* behaviour of the experimental translucent model.

    These assertions pin the formula (so a refactor cannot change it silently);
    they say nothing about how translucent filament actually prints.
    """
    def test_magenta_plus_yellow_is_red(self) -> None:
        red = blend_transmission([(MAGENTA, 1.0), (YELLOW, 1.0)])
        self.assertGreater(red[0], 200)
        self.assertLess(red[1], 120)
        self.assertLess(red[2], 120)

    def test_cyan_plus_yellow_is_green_and_cyan_plus_magenta_is_blue(self) -> None:
        green = blend_transmission([(CYAN, 1.0), (YELLOW, 1.0)])
        blue = blend_transmission([(CYAN, 1.0), (MAGENTA, 1.0)])
        self.assertEqual(max(range(3), key=lambda c: green[c]), 1)
        self.assertEqual(max(range(3), key=lambda c: blue[c]), 2)

    def test_grey_darkens_and_desaturates(self) -> None:
        blended = blend_transmission([(MAGENTA, 1.0), (GREY, 1.0)])
        # The filter halves the light: the channels magenta transmits drop hard,
        # and the overall luminance falls.
        self.assertLess(blended[0], MAGENTA[0])
        self.assertLess(blended[2], MAGENTA[2])
        self.assertLess(sum(blended), sum(MAGENTA))

    def test_single_component_passes_through(self) -> None:
        self.assertEqual(blend_transmission([(CYAN, 1.0)]), CYAN)

    def test_weights_are_normalised(self) -> None:
        self.assertEqual(
            blend_transmission([(MAGENTA, 3.0), (YELLOW, 3.0)]),
            blend_transmission([(MAGENTA, 1.0), (YELLOW, 1.0)]),
        )


class RegistryTests(unittest.TestCase):
    def test_names(self) -> None:
        self.assertEqual(set(MIX_MODELS), {"average", "pigment", "transmission"})
        for name in MIX_MODELS:
            self.assertTrue(callable(mix_model(name)))

    def test_transmission_is_flagged_experimental(self) -> None:
        self.assertEqual(set(EXPERIMENTAL_MODELS), {"transmission"})
        for name in EXPERIMENTAL_MODELS:
            self.assertIn(name, MIX_MODELS)

    def test_unknown_model_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            mix_model("mixbox")


if __name__ == "__main__":
    unittest.main()
