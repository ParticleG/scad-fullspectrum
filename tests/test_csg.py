"""Tests for the CSG parser and the colour splitter."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scad_fullspectrum import csg  # noqa: E402

RED = (255, 0, 0)
GREEN = (0, 255, 0)
BLUE = (0, 0, 255)
YELLOW = (255, 255, 0)

SAMPLE = """color([1, 0, 0, 1]) {
\tsquare(size = [10, 10]);
}
multmatrix([[1, 0, 0, 5], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]) {
\tcolor([0, 1, 0, 1]) {
\t\tcube(size = [1, 2, 3], center = false);
\t}
}
difference() {
\tcolor([0, 0, 1, 1]) {
\t\tcube(size = [10, 10, 10]);
\t}
\tcolor([1, 1, 0, 1]) {
\t\tsphere($fn = 0, r = 6);
\t}
}
"""


def names(nodes: list[csg.Node]) -> list[str]:
    out: list[str] = []
    for node in nodes:
        out.append(node.name)
        if node.children:
            out.extend(names(node.children))
    return out


class ParseTests(unittest.TestCase):
    def test_round_trip_preserves_structure(self) -> None:
        tree = csg.parse(SAMPLE)
        self.assertEqual(names(tree), names(csg.parse(csg.dump(tree))))

    def test_values(self) -> None:
        tree = csg.parse(SAMPLE)
        first = tree[0]
        self.assertEqual(first.name, "color")
        self.assertEqual(first.positional().__next__(), [1, 0, 0, 1])
        square = first.children[0]
        self.assertEqual(square.arg("size"), [10, 10])

    def test_comments_and_modifiers(self) -> None:
        tree = csg.parse("// leading\n%cube(size = [1, 1, 1]); /* inner */ #sphere(r = 2);")
        self.assertEqual([node.name for node in tree], ["cube", "sphere"])
        self.assertEqual([node.modifier for node in tree], ["%", "#"])

    def test_background_geometry_is_not_printed(self) -> None:
        tree = csg.parse("%cube(size=[1,1,1]); color([1,0,0,1]) { sphere(r=1); }")
        self.assertEqual(set(csg.iter_colors(tree)), {RED})
        self.assertEqual(names(csg.split_for_color(tree, RED)), ["color", "sphere"])
        self.assertEqual(csg.split_for_color(tree, None), [])

    def test_root_modifier_selects_a_single_subtree(self) -> None:
        tree = csg.select_root(csg.parse("!translate([1,0,0]) { cube(size=[1,1,1]); } sphere(r=1);"))
        self.assertEqual(names(tree), ["translate", "cube"])

    def test_number_formatting(self) -> None:
        self.assertEqual(csg.dump([csg.Node("cube", [(None, [1.5, -41.4079666])], None)]), "cube([1.5, -41.4079666]);")

    def test_argumentless_containers_keep_their_parentheses(self) -> None:
        # OpenSCAD only accepts ``group()``, never a bare ``group``.
        text = "group() { union() { cube(); difference() { cube(); sphere(); } } }"
        dumped = csg.dump(csg.parse(text))
        self.assertIn("group() {", dumped)
        self.assertIn("union() {", dumped)
        self.assertIn("difference() {", dumped)
        self.assertEqual(names(csg.parse(dumped)), names(csg.parse(text)))


class ColorTests(unittest.TestCase):
    def test_iter_colors(self) -> None:
        self.assertEqual(set(csg.iter_colors(csg.parse(SAMPLE))), {RED, GREEN, BLUE, YELLOW})

    def test_innermost_scope_wins(self) -> None:
        tree = csg.parse("color([1,0,0,1]) { color([0,1,0,1]) { cube(size=[1,1,1]); } }")
        self.assertEqual(set(csg.iter_colors(tree)), {GREEN})
        self.assertEqual(csg.split_for_color(tree, GREEN), tree)

    def test_uncolored_detection(self) -> None:
        tree = csg.parse("cube(size=[1,1,1]); color([1,0,0,1]) { sphere(r=1); }")
        self.assertTrue(any(csg.split_for_color(tree, None)))
        self.assertEqual(csg.split_for_color(csg.parse(SAMPLE), None), [])


class SplitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tree = csg.parse(SAMPLE)

    def test_leaf_selection(self) -> None:
        red = csg.split_for_color(self.tree, RED)
        self.assertEqual(sum(1 for node in red for _ in [0]), 1)
        self.assertIn("square", names(red))
        self.assertNotIn("cube", names(red))

    def test_difference_keeps_cutters(self) -> None:
        blue = csg.split_for_color(self.tree, BLUE)
        self.assertIn("difference", names(blue))
        self.assertIn("sphere", names(blue))
        self.assertEqual(blue[0].children[1].name, "color")

    def test_cutter_colour_gets_nothing(self) -> None:
        # The yellow sphere is only a cutter: it never exists as printed material.
        self.assertEqual(csg.split_for_color(self.tree, YELLOW), [])

    def test_difference_without_base_colour_drops_out(self) -> None:
        tree = csg.parse(
            "difference() { color([1,0,0,1]) { cube(size=[4,4,4]); } sphere(r=3); }"
        )
        self.assertEqual(csg.split_for_color(tree, GREEN), [])

    def test_hull_goes_to_the_first_colour(self) -> None:
        tree = csg.parse(
            "hull() { color([1,0,0,1]) { sphere(r=3); } color([0,0,1,1]) { cube(size=[2,2,2]); } }"
        )
        red = csg.split_for_color(tree, RED)
        self.assertEqual(names(red), ["hull", "color", "sphere", "color", "cube"])
        self.assertEqual(csg.split_for_color(tree, BLUE), [])

    def test_hull_inherits_the_enclosing_colour(self) -> None:
        tree = csg.parse(
            "color([1,0,0,1]) { hull() { sphere(r=1); translate([3,0,0]) { sphere(r=1); } } }"
        )
        self.assertEqual(set(csg.iter_colors(tree)), {RED})
        self.assertEqual(
            names(csg.split_for_color(tree, RED)),
            ["color", "hull", "sphere", "translate", "sphere"],
        )
        self.assertEqual(csg.split_for_color(tree, BLUE), [])
        self.assertEqual(csg.split_for_color(tree, None), [])

    def test_minkowski_inherits_the_enclosing_colour(self) -> None:
        tree = csg.parse("color([0,1,0,1]) { minkowski() { cube(size=[1,1,1]); sphere(r=0.5); } }")
        self.assertEqual(
            names(csg.split_for_color(tree, GREEN)), ["color", "minkowski", "cube", "sphere"]
        )
        self.assertEqual(csg.split_for_color(tree, None), [])

    def test_uncoloured_hull_belongs_to_the_uncoloured_geometry(self) -> None:
        tree = csg.parse("hull() { sphere(r=1); translate([2,0,0]) { sphere(r=1); } }")
        self.assertTrue(csg.split_for_color(tree, None))
        self.assertEqual(csg.split_for_color(tree, RED), [])

    def test_intersection_keeps_bounding_children(self) -> None:
        tree = csg.parse(
            "intersection() { cube(size=[10,10,10]); color([1,0,0,1]) { sphere(r=7); } }"
        )
        red = csg.split_for_color(tree, RED)
        self.assertEqual(names(red), ["intersection", "cube", "color", "sphere"])

    def test_transform_chain_is_preserved(self) -> None:
        red = csg.split_for_color(self.tree, RED)
        self.assertEqual(red[0].name, "color")


if __name__ == "__main__":
    unittest.main()
