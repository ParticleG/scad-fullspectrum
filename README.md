# scad-fullspectrum

English | [简体中文](README.zh-CN.md)

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
  "mix": { "components": 4, "step": 5, "pure_threshold": 1.0, "max_mixes": null, "model": "average" },
  "printer": { "bed": [270.0, 270.0] },
  "template": "templates/project_settings.config"
}
```

| Key | Meaning |
| --- | --- |
| `base_filaments` | the four spools actually loaded, in toolhead order; `color` is the filament's display colour |
| `uncolored` | what to do with geometry outside any `color()` scope: a hex colour or a slot index (default: drop it and warn) |
| `mix.components` | maximum filaments per recipe, 2–4 (default 4, including when the field is omitted) |
| `mix.step` | percentage grid for candidate recipes (default 5 %) |
| `mix.pure_threshold` | ΔE₀₀ below which a spool is used as-is (default 1.0) |
| `mix.max_mixes` | cap on virtual filaments; the perceptually closest recipes are merged until the cap is met (the reported blend and ΔE always describe the recipe actually assigned) |
| `mix.model` | blend model used for search and prediction: `average`, `pigment` or `transmission` (default `average`; see [Blend models](#blend-models)) |
| `printer.bed` | build plate size; the model is centred on it |
| `template` | `project_settings.config` or a sliced `.3mf` whose settings are copied (printer, process, filament presets, wipe tower, …) |
| `settings` | arbitrary overrides merged into `Metadata/project_settings.config` |

All built-in presets allow up to four components. A config that omits
`mix.components` (or the entire `mix` object) also defaults to four; explicit
config values and `--components` still take precedence. This is an upper limit,
not a requirement to use all four spools: simpler recipes can still win.
Four-component searches, especially with `--step 1`, cost more time and can
increase tool changes. Use `--components 2` or `3` when that trade-off is preferable.

### Presets

Spool sets ship with the tool, so no config file is needed to start:

```
./scad2fs3mf --list-presets
./scad2fs3mf part.scad -o part.3mf --preset translucent-cmyn
```

| preset | slot codes (1-4) | spools | model |
| --- | --- | --- | --- |
| `translucent-cmyn` | C M Y N | translucent cyan, magenta, yellow, neutral grey | `transmission` (experimental) |
| `pla-cmyk` | C M Y K | cyan, magenta, yellow, black | `pigment` |
| `pla-cmyw` | C M Y W | cyan, magenta, yellow, white | `pigment` |
| `pla-cmyn` | C M Y N | cyan, magenta, yellow, neutral grey | `pigment` |
| `pla-rybw` | R Y B W | red, yellow, blue, white | `pigment` |

A preset is named `<material>-<codes>`, the codes being the slot letters joined
in slot order: `pla-cmyk`, `pla-cmyw`, `pla-cmyn`, `pla-rybw`. The letters are
`C` cyan, `M` magenta, `Y` yellow, `K` black, `W` white, `R` red, `B` blue,
`G` **green** and `N` the **neutral** grey - so a six- or eight-spool set that
contains both green and grey cannot be misread, and a longer set simply joins
more letters. Only those letters are codes; anything else (a "natural" spool,
say) is spelled out. `presets.validate()` enforces the spelling.

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

Sets with more than four spools are not shipped yet: the planner already accepts
*N* contiguous slots, but the bundled template carries four-slot arrays, so such
a project needs a matching settings template exported from the slicer.

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
The table below runs the 60-colour hue wheel with the shipped example's spool
colours. Component counts are explicit so these measurements do not depend on
the default (the idealised `#00FF…` values also need the caveat below):

| setting | mixes | median ΔE | worst ΔE | predicted > ΔE 10 |
| --- | --- | --- | --- | --- |
| `average`, `--components 2 --step 5` | 40 | 6.4 | 22.1 | 20/60 |
| `average`, `--components 2 --step 1` | 49 | 6.2 | 22.1 | 20/60 |
| `pigment`, `--components 2 --step 5` | 42 | 4.0 | 21.2 | 19/60 |
| `pigment`, `--components 3 --step 1` | 50 | 3.8 | 21.2 | 19/60 |
| `transmission` (experimental), `--components 2 --step 5` | 42 | 1.2 | 8.0 | 0/60 |
| `transmission` (experimental), `--components 2 --step 1` | 57 | 0.3 | 1.6 | 0/60 |

The `transmission` rows only say that the wheel is reachable *inside that
formula*: the model is uncalibrated (see below), so they are **not** evidence
that these spools print the wheel. Only the `average` and `pigment` rows compare
against a model whose behaviour has an external reference.

Reproduce these with the shipped example:

```
./tools/bench_mixes.py examples/hue-wheel.scad --preset translucent-cmyn \
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

* It can rank recipes under the selected approximation.
* It cannot predict the printed colour: no absorption spectra, no reference
  thickness, no substrate and no illumination model. `mix.model:
  "transmission"` is experimental - calibrate it with printed swatches.

Calibrate, in the viewing mode the part is for:

1. **Reflective viewing** (lit from the viewer's side): measure pure and mixed
   patches at the intended thickness, with the same backing, lighting and
   viewing face. Keep recipe assignments fixed during calibration and reserve
   separate recipes for validation. Display HEX values alone do not identify
   absorption or scattering; changing `mix.step` or `mix.components` changes
   the search space, not the physical model.
2. **Transmissive / backlit viewing** (thin walls, lampshades, diffusers - a
   documented use of translucent PLA): the part is judged by the light passing
   through it, so calibrate against backlight, not against a backer. Print the
   same swatch grid as thin walls and compare it lit from behind; a reflective
   white backing would defeat this mode, so do not force one here.

Practical notes that hold in both modes:

* Thin interleaved layers can combine spectral filtering, scattering and spatial
  averaging. Layer order, surface orientation and viewing distance matter.
* A grey spool is not necessarily a spectrally neutral filter. An opaque white
  spool or backing changes the optical system and requires separate calibration.
* Thickness can change hue, lightness and chroma; do not assume that saturation
  always increases.
* Purge/prime towers and travel moves leave translucent smears more visibly than
  opaque ones - keep wiping parameters generous.

### Panchroma CMYN calibration kit

Generate exact-recipe test projects without calling the colour solver:

```sh
python3 tools/make_panchroma_calibration.py calibration/runs/new-run
```

The output directory must not already exist. Slots are **1=Cyan, 2=Magenta,
3=Yellow, 4=Grey (N)**, not black. The script uses the bundled Snapmaker U1
0.4 mm printer template. Its vendor HEX/TD metadata comes from
[Polymaker's table](https://wiki.polymaker.com/polymaker-products/more-about-our-products/hex-codes-and-transmission-distances);
these values are neither transmittance spectra nor measured mixture colours.

[Snapmaker's colour reference](https://wiki.snapmaker.com/en/snapmaker_orca/full_spectrum_color_reference)
also supplies 39 photographed recipes and a downloadable 177-colour project.
It is a visual reference, not a numeric mixture-measurement dataset. Its
[filament TD table](https://s3.us-west-2.amazonaws.com/snapmaker.com/download/manual/PLA+Full+Spectrum+Filament+Bundle+Hex+Code+%26+TD+Value+Table.pdf)
uses the same HEX values but lists C/M/Y/Gray TD as 5.5/5.5/9.5/6.5, versus
Polymaker's 8/7.8/14/11.5. Matching HEX does not establish optical equivalence
between those products or batches; do not substitute either calibration blindly.

| Projects | Coupons | Purpose |
| --- | --- | --- |
| `thickness-cyan`, `thickness-magenta`, `thickness-yellow`, `thickness-grey` | 11 per spool | Pure-material thickness response from 0.16 to 15.36 mm |
| `mix-fit` | 35 recipes + 2 repeatability controls | Complete 25% composition grid across 1-4 components, at 3.2 mm thickness |
| `mix-holdout` | 20 | Separate two-, three- and four-component recipes, excluded from fitting |
| `layer-order` | 6 | Equal-ratio stacks with reversed block order or interleaving; physical slots, not virtual mixes |

Open the **3MF** files as projects. SCAD files are geometry references and cannot
preserve the explicit virtual recipes through the normal colour-solving CLI.
SVG maps identify the coupons from above, with the front at the bottom and a
clipped front-left corner on each coupon. Labels are **not printed**: photograph
the plate before removal and transfer IDs to containers or non-measurement edges.
`samples.csv` records ratios and layout. The general-purpose `measurements.csv`
supports instrument readings and camera-derived results; it is deliberately
blank apart from IDs and viewing modes. Neither it nor the instrument-specific
sheet below reads RAW images or imports measurements automatically.
`manifest.json` records the intended process and source metadata, not measured
results.

**Before printing:** verify the actual printer, loaded slot order and material
temperatures. The calibration process explicitly sets 0.08 mm layers, a 0.16 mm
first layer, 100% rectilinear infill, no ironing and no support. Keep these
conditions fixed across calibration and validation. Check the wipe tower
clearance and inspect the sliced tool assignments, especially the thin coupons.
The virtual percentages are requests to the slicer, not measured extrusion
fractions; retain G-code and note layer rounding and first-layer effects.
The layer-order controls use 0.16 mm material blocks: normally two 0.08 mm layers,
except the first block, which is one 0.16 mm first layer. No permanent backing
or label geometry crosses the central measurement area.

**Measurement:** use the central 10 x 10 mm of each 20 x 20 mm coupon. Measure
actual thickness without crushing thin samples. Record spool batch, print run,
face, rotation and lighting. Keep white-backed reflection, black-backed
reflection and backlit transmission as separate datasets. Reposition and repeat
each reading at least three times; reprint selected controls to separate capture
repeatability from printer repeatability. For photography, use RAW where
available, fixed exposure/white balance, a colour reference, uniform lighting
and an unclipped central region. Camera RGB without colour calibration is not
an absolute Lab measurement, and camera channels cannot recover a full spectrum.
A spectrophotometer with transmission capability is needed for spectral
transmittance; scattering samples require attention to total versus direct
transmission and measurement aperture.

Start with measured-recipe nearest-neighbour matching or interpolation within
the measured composition grid. Keep `mix-holdout` out of model fitting and report
its error separately. This kit primarily characterizes flat, top-viewed patches;
other thicknesses, sidewalls, backing materials and layer sequences require
their own validation. It does not install a calibrated colour model in the CLI.

#### i1Pro 2 recording protocol

Every generation also writes `measurements-i1pro2.csv`, `backings.csv`,
`backing-references-i1pro2.csv` and `measurements-i1pro2-guide.txt`.
The guide is copied from the versioned
[instrument protocol template](templates/measurements-i1pro2-guide.txt); edit
that source rather than a generated copy when improving the shared workflow.

For the current 107 coupons, the instrument sheet reserves 642 readings:
white-backed reflection first, then black-backed reflection, with three
repositioned reads per coupon and backing. Each `reading_id` is unique, for
example `TC01-W-01`. It includes design metadata for cross-checking, not measured
extrusion fractions. The general and instrument sheets do not synchronize;
choose the instrument sheet for this workflow rather than entering results twice.

* Enter the actual `L_star`, `a_star` and `b_star` values. Preserve signed values
  and acquisition precision. Blank means unmeasured, not zero.
* Set `spectral_file` only after exporting that reading's spectrum. Keep the
  original wavelength labels and units; recording Lab alone loses the spectrum.
* Confirm the prefilled D50 / CIE 1931 2-degree observer, top face and 0-degree
  rotation against the actual setup. These are protocol defaults, not observations.
* Record actual thickness, print run, measurement session, backing, acquisition
  software/version, instrument identity and measurement condition. Do not copy
  the design thickness into a field intended for a physical measurement.
* `measurement_condition` is intentionally blank. D50 in the Lab computation
  does not imply native M1 acquisition. ArgyllCMS documents that its i1Pro 2
  driver does not use the device UV mode; identify any simulation or FWA
  compensation rather than reporting it as a native hardware condition.

Use the original calibration base for instrument calibration and a separate,
identified sample backing. Use spot measurements in the central area, with
stable support and repeatable instrument placement. Do not compress thin samples
or scan across coupons of different heights. Save individual readings before
averaging; orientation changes and reprints need separate, uniquely identified
readings. Reflection spectra include the sample/backing/geometry combination;
this is not a measurement of intrinsic absorption or total transmission.
Backlit measurements require a separate protocol and are not in this sheet.

**Bare-backing controls:** `backings.csv` records each backing's material, batch,
paper stack, thickness, finish, used face and underlay. WB01 and BB01 are default
white/black identities, not certified optical standards. The coupon sheet
prefills these IDs; confirm the actual setup and use a new ID when it changes.
`backing-references-i1pro2.csv` separately reserves 12 unmeasured controls:
two backings x start/end of one session x three repeats. Fill the same
`measurement_session` in coupon and control rows; match both session and
`backing_id`, as well as acquisition and colorimetric conditions.

The control sheet has no coupon IDs or filament percentages. Keep it out of
recipe fitting and holdout evaluation, and do not subtract backing Lab from
coupon Lab. Preserve individual spectra and placement information. Append
uniquely identified controls for further sessions or uniformity checks instead
of replacing previous readings. The instrument protocol describes the fields.

### Calibration artifacts

Keep reproducible source, local experiments and published measurements separate:

```text
tools/make_panchroma_calibration.py          # versioned generation logic
templates/measurements-i1pro2-guide.txt      # versioned measurement protocol
calibration/runs/<run-id>/                  # local, Git-ignored experiment files
calibration/datasets/<dataset-id>/          # curated measured data, when available
```

The generator requires a new output directory and never refreshes an existing
run in place. Archive an existing experiment by copying its entire directory
into a new `calibration/runs/<run-id>/`, retaining the original until the copy is
verified. Preserve manual projects such as `thickness-cmyn.3mf`; that file is not
an output of the current generator. A regenerated project is not a substitute
for the actual project or G-code used to print a measured sample.

Keep run-specific models, layouts, screenshots, raw captures, settings,
measurement exports and verification records together. Copies do not
synchronize: choose one working copy for subsequent readings. A copy checksum
or historical verification report describes that snapshot, not future edits,
physical colour accuracy or a new generator version. Git-ignored runs are not
backed up by Git; retain separate backups.

Create a dataset directory only after real measurements are available. Promote
the selected readings together with their original spectra, exact `samples.csv`
mapping, run manifest, actual print/measurement conditions and spool batches.
Record the generator/template revision when known, and retain the exact printed
project and G-code in the associated archive; do not guess missing provenance or
rebuild historical mappings with the current generator. Keep holdout labels and
raw individual readings so validation remains independent and repeatability
can be assessed.

Review dataset paths, instrument serial numbers and third-party redistribution
rights before publication. Include only the relevant measured data and
provenance, not an entire working directory. Large photographs and printable
project bundles can remain in separately archived or release assets. Empty
recording sheets are generated outputs, not measurement datasets. CSV and JSON
are not globally ignored, so curated datasets can be versioned normally.

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
