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
   Recipes are ranked by CIEDE2000 against the blend predicted by the selected
   mix model (`average`, `pigment` or `transmission`, see below).
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
  "mix": { "components": 2, "step": 5, "pure_threshold": 1.0, "max_mixes": null, "model": "average" },
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
| `mix.model` | blend model used for search and prediction: `average`, `pigment` or `transmission` (default `average`; see [Blend models](#blend-models)) |
| `printer.bed` | build plate size; the model is centred on it |
| `template` | `project_settings.config` or a sliced `.3mf` whose settings are copied (printer, process, filament presets, wipe tower, …) |
| `settings` | arbitrary overrides merged into `Metadata/project_settings.config` |

### Presets

Spool sets ship with the tool, so no config file is needed to start:

```
./scad2fs3mf --list-presets
./scad2fs3mf part.scad -o part.3mf --preset translucent-cmyg
```

| preset | spools (slot 1-4) | model |
| --- | --- | --- |
| `translucent-cmyg` | translucent cyan, magenta, yellow, grey | `transmission` (experimental) |
| `pla-cmyk` | cyan, magenta, yellow, black | `pigment` |
| `pla-cmyw` | cyan, magenta, yellow, white | `pigment` |
| `pla-cmyg` | cyan, magenta, yellow, grey | `pigment` |
| `pla-rybw` | red, yellow, blue, white | `pigment` |

Colours are idealised placeholders: measure your own spools and replace them.

**Overriding a preset.** Precedence is preset < config file < explicit flags, and
a config file replaces the keys it mentions: `base_filaments` is a list, so a
file that carries its own spools *replaces the preset's spools and slot mapping*,
while a key the file omits stays from the preset, and `mix` merges key by key.
To keep a preset's spools and only change the model, use the flag or a minimal
file:

```
./scad2fs3mf part.scad -o part.3mf --preset pla-cmyk --mix-model average
echo '{"mix": {"model": "average"}}' > model-only.json
./scad2fs3mf part.scad -o part.3mf --preset pla-cmyk -c model-only.json
```

Giving the spools from a file (or `-c` with a preset name instead of `--preset`)
is equally valid - just be aware the file's four entries win:

```
./scad2fs3mf part.scad -o part.3mf --preset pla-cmyk -c my-spools.json
./scad2fs3mf part.scad -o part.3mf -c pla-rybw
```

`python3 -m scad_fullspectrum --print-example-config` prints the skeleton, and
`--help` lists the flags that override the config (`--components`, `--max-mixes`,
`--mix-model`, `--template`, `--uncolored`, …). Parameterised designs take
OpenSCAD defines directly:

```
python3 -m scad_fullspectrum examples/hue-wheel.scad -o wheel.3mf \
    -c examples/hue-wheel.json -D segments=60
```

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
# built-in preset
./scad2fs3mf examples/hue-wheel.scad -o /tmp/wheel.3mf --preset pla-cmyw

# or a config file (examples/hue-wheel.json documents the file format)
./scad2fs3mf examples/hue-wheel.scad -o /tmp/wheel.3mf \
    -c examples/hue-wheel.json --report /tmp/wheel.json
```

The report lists, for every source colour, the chosen extruder, the recipe, the
predicted blend and its ΔE₀₀.

## Accuracy
Every ΔE₀₀ in the report and the CLI summary is a **model prediction**: it
compares a source colour with the blend the *selected model* computes for the
recipe, not a measurement of the printed part. The CLI prints a summary of it
(median, worst, how many colours are predicted above ΔE 10) and `--report`
carries the per-colour detail.

`--mix-model`, `--step` and `--components` widen or correct that search space.
The table below runs the 60-colour hue wheel through the shipped example (spool
colours are the idealised `#00FF…` values, see the caveat at the end of this
section):

| setting | mixes | median ΔE | worst ΔE | predicted > ΔE 10 |
| --- | --- | --- | --- | --- | --- |
| `average`, `--step 5` (default) | 40 | 6.4 | 22.1 | 20/60 |
| `average`, `--step 1` | 49 | 6.2 | 22.1 | 20/60 |
| `pigment`, `--step 5` | 42 | 4.0 | 21.2 | 19/60 |
| `pigment`, `--components 3 --step 1` | 50 | 3.8 | 21.2 | 19/60 |
| `transmission` (experimental), `--step 5` | 42 | 1.2 | 8.0 | 0/60 |
| `transmission` (experimental), `--step 1` | 57 | 0.3 | 1.6 | 0/60 |

The `transmission` rows only say that the wheel is reachable *inside that
formula*: the model is uncalibrated (see below), so they are **not** evidence
that these spools print the wheel. Only the `average` and `pigment` rows compare
against a model whose behaviour has an external reference.

Reproduce these with the shipped example:

```
./tools/bench_mixes.py examples/hue-wheel.scad --preset translucent-cmyg \
    --models -D segments=60
```


* `--step 1` barely moves accuracy for a saturated hue wheel under the opaque
  models (4 of 60 colours improve by more than ΔE 0.5) - it mainly stops
  neighbouring colours from collapsing onto the same 5 % grid point (colours
  sharing a slot: 17 → 8).
* `--components 3` gives no measurable gain on saturated hues, but is decisive
  for muted ones (`#B0B0B0` 14.9 → 2.2, `#93A9D1` 9.7 → 1.8 under the opaque
  models). Three-component rows load and display correctly in Snapmaker Orca
  2.3.6; that verifies parsing and display, not the blend arithmetic.
* `--max-mixes N` merges the closest recipes; use it to cut tool changes, never
  to improve colour.

`tools/bench_mixes.py part.scad spools.json --models` runs one design through
every model/component/step combination and prints the same table.

Two claims that are easy to get wrong, and what the measurements actually say:

* *Palette limits* - under the **opaque** models magenta/cyan/yellow/grey cannot
  reach a saturated red or blue (ΔE 13-22 there), because an opaque blend stays
  inside the colour hull of the spools. Whether translucent spools do better is a
  question about the printed part: the experimental `transmission` mode suggests
  the direction (stacked translucent layers filter light instead of averaging
  with it) but cannot answer it, and nothing here was checked against a print.
* *Four-component mixes* - with four spools the hull is a non-degenerate
  tetrahedron (`#808080` is not on the magenta/cyan/yellow plane), so 2- and
  3-component recipes reach only its edges and faces, and interior colours need
  all four. On the measured wheel this never mattered (saturated hues sit on the
  hull surface, so triples and quads never beat pairs there); do not generalise
  it to muted or desaturated designs.

Put the spools' *measured* hex values into `base_filaments` - the idealised
`#00FFFF`-style values make the prediction optimistic.

## Blend models

| model | what it assumes | use it for |
| --- | --- | --- |
| `average` | weighted average in sRGB space | opaque filaments, quick runs; conservative for saturated results |
| `pigment` | the slicers' degree-4 pigment polynomial (`FilamentMixerModel.hpp`, MIT) | predicting the swatch the slicer draws: two swatches sampled from Snapmaker Orca 2.3.6 for recipes this tool wrote are reproduced within 2/255 per channel, one byte-exact |
| `transmission` (**experimental**) | that the entered display hex values are transmittances of "one layer", that the substrate is a white backer, and that a zero channel behaves like `1e-6` | making the *direction* of subtractive mixing visible while searching recipes; never as a colour guarantee |

`transmission` has no reference thickness, no measured absorption data and no
illumination model, so its ΔE compares the formula with itself. Calibrate it by
printing mixture swatches before trusting any of its numbers; the CLI prints a
warning and `--report` marks the run as experimental.

None of the models is a physical measurement: layer height, opacity (TD),
purging, surface finish, the substrate and the viewing light all shift the
printed result.

## Translucent spools

Translucent filaments filter light instead of covering it, so the opaque mental
model ("average the colours") does not apply. What this tool can and cannot tell
you:

* It can order recipes and show which direction a stack shifts the hue.
* It cannot predict the printed colour: no absorption spectra, no reference
  thickness, no substrate and no illumination model. `mix.model:
  "transmission"` is experimental - calibrate it with printed swatches.

Calibrate, in the viewing mode the part is for:

1. **Reflective viewing** (lit from the viewer's side): print each *pure*
   filament as a patch of a few layers (3-5, at your working layer height) over
   the same backing the part will have, read the patches with a colorimeter or a
   locked-off camera, and put those hex values into `base_filaments`. Then print
   a small grid of *mixture* swatches - each patch a stack with the recipe the
   tool reports (`--report` lists them) - at the same thickness and backing, and
   compare. Adjust `mix.step`/`mix.components` and the spool hexes until the tool
   agrees with the grid.
2. **Transmissive / backlit viewing** (thin walls, lampshades, diffusers - a
   documented use of translucent PLA): the part is judged by the light passing
   through it, so calibrate against backlight, not against a backer. Print the
   same swatch grid as thin walls and compare it lit from behind; a reflective
   white backing would defeat this mode, so do not force one here.

Practical notes that hold in both modes:

* The colour comes from the *stack*: alternating thin layers (0.08-0.12 mm) of
  different filaments behave like a single filter, which is the same mechanism
  the FullSpectrum cadence uses.
* Grey is a neutral-density filter - it darkens and desaturates. Keep it out of
  saturated mixes; if you mostly print bright or pastel reflective pieces, an
  opaque white spool is worth a slot (it also serves as a backer). Swapping is a
  choice, not a rule.
* Colour deepens with total thickness; thicker shells and more layers saturate.
* Purge/prime towers and travel moves leave translucent smears more visibly than
  opaque ones - keep wiping parameters generous.
## Caveats

* Alpha in `color([r, g, b, a])` is ignored - the printer is opaque.
* `hull()`/`minkowski()` of several colours cannot be split meaningfully; the
  whole hull is printed in the first colour found inside it.
* Every colour becomes a part with its own extruder, so a hundred-colour design
  means a hundred virtual filaments and a lot of tool changes. Use
  `mix.max_mixes` to merge similar colours.
* Mixing is optical: thin alternating layers of filaments. What the tool reports
  is a model prediction - the printed colour also depends on the filaments'
  opacity (TD), layer height, temperature, speed and the base under the colour.
  Start with the 0.08 mm process the template ships, and print a swatch to
  calibrate before committing to a large piece.
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
