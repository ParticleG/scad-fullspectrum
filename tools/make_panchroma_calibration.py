#!/usr/bin/env python3
"""Generate unmeasured Panchroma CMYN calibration projects and recording sheets.

    python3 tools/make_panchroma_calibration.py /path/to/new-output-directory

Open the 3MF projects in Snapmaker Orca / FullSpectrum, not the generated SCAD
geometry references. Recipes bypass the colour solver. Display HEX and TD values
are vendor metadata, not measured transmission spectra or predicted patch colours.
General and i1Pro 2 recording sheets are generated with an instrument guide.
See README.md for printing, measurement and experiment archival precautions.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import dataclass
from itertools import combinations, product
from pathlib import Path
from xml.sax.saxutils import escape

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scad_fullspectrum.cli import load_settings_template  # noqa: E402
from scad_fullspectrum.mixes import Recipe, encode_definitions  # noqa: E402
from scad_fullspectrum.threemf import Part, write_project  # noqa: E402

FILAMENTS = (
    ("C", "cyan", "CA02001", "#08ABFB", 8.0),
    ("M", "magenta", "CA02002", "#D93B90", 7.8),
    ("Y", "yellow", "CA02003", "#F9ED3D", 14.0),
    ("N", "grey", "CA02004", "#9199A4", 11.5),
)
BASE_COLORS = [tuple(bytes.fromhex(filament[3][1:])) for filament in FILAMENTS]
THICKNESS_UNITS = (2, 3, 4, 6, 8, 12, 16, 32, 64, 128, 192)
POINTS = ((2, 0), (20, 0), (20, 20), (0, 20), (0, 2))
LAYER_HEIGHT = 0.08
FIRST_LAYER_HEIGHT = 0.16
MIX_THICKNESS = 3.2
ORDER_UNIT = 0.16
PITCH = 25
SOURCES = {
    "vendor_hex_td": "https://wiki.polymaker.com/polymaker-products/more-about-our-products/hex-codes-and-transmission-distances",
    "vendor_method": "https://wiki.polymaker.com/polymaker-products/more-about-our-products/unique-product-questions/unique-product-questions-2025",
    "stack_measurement_method": "https://doi.org/10.31224/7794",
}
PROCESS = {
    "layer_height": str(LAYER_HEIGHT),
    "initial_layer_print_height": str(FIRST_LAYER_HEIGHT),
    "sparse_infill_density": "100%",
    "sparse_infill_pattern": "rectilinear",
    "infill_combination": "0",
    "wall_loops": "2",
    "ironing_type": "no ironing",
    "enable_support": "0",
    "brim_type": "no_brim",
    "print_sequence": "by layer",
    "mixed_filament_region_collapse": "0",
    "wipe_tower_x": ["235"],
    "wipe_tower_y": ["225"],
}
BACKINGS = (
    ("WB01", "white", "W"),
    ("BB01", "black", "B"),
)


@dataclass(frozen=True)
class Coupon:
    sample_id: str
    role: str
    percents: tuple[int, ...]
    thickness: float
    sequence: tuple[int, ...] = ()


def coupons_by_plate() -> dict[str, list[Coupon]]:
    plates = {}
    for slot, filament in enumerate(FILAMENTS):
        percents = tuple(100 if i == slot else 0 for i in range(4))
        plates[f"thickness-{filament[1]}"] = [
            Coupon(f"T{filament[0]}{i + 1:02}", "thickness", percents, round(units * LAYER_HEIGHT, 2))
            for i, units in enumerate(THICKNESS_UNITS)
        ]

    lattice = [tuple(25 * n for n in row) for row in product(range(5), repeat=4) if sum(row) == 4]
    lattice.sort(key=lambda row: (sum(n > 0 for n in row), tuple(-n for n in row)))
    plates["mix-fit"] = [
        Coupon(f"F{i + 1:03}", "fit", row, MIX_THICKNESS) for i, row in enumerate(lattice)
    ]
    plates["mix-fit"].extend(
        Coupon(f"F{i:03}", "repeatability", (25, 25, 25, 25), MIX_THICKNESS) for i in (36, 37)
    )

    holdout = []
    for slots in combinations(range(4), 2):
        for percent in (10, 90):
            row = [0] * 4
            row[slots[0]], row[slots[1]] = percent, 100 - percent
            holdout.append(tuple(row))
    for slots in combinations(range(4), 3):
        row = [0] * 4
        for slot, percent in zip(slots, (20, 30, 50)):
            row[slot] = percent
        holdout.append(tuple(row))
    row = (10, 20, 30, 40)
    holdout.extend(row[i:] + row[:i] for i in range(4))
    plates["mix-holdout"] = [
        Coupon(f"V{i + 1:03}", "holdout", row, MIX_THICKNESS) for i, row in enumerate(holdout)
    ]

    sequences = [
        (1,) * 10 + (2,) * 10,
        (2,) * 10 + (1,) * 10,
        (1, 2) * 10,
        (2, 1) * 10,
        (1, 2, 3, 4) * 5,
        (4, 3, 2, 1) * 5,
    ]
    plates["layer-order"] = [
        Coupon(
            f"O{i + 1:02}", "layer_order",
            tuple(5 * sequence.count(slot) for slot in range(1, 5)),
            MIX_THICKNESS, sequence,
        )
        for i, sequence in enumerate(sequences)
    ]
    return plates


def prism(part_id: int, name: str, extruder: int, x: float, y: float, z: float, height: float) -> Part:
    count = len(POINTS)
    vertices = [(x + px, y + py, pz) for pz in (z, z + height) for px, py in POINTS]
    triangles = []
    for i in range(1, count - 1):
        triangles.extend(((0, i + 1, i), (count, count + i, count + i + 1)))
    for i in range(count):
        j = (i + 1) % count
        triangles.extend(((i, j, count + j), (i, count + j, count + i)))
    return Part(part_id, name, extruder, vertices, triangles)


def write_plate(output: Path, name: str, coupons: list[Coupon], template: dict) -> list[dict]:
    parts, rows, records = [], [], []
    mixed_extruders = {}
    columns = min(6, len(coupons))
    row_count = (len(coupons) + columns - 1) // columns
    width, height = columns * PITCH - 5, row_count * PITCH - 5
    scad = [
        "// Geometry reference only: use the companion 3MF to preserve exact recipes.",
        "// Mixed coupons are neutral grey here, NOT predicted or measured colours.",
        "// Sample IDs are in the layout and CSV; no text is printed in the optical area.",
    ]
    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="-5 -17 {width + 10} {height + 28}">',
        '<rect x="-5" y="-17" width="100%" height="100%" fill="white"/>',
        f'<text x="0" y="-10" font-family="sans-serif" font-size="4">{escape(name)} / view from +Z</text>',
        '<text x="0" y="-4" font-family="sans-serif" font-size="2.5">IDs only; colours are not predictions. Front is at the bottom.</text>',
    ]
    for index, coupon in enumerate(coupons):
        column, row = index % columns, index // columns
        x, y = column * PITCH, row * PITCH
        slots = tuple(i + 1 for i, value in enumerate(coupon.percents) if value)
        if coupon.sequence:
            strata = [(slot, i * ORDER_UNIT, ORDER_UNIT) for i, slot in enumerate(coupon.sequence)]
        else:
            if len(slots) == 1:
                extruder = slots[0]
            else:
                recipe = Recipe(slots, tuple(coupon.percents[slot - 1] for slot in slots))
                if recipe not in mixed_extruders:
                    mixed_extruders[recipe] = 5 + len(rows)
                    rows.append((recipe, len(rows) + 1))
                extruder = mixed_extruders[recipe]
            strata = [(extruder, 0.0, coupon.thickness)]
        label = "_".join(f"{FILAMENTS[i][0]}{value}" for i, value in enumerate(coupon.percents) if value)
        for layer, (extruder, z, thickness) in enumerate(strata):
            part_name = f"{coupon.sample_id}_{label}_{coupon.thickness:g}mm"
            if coupon.sequence:
                part_name += f"_block{layer + 1:02}_F{extruder}"
            parts.append(prism(len(parts) + 1, part_name, extruder, x, y, z, thickness))
            color = [v / 255 for v in BASE_COLORS[extruder - 1]] if extruder <= 4 else [0.5, 0.5, 0.5]
            scad.extend((
                f"// {part_name}",
                f"color({json.dumps(color)}) translate([{x}, {y}, {z:.6f}])",
                f"    linear_extrude(height={thickness:.6f}) polygon(points={json.dumps(POINTS)});",
            ))
        records.append({
            "sample_id": coupon.sample_id, "plate": name, "role": coupon.role,
            "column_from_left": column + 1, "row_from_front": row + 1,
            "C_percent": coupon.percents[0], "M_percent": coupon.percents[1],
            "Y_percent": coupon.percents[2], "N_percent": coupon.percents[3],
            "design_thickness_mm": coupon.thickness,
            "sequence_bottom_to_top": "/".join(map(str, coupon.sequence)) if coupon.sequence else "slicer_generated",
            "sequence_unit_mm": ORDER_UNIT if coupon.sequence else "",
        })
        polygon = " ".join(f"{x + px},{height - y - py}" for px, py in POINTS)
        svg.extend((
            f'<polygon points="{polygon}" fill="#EEEEEE" stroke="#444444" stroke-width="0.25"/>',
            f'<text x="{x + 10}" y="{height - y - 11}" text-anchor="middle" font-family="sans-serif" font-size="3.5">{coupon.sample_id}</text>',
            f'<text x="{x + 10}" y="{height - y - 5}" text-anchor="middle" font-family="sans-serif" font-size="2.5">{coupon.thickness:g} mm</text>',
        ))
    svg.append("</svg>")
    settings = dict(template)
    settings.update(PROCESS)
    if len({part.extruder for part in parts}) == 1 and not rows:
        settings["enable_prime_tower"] = "0"
    # Orca restores unmarked fields from the named system process on import.
    modified = list(settings["different_settings_to_system"])
    modified[0] = ";".join(sorted(set(modified[0].split(";")) | set(PROCESS) | {"enable_prime_tower"}))
    settings["different_settings_to_system"] = modified
    write_project(output / f"{name}.3mf", parts, settings, model_name=name,
                  base_colors=BASE_COLORS, definitions=encode_definitions(rows))
    (output / f"{name}.scad").write_text("\n".join(scad) + "\n", encoding="utf-8")
    (output / f"{name}-layout.svg").write_text("\n".join(svg) + "\n", encoding="utf-8")
    return records


def _write_i1pro2_sheet(output: Path, records: list[dict]) -> None:
    fields = [
        "reading_id", "sample_id", "mode", "repeat", "L_star", "a_star", "b_star",
        "spectral_file", "actual_thickness_mm", "face", "rotation_degrees",
        "print_run", "measurement_session", "measurement_condition", "illuminant",
        "observer", "backing_id", "instrument", "software", "instrument_serial",
        "measured_at", "plate", "role", "design_thickness_mm",
        "C_percent", "M_percent", "Y_percent", "N_percent", "notes",
    ]
    reference_fields = [
        "sample_id", "plate", "role", "design_thickness_mm",
        "C_percent", "M_percent", "Y_percent", "N_percent",
    ]
    with (output / "measurements-i1pro2.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for backing_id, backing_type, code in BACKINGS:
            for record in records:
                row = {field: record[field] for field in reference_fields}
                row.update({
                    "mode": f"{backing_type}_backing_reflection", "backing_id": backing_id,
                    "face": "top", "rotation_degrees": 0,
                    "illuminant": "D50", "observer": "1931_2", "instrument": "X-Rite i1Pro 2",
                })
                for repeat in range(1, 4):
                    row["reading_id"] = f"{record['sample_id']}-{code}-{repeat:02d}"
                    row["repeat"] = repeat
                    writer.writerow(row)


def _write_backing_sheets(output: Path) -> None:
    fields = [
        "backing_id", "backing_type", "material", "brand_or_source", "batch_or_lot",
        "sheet_count", "thickness_mm", "surface_finish", "used_face", "underlay", "notes",
    ]
    with (output / "backings.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for backing_id, backing_type, _ in BACKINGS:
            writer.writerow({"backing_id": backing_id, "backing_type": backing_type})

    fields = [
        "reading_id", "backing_id", "session_phase", "repeat",
        "L_star", "a_star", "b_star", "spectral_file", "measurement_session",
        "position", "rotation_degrees", "measurement_condition", "illuminant",
        "observer", "instrument", "software", "instrument_serial", "measured_at", "notes",
    ]
    with (output / "backing-references-i1pro2.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for backing_id, _, _ in BACKINGS:
            for phase in ("start", "end"):
                for repeat in range(1, 4):
                    writer.writerow({
                        "reading_id": f"{backing_id}-{phase.upper()}-{repeat:02d}",
                        "backing_id": backing_id, "session_phase": phase, "repeat": repeat,
                        "position": "reference", "rotation_degrees": 0,
                        "illuminant": "D50", "observer": "1931_2", "instrument": "X-Rite i1Pro 2",
                    })


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="new output directory; existing paths are refused")
    args = parser.parse_args(argv)
    template = load_settings_template(None)
    guide_path = Path(__file__).resolve().parents[1] / "templates" / "measurements-i1pro2-guide.txt"
    guide = guide_path.read_text(encoding="utf-8")
    try:
        args.output.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        parser.error(f"output already exists: {args.output}")
    records = []
    plates = coupons_by_plate()
    for name, coupons in plates.items():
        records.extend(write_plate(args.output, name, coupons, template))
    with (args.output / "samples.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)
    fields = [
        "sample_id", "mode", "print_run", "repeat", "face", "rotation_degrees",
        "actual_thickness_mm", "method", "illuminant", "observer", "geometry",
        "L_star", "a_star", "b_star", "rgb_space", "R", "G", "B",
        "capture_file", "spectral_file", "notes",
    ]
    with (args.output / "measurements.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for record in records:
            for mode in ("white_backing_reflection", "black_backing_reflection", "backlit_transmission"):
                writer.writerow({"sample_id": record["sample_id"], "mode": mode})
    _write_i1pro2_sheet(args.output, records)
    _write_backing_sheets(args.output)
    (args.output / "measurements-i1pro2-guide.txt").write_text(guide, encoding="utf-8")
    manifest = {
        "measurement_status": "unmeasured; blank CSV fields are for actual observations",
        "sources": SOURCES,
        "filaments": [
            {"slot": i + 1, "code": code, "name": name, "vendor_sku": sku,
             "display_hex": color, "vendor_scalar_td_mm": td, "spool_batch": None}
            for i, (code, name, sku, color, td) in enumerate(FILAMENTS)
        ],
        "printer_template": "bundled Snapmaker U1, 0.4 mm nozzle; verify printer and temperatures before printing",
        "process_overrides": PROCESS,
        "coupon_footprint_mm": [20, 20],
        "measurement_region": "central 10 x 10 mm; clipped front-left corner and edges excluded",
        "geometry_notes": "no backing, support, label text or coating inside the optical area; labels are not printed",
        "mix_recipe_notes": "requested ratios, not measured extrusion; inspect actual sliced layers and retain G-code",
        "layer_order_notes": "physical slots; each 0.16 mm block spans two nominal 0.08 mm layers except the first block",
        "holdout_notes": "do not fit mix-holdout samples; repeatability controls are not independent validation",
        "plates": {name: {"project": f"{name}.3mf", "samples": len(coupons)} for name, coupons in plates.items()},
    }
    (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Created {len(plates)} projects with {len(records)} unmeasured coupons in {args.output}")
    print("Physical slots: 1=Cyan, 2=Magenta, 3=Yellow, 4=Grey (N), not Black.")
    print("Open the 3MF files; SCAD and SVG are geometry/layout references, not colour predictions.")
    print("i1Pro 2: measurements-i1pro2.csv; protocol: measurements-i1pro2-guide.txt.")
    print("Backing controls: backings.csv; bare readings: backing-references-i1pro2.csv.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
