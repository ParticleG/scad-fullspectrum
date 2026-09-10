"""Command line front end for the SCAD -> FullSpectrum 3MF converter."""

from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path

from .color import RGB, hex_to_rgb
from .pipeline import BuildOptions, build

__all__ = ["main"]

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TEMPLATE = PACKAGE_ROOT / "templates" / "project_settings.config"

_EXAMPLE_CONFIG = {
    "base_filaments": [
        {"slot": 1, "color": "#FF00FF", "name": "Magenta"},
        {"slot": 2, "color": "#00FFFF", "name": "Cyan"},
        {"slot": 3, "color": "#808080", "name": "Grey"},
        {"slot": 4, "color": "#FFFF00", "name": "Yellow"},
    ],
    "uncolored": None,
    "mix": {"components": 2, "step": 5, "pure_threshold": 1.0, "max_mixes": None},
    "printer": {"bed": [270.0, 270.0]},
}


def load_config(path: str | None) -> dict:
    if path is None:
        return {}
    data = json.loads(Path(path).read_text())
    if not isinstance(data, dict):
        raise ValueError(f"{path}: the config must be a JSON object")
    return data


def load_settings_template(path: Path | None) -> dict:
    """Read a project settings JSON, either raw or from inside a project 3MF."""

    template = path or DEFAULT_TEMPLATE
    if not template.is_file():
        raise FileNotFoundError(
            f"project settings template not found: {template}\n"
            "pass --template with a project_settings.config or a sliced .3mf file"
        )
    if template.suffix.lower() == ".3mf":
        with zipfile.ZipFile(template) as archive:
            with archive.open("Metadata/project_settings.config") as handle:
                return json.load(handle)
    return json.loads(template.read_text())


def _base_colors(config: dict) -> tuple[list[RGB], list[str]]:
    entries = config.get("base_filaments")
    if not entries:
        raise ValueError(
            "no base_filaments in the config; add four entries like "
            '{"slot": 1, "color": "#FF00FF", "name": "Magenta"}'
        )
    entries = sorted(entries, key=lambda item: item.get("slot", 0))
    colors: list[RGB] = []
    names: list[str] = []
    for index, entry in enumerate(entries, start=1):
        slot = entry.get("slot", index)
        if slot != index:
            raise ValueError(f"base_filaments slots must be 1..{len(entries)}, got {slot}")
        colors.append(hex_to_rgb(entry["color"]))
        names.append(entry.get("name") or f"F{slot}")
    return colors, names


def _resolve_uncolored(value: object, colors: list[RGB]) -> RGB | None:
    if value is None:
        return None
    if isinstance(value, int):
        if not 1 <= value <= len(colors):
            raise ValueError(f"uncolored slot {value} is outside 1..{len(colors)}")
        return colors[value - 1]
    if isinstance(value, str):
        if value.startswith("#") or len(value) in {3, 6}:
            return hex_to_rgb(value)
        raise ValueError(f"uncolored must be a hex colour or a slot index, got {value!r}")
    raise ValueError(f"uncolored must be a hex colour or a slot index, got {value!r}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scad2fs3mf",
        description=(
            "Convert an OpenSCAD file whose parts are tagged with color() into a "
            "Snapmaker Orca / FullSpectrum project 3MF whose colours are printed "
            "as blends of the loaded filaments."
        ),
        epilog=(
            "config keys: base_filaments[{slot,color,name}], uncolored, template, "
            "mix{components,step,pure_threshold,max_mixes}, printer{bed}, openscad, settings"
        ),
    )
    parser.add_argument("scad", nargs="?", help="input .scad file")
    parser.add_argument("-o", "--output", help="output .3mf project file")
    parser.add_argument("-c", "--config", help="JSON config with the loaded filaments")
    parser.add_argument("--template", help="project_settings.config or .3mf project to copy settings from")
    parser.add_argument("--uncolored", help="filament for uncolored geometry: #RRGGBB or slot index")
    parser.add_argument("--components", type=int, choices=(1, 2, 3, 4), help="max filaments per mix")
    parser.add_argument("--step", type=int, help="percentage grid for mix candidates (default 5)")
    parser.add_argument("--pure-threshold", type=float, help="ΔE within which a spool is used as is")
    parser.add_argument("--max-mixes", type=int, help="cap the number of mixed filaments")
    parser.add_argument("--bed", help="build plate size in mm, e.g. 270x270")
    parser.add_argument("--openscad", help="openscad executable (default: openscad)")
    parser.add_argument("--report", help="write a JSON report next to the project")
    parser.add_argument("--keep-temp", help="keep intermediate CSG/STL files in this directory")
    parser.add_argument("--print-example-config", action="store_true", help="print a sample config and exit")
    parser.add_argument("-v", "--verbose", action="store_true", help="show OpenSCAD output")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.print_example_config:
        print(json.dumps(_EXAMPLE_CONFIG, indent=2))
        return 0

    if not args.scad or not args.output:
        parser.error("the SCAD file and -o/--output are required")

    try:
        config = load_config(args.config)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        parser.error(str(error))
        return 2

    try:
        colors, names = _base_colors(config)
    except (KeyError, ValueError) as error:
        parser.error(f"{error}\n\nhint: run with --print-example-config to see the expected shape")
        return 2

    mix = dict(config.get("mix") or {})
    printer = dict(config.get("printer") or {})

    uncolored_value = args.uncolored if args.uncolored is not None else config.get("uncolored")
    if isinstance(uncolored_value, str) and uncolored_value.isdigit():
        uncolored_value = int(uncolored_value)
    try:
        uncolored = _resolve_uncolored(uncolored_value, colors)
    except ValueError as error:
        parser.error(str(error))
        return 2

    bed = printer.get("bed", [270.0, 270.0])
    if args.bed:
        try:
            width, height = args.bed.lower().split("x")
            bed = [float(width), float(height)]
        except ValueError:
            parser.error("--bed expects WIDTHxHEIGHT, e.g. 270x270")
            return 2

    template_path = Path(args.template) if args.template else config.get("template")
    try:
        settings = load_settings_template(Path(template_path) if template_path else None)
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        parser.error(f"cannot read project settings: {error}")
        return 2
    settings.update(config.get("settings") or {})

    options = BuildOptions(
        base_colors=colors,
        base_names=names,
        uncolored=uncolored,
        physical_count=len(colors),
        components=args.components or int(mix.get("components", 2)),
        step=args.step or int(mix.get("step", 5)),
        pure_threshold=(
            args.pure_threshold if args.pure_threshold is not None else float(mix.get("pure_threshold", 1.0))
        ),
        max_mixes=args.max_mixes if args.max_mixes is not None else mix.get("max_mixes"),
        openscad=args.openscad or config.get("openscad", "openscad"),
        bed=(float(bed[0]), float(bed[1])),
        keep_temp=Path(args.keep_temp).resolve() if args.keep_temp else None,
        verbose=args.verbose,
    )

    try:
        report = build(args.scad, args.output, options, settings)
    except (RuntimeError, OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    try:
        _print_report(report, names)
    except BrokenPipeError:  # e.g. ``... | head``
        return 0
    if args.report:
        Path(args.report).write_text(report.to_json())
    return 0


def _print_report(report, names: list[str]) -> None:
    print(f"project : {report.output}")
    print(f"parts   : {len(report.parts)}  triangles: {report.triangles}")
    if report.colors:
        print("\ncolour      extruder  filament mix")
        for entry in report.colors:
            print(
                f"  {entry['source']}  T{entry['extruder']:<3}      {entry['recipe']}"
                f"  -> {entry['blend']}  ΔE {entry['delta_e']:.1f}"
            )
    if report.rows:
        print("\nmixed filaments:")
        for row in report.rows:
            print(f"  T{row['extruder']:<3} {row['row']}")
    for warning in report.warnings:
        print(f"warning: {warning}", file=sys.stderr)
