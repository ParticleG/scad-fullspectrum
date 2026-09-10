"""Tests for the mix solver, the row encoding and the plan it produces."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scad_fullspectrum.color import (  # noqa: E402
    blend_rgb,
    delta_e_2000,
    hex_to_rgb,
    rgb_to_hex,
    rgb_to_lab,
)
from scad_fullspectrum.mixes import Recipe, encode_definitions, plan, solve  # noqa: E402

BASES = [hex_to_rgb(c) for c in ("#FF00FF", "#00FFFF", "#808080", "#FFFF00")]


def decode_row(row: str) -> dict:
    """Independent decoder mirroring the slicer's loader for the fields we emit."""

    tokens = row.split(",")
    out = {
        "a": int(tokens[0]),
        "b": int(tokens[1]),
        "enabled": int(tokens[2]) != 0,
        "custom": int(tokens[3]) != 0,
        "percent_b": int(tokens[4]),
    }
    for token in tokens[5:]:
        if token.startswith("g"):
            out["gradient_ids"] = token[1:]
        elif token.startswith("w"):
            out["weights"] = token[1:]
        elif token.startswith("m"):
            out["mode"] = int(token[1:])
        elif token.startswith("d"):
            out["deleted"] = int(token[1:]) != 0
        elif token.startswith("o"):
            out["origin_auto"] = int(token[1:]) != 0
        elif token.startswith("u"):
            out["stable_id"] = int(token[1:])
    return out


class RecipeTests(unittest.TestCase):
    def test_pair_row_encodes_b_percentage(self) -> None:
        row = Recipe((1, 4), (55, 45)).encode(7)
        self.assertEqual(row, "1,4,1,1,45,0,g,w,m2,z0,xa0,xb0,d0,o0,u7,cm0")
        decoded = decode_row(row)
        self.assertEqual(decoded["percent_b"], 45)
        self.assertTrue(decoded["enabled"] and decoded["custom"])
        self.assertFalse(decoded["deleted"] or decoded["origin_auto"])

    def test_multi_component_row_lists_ids_and_weights_ascending(self) -> None:
        row = Recipe((1, 2, 3), (20, 30, 50)).encode(9)
        self.assertEqual(row, "1,2,1,1,50,0,g123,w20/30/50,m0,z0,xa0,xb0,d0,o0,u9,cm0")

    def test_quad_row(self) -> None:
        row = Recipe((1, 2, 3, 4), (10, 20, 30, 40)).encode(1)
        self.assertEqual(row, "1,2,1,1,50,0,g1234,w10/20/30/40,m0,z0,xa0,xb0,d0,o0,u1,cm0")

    def test_invalid_recipes_rejected(self) -> None:
        with self.assertRaises(ValueError):
            Recipe((1, 1), (50, 50))
        with self.assertRaises(ValueError):
            Recipe((2, 1), (50, 50))
        with self.assertRaises(ValueError):
            Recipe((1, 2), (40, 40))
        with self.assertRaises(ValueError):
            Recipe((1,), (100,))

    def test_encode_definitions_joins_rows(self) -> None:
        text = encode_definitions([(Recipe((1, 2), (50, 50)), 1), (Recipe((2, 3), (80, 20)), 2)])
        self.assertEqual(len(text.split(";")), 2)
        self.assertTrue(text.startswith("1,2,1,1,50"))


class SolveTests(unittest.TestCase):
    def test_exact_spool_match_is_returned_as_a_single(self) -> None:
        suggestion = solve(hex_to_rgb("#FFFF00"), BASES)
        self.assertEqual(suggestion.slot, 4)
        self.assertIsNone(suggestion.recipe)

    def test_mix_between_two_spools(self) -> None:
        suggestion = solve(hex_to_rgb("#FF8080"), BASES, components=2)
        self.assertIsNotNone(suggestion.recipe)
        self.assertEqual(set(suggestion.recipe.slots), {1, 4})
        self.assertLess(suggestion.delta_e, 20)

    def test_more_components_can_only_help(self) -> None:
        target = hex_to_rgb("#B0B0FF")
        pairs = solve(target, BASES, components=2)
        triples = solve(target, BASES, components=3)
        self.assertLessEqual(triples.delta_e, pairs.delta_e + 1e-9)


class PlanTests(unittest.TestCase):
    def test_same_colour_shares_one_row(self) -> None:
        target = hex_to_rgb("#00CCFF")
        result = plan([target, target], BASES)
        self.assertEqual(len(result.rows), 1)
        self.assertEqual(result.extruder_of(target), 5)

    def test_pure_spool_does_not_create_a_row(self) -> None:
        result = plan([hex_to_rgb("#FF00FF")], BASES)
        self.assertEqual(result.rows, [])
        self.assertEqual(result.extruder_of(hex_to_rgb("#FF00FF")), 1)

    def test_virtual_ids_start_after_the_physical_spools(self) -> None:
        targets = [hex_to_rgb("#00CCFF"), hex_to_rgb("#FFCC00")]
        result = plan(targets, BASES)
        self.assertEqual(len(result.rows), 2)
        self.assertEqual(sorted(assignment.extruder for assignment in result.assignments.values()), [5, 6])

    def test_max_mixes_collapses_the_closest_rows(self) -> None:
        targets = [hex_to_rgb("#00CCFF"), hex_to_rgb("#00B2FF"), hex_to_rgb("#FFCC00")]
        result = plan(targets, BASES, max_mixes=2)
        self.assertEqual(len(result.rows), 2)
        self.assertEqual(sorted({a.extruder for a in result.assignments.values()}), [5, 6])

    def test_collapsed_assignments_match_their_recipe(self) -> None:
        """After merging, blend and ΔE must describe the recipe actually printed."""

        targets = [hex_to_rgb("#00CCFF"), hex_to_rgb("#00E6FF"), hex_to_rgb("#FFCC00")]
        merged = plan(targets, BASES, max_mixes=1)

        self.assertEqual(len(merged.rows), 1)
        recipe, _ = merged.rows[0]
        for target in targets:
            assignment = merged.assignments[target]
            self.assertEqual(assignment.recipe, recipe)
            expected_blend = blend_rgb(
                [(BASES[slot - 1], float(pct)) for slot, pct in zip(recipe.slots, recipe.percents)]
            )
            self.assertEqual(assignment.blend, expected_blend)
            self.assertAlmostEqual(
                assignment.delta_e,
                delta_e_2000(rgb_to_lab(target), rgb_to_lab(expected_blend)),
                places=9,
            )

        # Merging really does move at least one colour onto a different recipe,
        # which is the case this test exists for.
        unmerged = plan(targets, BASES)
        worsened = [
            target
            for target in targets
            if merged.assignments[target].recipe != unmerged.assignments[target].recipe
        ]
        self.assertTrue(worsened, "merging should reassign at least one colour")
        for target in worsened:
            self.assertAlmostEqual(
                merged.assignments[target].delta_e,
                delta_e_2000(rgb_to_lab(target), rgb_to_lab(merged.assignments[target].blend)),
                places=9,
            )
            self.assertGreater(
                merged.assignments[target].delta_e,
                unmerged.assignments[target].delta_e - 1e-9,
            )

    def test_rows_are_stable_in_extruder_order(self) -> None:
        targets = [hex_to_rgb("#00CCFF"), hex_to_rgb("#FFCC00")]
        result = plan(targets, BASES)
        self.assertEqual(
            [recipe.encode(uid) for recipe, uid in result.rows],
            encode_definitions(result.rows).split(";"),
        )
        self.assertEqual(rgb_to_hex(BASES[0]), "#FF00FF")


if __name__ == "__main__":
    unittest.main()
