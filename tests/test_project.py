"""Tests for the 3MF package writer and the end-to-end pipeline."""

from __future__ import annotations

import json
import shutil
import sys
import unittest
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scad_fullspectrum.color import hex_to_rgb  # noqa: E402
from scad_fullspectrum.pipeline import BuildOptions, build  # noqa: E402
from scad_fullspectrum.threemf import Part, write_project  # noqa: E402

SETTINGS = {
    "version": "2.3.6",
    "name": "project_settings",
    "filament_colour": ["#000000"] * 4,
    "filament_multi_colors": ["#000000"] * 4,
    "filament_type": ["PLA"] * 4,
    "printer_model": "Snapmaker U1",
    "nozzle_diameter": ["0.4"],
}

BASES = [hex_to_rgb(c) for c in ("#FF00FF", "#00FFFF", "#808080", "#FFFF00")]

SQUARE = [(0.0, 0.0, 0.0), (2.0, 0.0, 0.0), (2.0, 2.0, 0.0), (0.0, 2.0, 0.0)]
TRIANGLES = [(0, 1, 2), (0, 2, 3)]


def make_part(part_id: int, extruder: int, offset: float = 0.0) -> Part:
    vertices = [(x + offset, y, z) for x, y, z in SQUARE]
    return Part(id=part_id, name=f"part{part_id}", extruder=extruder, vertices=vertices, triangles=list(TRIANGLES))


class WriterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        self.path = Path(self.tmp.name) / "demo.3mf"
        write_project(
            self.path,
            [make_part(1, 1), make_part(2, 5, offset=3.0)],
            SETTINGS,
            model_name="demo",
            base_colors=BASES,
            definitions="1,2,1,1,50,0,g,w,m2,z0,xa0,xb0,d0,o0,u1,cm0",
        )
        self.archive = zipfile.ZipFile(self.path)

    def tearDown(self) -> None:
        self.archive.close()
        self.tmp.cleanup()

    def test_package_members(self) -> None:
        expected = {
            "[Content_Types].xml",
            "_rels/.rels",
            "3D/3dmodel.model",
            "3D/_rels/3dmodel.model.rels",
            "3D/Objects/demo_1.model",
            "Metadata/project_settings.config",
            "Metadata/model_settings.config",
            "Metadata/slice_info.config",
        }
        self.assertEqual(set(self.archive.namelist()), expected)

    def test_every_member_is_well_formed_xml_or_json(self) -> None:
        for name in self.archive.namelist():
            data = self.archive.read(name)
            if name == "Metadata/project_settings.config":
                json.loads(data)
            else:
                ET.fromstring(data)

    def test_root_object_references_every_part(self) -> None:
        model = ET.fromstring(self.archive.read("3D/3dmodel.model"))
        namespace = {"c": "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"}
        root = model.find("c:resources/c:object", namespace)
        components = root.findall("c:components/c:component", namespace)
        self.assertEqual([c.get("objectid") for c in components], ["1", "2"])
        self.assertEqual(root.get("id"), "3")
        build_item = model.find("c:build/c:item", namespace)
        self.assertEqual(build_item.get("objectid"), "3")

    def test_parts_carry_their_extruder(self) -> None:
        settings = ET.fromstring(self.archive.read("Metadata/model_settings.config"))
        parts = settings.findall("object/part")
        self.assertEqual(len(parts), 2)
        extruders = [
            metadata.get("value")
            for part in parts
            for metadata in part.findall("metadata")
            if metadata.get("key") == "extruder"
        ]
        self.assertEqual(extruders, ["1", "5"])

    def test_project_settings_are_patched(self) -> None:
        settings = json.loads(self.archive.read("Metadata/project_settings.config"))
        self.assertEqual(settings["filament_colour"], ["#FF00FF", "#00FFFF", "#808080", "#FFFF00"])
        self.assertEqual(settings["filament_type"], ["PLA"] * 4)
        self.assertTrue(settings["mixed_filament_definitions"].startswith("1,2,1,1,50"))

    def test_model_is_centred_on_the_plate(self) -> None:
        settings = ET.fromstring(self.archive.read("Metadata/model_settings.config"))
        transform = settings.find("assemble/assemble_item").get("transform").split()
        # Part 2 spans x = 3..5, part 1 spans x = 0..2 -> centre 2.5 goes to 135.
        self.assertAlmostEqual(float(transform[9]), 132.5, places=4)
        self.assertAlmostEqual(float(transform[10]), 134.0, places=4)
        self.assertAlmostEqual(float(transform[11]), 0.0, places=4)


@unittest.skipUnless(shutil.which("openscad"), "openscad is required for the pipeline test")
class PipelineTests(unittest.TestCase):
    SCAD = """
color([1, 0, 0]) { cube(size = [4, 4, 2]); }
translate([6, 0, 0]) { color([0, 1, 0]) { cube(size = [4, 4, 2]); } }
translate([12, 0, 0]) { cube(size = [4, 4, 2]); }
"""

    def test_end_to_end(self) -> None:
        with TemporaryDirectory() as tmp:
            scad = Path(tmp) / "sample.scad"
            scad.write_text(self.SCAD)
            options = BuildOptions(
                base_colors=BASES,
                uncolored=hex_to_rgb("#808080"),
                physical_count=4,
                components=2,
            )
            report = build(scad, Path(tmp) / "sample.3mf", options, dict(SETTINGS))

            self.assertEqual(len(report.parts), 3)
            self.assertEqual(report.triangles, 36)  # 3 cubes x 12 triangles
            self.assertEqual({part["extruder"] for part in report.parts}, {3, 5, 6})
            # Red and green need a blend; the grey part matches spool 3 exactly.
            self.assertEqual(len(report.rows), 2)
            self.assertEqual([row["slots"] for row in report.rows], [[1, 4], [2, 4]])

            archive = zipfile.ZipFile(Path(tmp) / "sample.3mf")
            settings = json.loads(archive.read("Metadata/project_settings.config"))
            rows = settings["mixed_filament_definitions"].split(";")
            self.assertEqual(len(rows), 2)
            self.assertTrue(rows[0].startswith("1,4,1,1,"))
            self.assertTrue(rows[1].startswith("2,4,1,1,"))

    def test_coloured_hull_stays_printable(self) -> None:
        with TemporaryDirectory() as tmp:
            scad = Path(tmp) / "hull.scad"
            scad.write_text(
                "color([1, 0, 0]) { hull() { sphere(r=2); translate([6, 0, 0]) { sphere(r=2); } } }\n"
            )
            report = build(
                scad,
                Path(tmp) / "hull.3mf",
                BuildOptions(base_colors=BASES, physical_count=4),
                dict(SETTINGS),
            )
            self.assertEqual(len(report.parts), 1)
            self.assertEqual(report.parts[0]["name"], "#FF0000")
            self.assertGreater(report.parts[0]["triangles"], 0)

    def test_uncolored_geometry_is_dropped_without_a_target(self) -> None:
        with TemporaryDirectory() as tmp:
            scad = Path(tmp) / "sample.scad"
            scad.write_text(self.SCAD)
            report = build(
                scad,
                Path(tmp) / "sample.3mf",
                BuildOptions(base_colors=BASES, physical_count=4),
                dict(SETTINGS),
            )
            self.assertEqual(len(report.parts), 2)
            self.assertTrue(any("uncolored" in warning for warning in report.warnings))


if __name__ == "__main__":
    unittest.main()
