"""End-to-end pipeline: SCAD -> per-colour meshes -> FullSpectrum 3MF project."""

from __future__ import annotations

import json
import shutil
import statistics
import subprocess
import tempfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from . import csg
from .color import EXPERIMENTAL_MODELS, RGB, rgb_to_hex
from .mesh import read_stl
from .mixes import encode_definitions, plan
from .threemf import Part, write_project

__all__ = ["BuildOptions", "BuildReport", "build"]


@dataclass
class BuildOptions:
    """Everything the pipeline needs besides the SCAD file itself."""

    base_colors: list[RGB]
    base_names: list[str] = field(default_factory=list)
    uncolored: RGB | None = None
    physical_count: int = 4
    components: int = 4
    step: int = 5
    pure_threshold: float = 1.0
    max_mixes: int | None = None
    mix_model: str = "average"
    openscad: str = "openscad"
    defines: list[str] = field(default_factory=list)
    bed: tuple[float, float] = (270.0, 270.0)
    keep_temp: Path | None = None
    verbose: bool = False


@dataclass
class BuildReport:
    scad: str
    output: str
    parts: list[dict] = field(default_factory=list)
    colors: list[dict] = field(default_factory=list)
    rows: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    triangles: int = 0
    mix_model: str = "average"
    mix_model_experimental: bool = False
    summary: dict = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(self.__dict__, indent=2, ensure_ascii=False)


def _run(command: Sequence[str]) -> subprocess.CompletedProcess:
    return subprocess.run(list(command), capture_output=True, text=True, check=False)


def _openscad_command(options: BuildOptions, output: Path, source: Path) -> list[str]:
    command = [options.openscad, "-o", str(output)]
    for define in options.defines:
        command += ["-D", define]
    return command + [str(source)]


def _resolve_imports(nodes: list[csg.Node], base_dir: Path) -> None:
    """Rewrite relative ``import()``/``surface()`` paths against the SCAD folder.

    Per-colour CSG files are rendered from a temporary directory, where a
    relative path recorded by OpenSCAD would no longer resolve.
    """

    for node in nodes:
        if node.name in {"import", "surface"}:
            args = list(node.args)
            if args and args[0][0] is None and isinstance(args[0][1], str):
                value = Path(args[0][1])
                if not value.is_absolute():
                    args[0] = (None, str((base_dir / value).resolve()))
                    node.args = args
        if node.children:
            _resolve_imports(node.children, base_dir)


def _has_uncolored(nodes: list[csg.Node], inherited: RGB | None = None) -> bool:
    for node in nodes:
        if node.modifier == "%":
            continue
        current = csg.color_of(node) or inherited
        if node.children is None:
            if current is None:
                return True
            continue
        if _has_uncolored(node.children, current):
            return True
    return False


def _collect_targets(tree: list[csg.Node]) -> list[RGB | None]:
    targets: list[RGB | None] = []
    seen: set[RGB | None] = set()
    for color in csg.iter_colors(tree):
        if color not in seen:
            seen.add(color)
            targets.append(color)
    if _has_uncolored(tree):
        targets.append(None)
    return targets


def _summarise(report: BuildReport, parts: Sequence[Part], rows: Sequence[tuple], physical: int) -> dict:
    """Colour-matching and filament-count statistics for the CLI/report.

    ``delta_e_over_10`` counts colours whose *predicted* match error is above 10;
    it says nothing about whether the colour is inside the spools' gamut.
    """

    delta_e = [entry["delta_e"] for entry in report.colors]
    slot_usage = Counter(entry["extruder"] for entry in report.colors)
    return {
        "parts": len(parts),
        "triangles": report.triangles,
        "physical_filaments": physical,
        "mixes": len(rows),
        "extruders_used": len(slot_usage),
        "shared_slots": sum(count - 1 for count in slot_usage.values() if count > 1),
        "median_delta_e": round(statistics.median(delta_e), 2) if delta_e else 0.0,
        "max_delta_e": round(max(delta_e), 2) if delta_e else 0.0,
        "delta_e_over_10": sum(1 for value in delta_e if value > 10.0),
    }


def build(
    scad_path: str | Path,
    output_path: str | Path,
    options: BuildOptions,
    settings: dict,
) -> BuildReport:
    """Run the whole conversion and return a report of what was produced."""

    scad_path = Path(scad_path).resolve()
    output_path = Path(output_path).resolve()
    if not scad_path.is_file():
        raise FileNotFoundError(f"SCAD file not found: {scad_path}")

    report = BuildReport(
        scad=str(scad_path),
        output=str(output_path),
        mix_model=options.mix_model,
        mix_model_experimental=options.mix_model in EXPERIMENTAL_MODELS,
    )
    temp_root = options.keep_temp or Path(tempfile.mkdtemp(prefix="scad-fullspectrum-"))
    temp_root.mkdir(parents=True, exist_ok=True)

    try:
        dump_path = temp_root / f"{scad_path.stem}.csg"
        result = _run(_openscad_command(options, dump_path, scad_path))
        if options.verbose and result.stdout.strip():
            print(result.stdout.strip())
        if not dump_path.is_file():
            detail = result.stderr.strip() or result.stdout.strip() or "no output"
            raise RuntimeError(f"OpenSCAD did not produce a CSG dump: {detail}")

        tree = csg.select_root(csg.parse(dump_path.read_text()))
        _resolve_imports(tree, scad_path.parent)

        targets = _collect_targets(tree)
        if targets == [None] and options.uncolored is None:
            raise RuntimeError(
                "the design has no color() scopes; set \"uncolored\" in the config to print it"
            )
        if None in targets and options.uncolored is None:
            report.warnings.append(
                "uncolored geometry is not assigned to a filament and was dropped; "
                'set "uncolored" in the config (a colour or a slot index) to keep it'
            )

        # Render every colour scope first: colours that end up producing no
        # geometry (cutters, empty intersections) must not consume a virtual
        # filament slot.
        rendered: list[tuple[RGB | None, str, list, list]] = []
        for index, target in enumerate(targets, start=1):
            if target is None and options.uncolored is None:
                continue
            statements = csg.split_for_color(tree, target)
            if not statements:
                continue
            label = "uncolored" if target is None else rgb_to_hex(target)
            csg_path = temp_root / f"part_{index:03d}.csg"
            stl_path = temp_root / f"part_{index:03d}.stl"
            csg_path.write_text(csg.dump(statements) + "\n")
            render = _run(_openscad_command(options, stl_path, csg_path))
            if not stl_path.is_file() or stl_path.stat().st_size == 0:
                detail = render.stderr.strip().splitlines()[-1] if render.stderr.strip() else "no mesh"
                report.warnings.append(f"{label}: OpenSCAD produced nothing ({detail})")
                continue
            vertices, triangles = read_stl(stl_path)
            if not triangles:
                report.warnings.append(f"{label}: mesh has no triangles")
                continue
            rendered.append((target, label, vertices, triangles))

        if not rendered:
            raise RuntimeError("no printable geometry was produced from the SCAD file")

        mix_colors = [target for target, _, _, _ in rendered if target is not None]
        if any(target is None for target, _, _, _ in rendered):
            mix_colors.append(options.uncolored)
        plan_result = plan(
            mix_colors,
            options.base_colors,
            components=options.components,
            step=options.step,
            pure_threshold=options.pure_threshold,
            max_mixes=options.max_mixes,
            model=options.mix_model,
        )

        parts: list[Part] = []
        for part_id, (target, label, vertices, triangles) in enumerate(rendered, start=1):
            color = target if target is not None else options.uncolored
            extruder = plan_result.extruder_of(color)
            parts.append(
                Part(id=part_id, name=label, extruder=extruder, vertices=vertices, triangles=triangles)
            )
            plan_result.assignments[color].parts.append(label)
            report.parts.append(
                {"id": part_id, "name": label, "extruder": extruder, "triangles": len(triangles)}
            )
            report.triangles += len(triangles)

        rows = list(plan_result.rows)
        definitions = encode_definitions(rows)
        report.rows = [
            {
                "stable_id": stable_id,
                "extruder": options.physical_count + index + 1,
                "slots": list(recipe.slots),
                "percents": list(recipe.percents),
                "row": recipe.encode(stable_id),
            }
            for index, (recipe, stable_id) in enumerate(rows)
        ]
        report.colors = [
            {
                "source": rgb_to_hex(assignment.target),
                "extruder": assignment.extruder,
                "recipe": assignment.label(),
                "blend": rgb_to_hex(assignment.blend),
                "delta_e": round(assignment.delta_e, 2),
                "parts": len(assignment.parts),
            }
            for _, assignment in sorted(plan_result.assignments.items(), key=lambda item: item[1].extruder)
            if assignment.parts
        ]
        report.summary = _summarise(report, parts, rows, options.physical_count)

        write_project(
            output_path,
            parts,
            settings,
            model_name=scad_path.stem,
            base_colors=options.base_colors,
            definitions=definitions,
            bed_center=(options.bed[0] / 2.0, options.bed[1] / 2.0),
        )
        return report
    finally:
        if options.keep_temp is None and temp_root.exists():
            shutil.rmtree(temp_root, ignore_errors=True)
