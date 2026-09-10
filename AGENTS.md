# Repository Guidelines

## Project Overview

`scad-fullspectrum` converts coloured OpenSCAD designs into Snapmaker Orca / FullSpectrum **project 3MF** files, assigning geometry to physical spools or computed filament blends. It is a local, standard-library-only Python CLI, not a slicer. The bundled workflow targets four-toolhead Snapmaker U1 projects.

## Architecture & Data Flow

Core modules live in `scad_fullspectrum/`:

1. `cli.py` resolves presets, JSON config, CLI overrides and a settings template, then constructs `BuildOptions` and calls `pipeline.build()`.
2. `pipeline.py` invokes OpenSCAD to flatten `.scad` into CSG. `csg.py` parses the tree and splits geometry by effective RGB colour; relative `import()`/`surface()` paths are made absolute before temporary-file rendering.
3. OpenSCAD renders each colour to STL; `mesh.py` reads binary/ASCII STL, deduplicates exact vertex coordinates and drops degenerate triangles.
4. `mixes.py` enumerates recipes once per plan, ranks predictions using `color.py`'s CIEDE2000 metric, shares identical recipes and optionally collapses mixes. Models are `average`, `pigment` and experimental `transmission`.
5. `threemf.py` writes the ZIP/XML project: root components in `3D/3dmodel.model`, meshes in `3D/Objects/<name>_1.model`, per-part extruders in `Metadata/model_settings.config`, and patched settings in `Metadata/project_settings.config`. `BuildReport` supplies the CLI summary and optional JSON report.

Preserve these contracts:

- CSG splitting is boolean-aware: retain difference cutters and intersection bounds; keep `hull()`/`minkowski()` atomic with inherited/first-colour attribution. Inner colour scopes win, alpha is ignored, and `%` background geometry is excluded.
- Physical slots are contiguous and 1-based. With `N` spools, the first virtual extruder is `N + 1`. `Recipe.encode()` is a slicer wire format: pair percentages describe the **second** slot; preserve custom/enabled flags and stable row IDs.
- After `max_mixes` collapse, reported blend/Delta E must describe the final assigned recipe, not the pre-merge suggestion.
- The writer replaces only `filament_colour`, existing `filament_multi_colors`, and `mixed_filament_definitions`; preserve all other supplied settings.

## Key Directories

- `scad_fullspectrum/`: conversion library and CLI; keep orchestration separate from colour math, CSG manipulation and serialization.
- `templates/`: printer/process settings snapshots, not generated build output.
- `tools/`: developer-only accuracy benchmark and pigment-table generator.
- `examples/`: tracked `.scad`/JSON inputs; `hue-wheel.scad` defaults to 12 colours, while README accuracy comparisons use `-D segments=60`.
- `tests/`: boundary-focused `unittest` modules; no separate fixture directory.

## Development Commands

Run from the repository root:

```sh
python3 -m scad_fullspectrum --help
./scad2fs3mf --list-presets
python3 -m scad_fullspectrum --print-example-config

# Build a project and inspect its colour-assignment report.
./scad2fs3mf examples/hue-wheel.scad -o /tmp/wheel.3mf \
  -c examples/hue-wheel.json --report /tmp/wheel.json

# Full suite, or one focused module.
python3 -m unittest discover -s tests
python3 -m unittest discover -s tests -p 'test_mixes.py' -v

# Optional accuracy sweep; substantially more work than the unit suite.
python3 tools/bench_mixes.py examples/hue-wheel.scad \
  --preset translucent-cmyg --models -D segments=60
```

Use unused output paths. `--keep-temp DIR` retains intermediate CSG/STL files; `-v` exposes OpenSCAD output. There is no separate package build/install workflow or configured lint, formatter, type-check or CI command; do not invent one.

## Code Conventions & Common Patterns

- Match existing four-space indentation, double-quoted strings, `snake_case` functions/modules, `PascalCase` classes and `UPPER_CASE` constants. Use postponed annotations, built-in generics and `X | None`; keep code, comments and documentation in English.
- Prefer typed dataclasses for data (`BuildOptions`, `BuildReport`, immutable `Recipe`) and functions for transformations. Keep `_`-prefixed helpers internal and maintain existing `__all__` exports.
- Dependencies and state are explicit arguments and per-build objects, not a DI container or application state store. OpenSCAD subprocesses run synchronously and sequentially; do not assume async execution.
- Preserve candidate reuse across target colours and cached pigment-pair terms; avoid rebuilding colour-independent search data for each target.
- Library validation/build failures use `ValueError`, `RuntimeError` or `OSError` subclasses. The CLI translates argument/config failures to exit 2 and caught build failures to exit 1; recoverable per-colour failures accumulate in `BuildReport.warnings`.
- Configuration precedence is preset < config file < explicit flags. `presets.merge()` overlays nested dictionaries one level and replaces lists; do not turn it into an arbitrary recursive merge. Preset retrieval returns copies.
- RGB values are integer triples; display hex is uppercase `#RRGGBB`. Treat `BuildReport` fields as the JSON output contract. Keep report-file writing before stdout printing so a broken pipe does not discard the report.

## Important Files

- `scad2fs3mf` and `scad_fullspectrum/__main__.py`: both call `cli.main()`. `scad_fullspectrum/__init__.py` exposes `BuildOptions`, `BuildReport`, `build` and the package version.
- `scad_fullspectrum/cli.py` and `presets.py`: config interpretation and built-in spool sets. Private CLI helpers are also imported by `tests/test_presets.py` and `tools/bench_mixes.py`; update those callers when refactoring.
- `templates/project_settings.config`: default four-spool Snapmaker U1, 0.4 mm nozzle, 0.08 mm process snapshot. A replacement template does **not** set placement dimensions: configure `printer.bed`/`--bed` too. Relative template paths resolve from the working directory, not the config file's directory.
- `scad_fullspectrum/_pigment_model.py`: generated; never hand-edit. Regenerate only with an external upstream header using `python3 tools/export_pigment_model.py path/to/FilamentMixerModel.hpp`; preserve attribution in `THIRD_PARTY_NOTICES.md`.
- `README.md` and `examples/hue-wheel.json`: user workflow/config references; keep them aligned with intentional CLI and model changes.

## Runtime/Tooling Preferences

Use `python3`; runtime and tests need no third-party Python packages or package manager. No minimum Python version is declared. Run from the checkout: the launcher adds its own directory to `sys.path`, while `python3 -m scad_fullspectrum` requires the package to be importable. Keep `templates/` alongside the package.

Conversion requires `openscad` on `PATH`, or an explicit `--openscad` executable. Generated `.3mf`, `.stl`, `.csg` and Python bytecode are ignored; JSON reports are not. Do not commit local output reports.

## Testing & QA

- Use stdlib `unittest`, `test_*.py` modules, `subTest` for related cases and `TemporaryDirectory` for I/O. Follow existing checkout import bootstrapping; avoid introducing pytest or external fixtures.
- `test_csg.py` covers parse/split semantics; `test_models.py` colour formulas; `test_mixes.py` recipe encoding/planning; `test_presets.py` presets/config; `test_project.py` ZIP/XML contracts and conversion.
- OpenSCAD integration classes in `test_project.py` and `test_presets.py` skip when `shutil.which("openscad")` fails. Check skipped counts before claiming end-to-end coverage. No coverage tool or percentage threshold is configured.
- Validate package contents and parsed XML/JSON rather than whole-archive hashes: generated UUIDs vary. Preserve domain-specific numerical tolerances and assertions that final assignments match encoded recipes.
- For CLI/template changes, also run the example conversion above: most tests use synthetic settings and bypass the actual CLI. For writer changes, inspect the result in the target slicer GUI; README documents a `normalize_fdm` crash in Snapmaker Orca CLI build `01.10.01.50`.
- `transmission` is uncalibrated and must remain labelled experimental in CLI/report output. Formula tests and benchmark Delta E are not proof of printed colour accuracy; physical claims require calibrated swatches.
