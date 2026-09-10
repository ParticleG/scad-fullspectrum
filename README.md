# scad-fullspectrum

Turn a coloured OpenSCAD file into a **Snapmaker Orca / FullSpectrum project 3MF**
in which every `color()` scope is printed as a blend of the filaments loaded in
the four toolheads.

```
./scad2fs3mf part.scad -o part.3mf -c spools.json
# or, from the repository root / with the package on PYTHONPATH:
python3 -m scad_fullspectrum part.scad -o part.3mf -c spools.json
```

The tool is dependency-free Python 3 (stdlib only) and needs the `openscad`
executable on `PATH`.

## What it does

1. `openscad -o model.csg model.scad` flattens the design. OpenSCAD's 3MF and AMF
   exporters throw colours away (3MF) or refuse multi-volume objects (AMF), but
   the CSG dump keeps every `color([r, g, b, a]) { ... }` scope.
2. The CSG tree is split per colour, one part per colour, honouring OpenSCAD's
   boolean semantics: the base of a `difference()` keeps its colour while the
   cutters are removed from every colour, `intersection()` keeps its bounding
   children, and `hull()`/`minkowski()` are attributed to the first colour inside
   them.
3. Each colour is matched against the loaded spools. A colour close to a spool
   (ΔE₀₀ ≤ `pure_threshold`) uses that spool directly; anything else becomes a
   mixed filament built from up to `components` spools on a `step`-percent grid.
   Recipes are ranked by CIEDE2000 against an sRGB weighted-average blend, which
   is the model the FullSpectrum fork uses for its mix preview.
4. The project is written with the same layout the slicer itself produces:
   `3D/3dmodel.model` (root object with one component per colour),
   `3D/Objects/<name>_1.model` (the meshes), `Metadata/model_settings.config`
   (one `<part>` per colour carrying its `extruder`) and
   `Metadata/project_settings.config` (spool colours, mix definitions and every
   other setting copied from a template project).

Virtual filament IDs start after the physical spools: with four spools, mix row
*k* is extruder `4 + k`, exactly the convention the slicer uses when it loads
`mixed_filament_definitions`.

## Configuration

```json
{
  "base_filaments": [
    { "slot": 1, "color": "#FF00FF", "name": "Magenta" },
    { "slot": 2, "color": "#00FFFF", "name": "Cyan" },
    { "slot": 3, "color": "#808080", "name": "Grey" },
    { "slot": 4, "color": "#FFFF00", "name": "Yellow" }
  ],
  "uncolored": 3,
  "mix": { "components": 2, "step": 5, "pure_threshold": 1.0, "max_mixes": null },
  "printer": { "bed": [270.0, 270.0] },
  "template": "templates/project_settings.config"
}
```

| Key | Meaning |
| --- | --- |
| `base_filaments` | the four spools actually loaded, in toolhead order; `color` is the filament's display colour |
| `uncolored` | what to do with geometry outside any `color()` scope: a hex colour or a slot index (default: drop it and warn) |
| `mix.components` | maximum filaments per recipe, 2–4 (default 2: fewest tool changes) |
| `mix.step` | percentage grid for candidate recipes (default 5 %) |
| `mix.pure_threshold` | ΔE₀₀ below which a spool is used as-is (default 1.0) |
| `mix.max_mixes` | cap on virtual filaments; the perceptually closest recipes are merged until the cap is met (the reported blend and ΔE always describe the recipe actually assigned) |
| `printer.bed` | build plate size; the model is centred on it |
| `template` | `project_settings.config` or a sliced `.3mf` whose settings are copied (printer, process, filament presets, wipe tower, …) |
| `settings` | arbitrary overrides merged into `Metadata/project_settings.config` |

`python3 -m scad_fullspectrum --print-example-config` prints the skeleton, and
`--help` lists the flags that override the config (`--components`, `--max-mixes`,
`--template`, `--uncolored`, …).

### Template project

`templates/project_settings.config` is a full Snapmaker U1 settings snapshot, so
a generated file opens with the U1 printer, the "0.08 High Quality" process and
four PLA filaments. To inherit your own preset instead, pass a project you saved
from the slicer:

```
python3 -m scad_fullspectrum part.scad -o part.3mf -c spools.json --template my-project.3mf
```

## Examples

```
python3 -m scad_fullspectrum examples/hue-wheel.scad \
    -o /tmp/hue-wheel.3mf -c examples/hue-wheel.json --report /tmp/hue-wheel.json
```

The report lists, for every source colour, the chosen extruder, the recipe, the
predicted blend and its ΔE₀₀.

## Caveats

* Alpha in `color([r, g, b, a])` is ignored - the printer is opaque.
* `hull()`/`minkowski()` of several colours cannot be split meaningfully; the
  whole hull is printed in the first colour found inside it.
* Every colour becomes a part with its own extruder, so a hundred-colour design
  means a hundred virtual filaments and a lot of tool changes. Use
  `mix.max_mixes` to merge similar colours.
* Mixing is optical: thin alternating layers of two filaments. A blend of two
  saturated filaments is always duller than either spool (mixing cannot reach a
  pure hue outside the spools' gamut), and the printed colour depends on the
  filaments' opacity (TD), temperature and speed. Start with the 0.08 mm process
  the template ships, and consider printing a swatch to calibrate.
* The snapmaker-orca **CLI** of build `01.10.01.50` crashes (`normalize_fdm`) when
  it loads 3MF projects, so slice from the GUI.

## Tests

```
python3 -m unittest discover -s tests
```

The suite covers the CSG parser/splitter (nested scopes, cutters, hulls,
background/root modifiers), the row encoding, the solver/planning rules and the
generated package (structure, extruders, patched settings, plate centring); the
pipeline test runs OpenSCAD when it is installed.
