"""Tests for the built-in spool presets and the config precedence rules."""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scad_fullspectrum import presets  # noqa: E402
from scad_fullspectrum.cli import _resolve_config, _base_colors  # noqa: E402
from scad_fullspectrum.color import MIX_MODELS, hex_to_rgb  # noqa: E402
from scad_fullspectrum.pipeline import BuildOptions, build  # noqa: E402

EXPECTED = {"translucent-cmyg", "pla-cmyk", "pla-cmyw", "pla-cmyg", "pla-rybw"}


class RegistryTests(unittest.TestCase):
    def test_expected_presets_exist(self) -> None:
        self.assertEqual(set(presets.names()), EXPECTED)

    def test_every_preset_is_usable(self) -> None:
        for name in presets.names():
            with self.subTest(preset=name):
                config = presets.get(name)
                colors, names = _base_colors(config)
                self.assertEqual(len(colors), 4, "presets target the four U1 toolheads")
                self.assertEqual([entry["slot"] for entry in config["base_filaments"]], [1, 2, 3, 4])
                self.assertTrue(all(entry["name"] for entry in config["base_filaments"]))
                for color in colors:
                    self.assertEqual(len(color), 3)
                    self.assertTrue(all(0 <= channel <= 255 for channel in color))
                mix = config["mix"]
                self.assertIn(mix["model"], MIX_MODELS)
                self.assertIn(mix["components"], (2, 3, 4))
                self.assertIn(mix["step"], (1, 2, 5, 10))
                self.assertTrue(names)

    def test_translucent_preset_uses_the_experimental_model(self) -> None:
        config = presets.get("translucent-cmyg")
        self.assertEqual(config["mix"]["model"], "transmission")
        self.assertIn("experimental", config["note"].lower())

    def test_opaque_presets_use_the_slicer_model(self) -> None:
        for name in ("pla-cmyk", "pla-cmyw", "pla-cmyg", "pla-rybw"):
            self.assertEqual(presets.get(name)["mix"]["model"], "pigment")

    def test_get_returns_an_isolated_copy(self) -> None:
        first = presets.get("pla-cmyw")
        first["base_filaments"][0]["color"] = "#123456"
        first["mix"]["step"] = 17
        second = presets.get("pla-cmyw")
        self.assertEqual(second["base_filaments"][0]["color"], "#00FFFF")
        self.assertEqual(second["mix"]["step"], 5)

    def test_unknown_preset_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            presets.get("pla-nope")
        self.assertFalse(presets.is_preset("pla-nope"))

    def test_describe_mentions_the_model_and_spools(self) -> None:
        text = presets.describe("pla-cmyk")
        self.assertIn("pigment", text)
        self.assertIn("Black", text)


class MergeTests(unittest.TestCase):
    def test_file_overrides_preset_keys(self) -> None:
        merged = presets.merge(presets.get("pla-cmyw"), {"mix": {"step": 1}, "uncolored": 4})
        self.assertEqual(merged["mix"]["step"], 1)
        # untouched preset keys survive
        self.assertEqual(merged["mix"]["model"], "pigment")
        self.assertEqual(merged["mix"]["components"], 2)
        self.assertEqual(merged["uncolored"], 4)

    def test_base_filaments_are_replaced_not_merged(self) -> None:
        override = {"base_filaments": [{"slot": index, "color": "#101010"} for index in range(1, 5)]}
        merged = presets.merge(presets.get("pla-cmyw"), override)
        self.assertEqual(merged["base_filaments"][0]["color"], "#101010")
        self.assertNotIn("name", merged["base_filaments"][0])


class ResolutionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_preset_flag(self) -> None:
        config = _resolve_config(None, "pla-cmyk")
        colors, names = _base_colors(config)
        self.assertEqual(names[3], "Black")
        self.assertEqual(colors[3], (0, 0, 0))

    def test_config_file_beats_preset(self) -> None:
        path = Path(self.tmp.name) / "mine.json"
        path.write_text(json.dumps({"mix": {"model": "average"}, "uncolored": 2}))
        config = _resolve_config(str(path), "pla-cmyk")
        self.assertEqual(config["mix"]["model"], "average")
        self.assertEqual(config["mix"]["components"], 2)
        self.assertEqual(config["uncolored"], 2)
        self.assertIn("Black", _base_colors(config)[1])

    def test_dash_c_accepts_a_preset_name(self) -> None:
        config = _resolve_config("pla-rybw", None)
        self.assertEqual(config["mix"]["components"], 3)

    def test_missing_config_file_is_an_error(self) -> None:
        with self.assertRaises(FileNotFoundError):
            _resolve_config(str(Path(self.tmp.name) / "absent.json"), None)


@unittest.skipUnless(shutil.which("openscad"), "openscad is required for the pipeline test")
class PresetBuildTests(unittest.TestCase):
    def test_build_from_a_preset(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            scad = Path(tmp) / "square.scad"
            scad.write_text("color([1, 0, 0]) { cube(size = [4, 4, 2]); }\n")
            config = _resolve_config(None, "translucent-cmyg")
            colors, names = _base_colors(config)
            mix = config["mix"]
            report = build(
                scad,
                Path(tmp) / "out.3mf",
                BuildOptions(
                    base_colors=colors,
                    base_names=names,
                    physical_count=4,
                    components=mix["components"],
                    step=mix["step"],
                    mix_model=mix["model"],
                ),
                {"version": "2.3.6", "filament_colour": ["#000000"] * 4},
            )
            self.assertEqual(report.mix_model, "transmission")
            self.assertTrue(report.mix_model_experimental)
            self.assertEqual(len(report.parts), 1)
            self.assertEqual(report.colors[0]["extruder"], 5)
            self.assertEqual(len(report.rows), 1)
            # Red is magenta + yellow in the set this preset loads.
            self.assertEqual(report.rows[0]["slots"], [2, 3])
            self.assertTrue(0 <= hex_to_rgb(report.colors[0]["blend"])[0] <= 255)


if __name__ == "__main__":
    unittest.main()
