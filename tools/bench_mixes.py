#!/usr/bin/env python3
"""Compare mix accuracy settings for one design.

Renders the same SCAD with different ``--components``/``--step`` combinations and
prints how the choice affects colour accuracy (median/worst ΔE₀₀), the number of
virtual filaments and how many source colours end up sharing a slot.

    tools/bench_mixes.py part.scad spools.json [--config-template project.3mf]
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scad_fullspectrum.cli import _base_colors, _resolve_config, load_settings_template  # noqa: E402
from scad_fullspectrum.color import EXPERIMENTAL_MODELS, MIX_MODELS  # noqa: E402
from scad_fullspectrum.pipeline import BuildOptions, build  # noqa: E402

CASES = [
    ("components=2 step=5", 2, 5),
    ("components=2 step=1", 2, 1),
    ("components=3 step=5", 3, 5),
    ("components=3 step=1", 3, 1),
    ("components=4 step=5", 4, 5),
    ("components=4 step=1", 4, 1),
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scad")
    parser.add_argument("config", nargs="?", help="config file or preset name")
    parser.add_argument("--preset", help="built-in spool preset")
    parser.add_argument("--template", help="project settings source (project_settings.config or .3mf)")
    parser.add_argument("--pure-threshold", type=float, default=1.0)
    parser.add_argument("--models", action="store_true", help="sweep every blend model as well")
    parser.add_argument(
        "-D", "--define", action="append", default=[], metavar="KEY=VALUE", help="OpenSCAD parameter (repeatable)"
    )
    args = parser.parse_args(argv)

    config = _resolve_config(args.config, args.preset)
    colors, _ = _base_colors(config)
    settings = load_settings_template(Path(args.template) if args.template else None)

    cases: list[tuple[str, int, int, str]] = []
    if args.models:
        for model in MIX_MODELS:
            tag = f"{model} (experimental)" if model in EXPERIMENTAL_MODELS else model
            for label, components, step in CASES:
                cases.append((f"{tag} {label}", components, step, model))
    else:
        default_model = (config.get("mix") or {}).get("model", "average")
        for label, components, step in CASES:
            cases.append((f"{default_model} {label}", components, step, default_model))

    header = f"{'setting':<34}{'mixes':>6}{'slots':>6}{'shared':>7}{'med dE':>8}{'max dE':>8}{'>10':>5}{'sec':>7}"
    print(header)
    print("-" * len(header))
    for label, components, step, model in cases:
        with TemporaryDirectory() as tmp:
            options = BuildOptions(
                base_colors=colors,
                physical_count=len(colors),
                components=components,
                step=step,
                pure_threshold=args.pure_threshold,
                mix_model=model,
                defines=list(args.define),
            )
            started = time.time()
            try:
                report = build(args.scad, Path(tmp) / "bench.3mf", options, dict(settings))
            except RuntimeError as error:
                print(f"{label:<34}  failed: {error}")
                continue
            elapsed = time.time() - started
        summary = report.summary
        print(
            f"{label:<34}{summary['mixes']:>6}{summary['extruders_used']:>6}{summary['shared_slots']:>7}"
            f"{summary['median_delta_e']:>8.1f}{summary['max_delta_e']:>8.1f}"
            f"{summary['delta_e_over_10']:>5}{elapsed:>7.1f}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
