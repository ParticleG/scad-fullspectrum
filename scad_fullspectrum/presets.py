"""Built-in spool presets.

A preset is just a config fragment: the four spools in toolhead order plus the
mix settings that suit them.  It is merged with, and overridden by, a user config
file and the command line flags, so ``--preset pla-cmyw -c my.json`` keeps the
preset spools and lets the file change whatever it wants.

Slot order follows the toolheads: slot 1 is the first extruder.  Every colour is
an *idealised* value - measure your own spools (printed patch at the working
thickness, backing and light) and put those hex values in your config.
"""

from __future__ import annotations

import copy

from .color import EXPERIMENTAL_MODELS

__all__ = ["PRESETS", "names", "get", "is_preset", "describe", "merge"]


def _filament(slot: int, color: str, name: str) -> dict:
    return {"slot": slot, "color": color, "name": name}


PRESETS: dict[str, dict] = {
    "translucent-cmyg": {
        "summary": "Translucent cyan / magenta / yellow + translucent grey (e.g. Polymaker Panchroma CMYK kit)",
        "note": (
            "Uses the experimental transmission model: it assumes the entered colours are "
            "transmittances and has no reference thickness, absorption data or lighting model, "
            "so its ΔE compares the formula with itself. Print pure-filament patches and a "
            "mixture grid at your working thickness, backing (or backlight) and light, then put "
            "the measured hex values here. Grey is a neutral-density filter: it darkens and "
            "desaturates, so keep it out of saturated mixes."
        ),
        "base_filaments": [
            _filament(1, "#00FFFF", "Translucent Cyan"),
            _filament(2, "#FF00FF", "Translucent Magenta"),
            _filament(3, "#FFFF00", "Translucent Yellow"),
            _filament(4, "#808080", "Translucent Grey"),
        ],
        "uncolored": None,
        "mix": {
            "components": 2,
            "step": 1,
            "pure_threshold": 1.0,
            "max_mixes": None,
            "model": "transmission",
        },
    },
    "pla-cmyk": {
        "summary": "Opaque cyan / magenta / yellow + black",
        "note": (
            "Black densifies instead of lightening, so light and pastel colours are out of "
            "reach with this set - use pla-cmyw when you need them. The pigment model matches "
            "the swatch the slicer draws, not the printed part."
        ),
        "base_filaments": [
            _filament(1, "#00FFFF", "Cyan"),
            _filament(2, "#FF00FF", "Magenta"),
            _filament(3, "#FFFF00", "Yellow"),
            _filament(4, "#000000", "Black"),
        ],
        "uncolored": None,
        "mix": {"components": 2, "step": 5, "pure_threshold": 1.0, "max_mixes": None, "model": "pigment"},
    },
    "pla-cmyw": {
        "summary": "Opaque cyan / magenta / yellow + white",
        "note": (
            "White lightens and desaturates: good for pastels, weak for dark or saturated "
            "results (no black in the set). The pigment model matches the swatch the slicer "
            "draws, not the printed part."
        ),
        "base_filaments": [
            _filament(1, "#00FFFF", "Cyan"),
            _filament(2, "#FF00FF", "Magenta"),
            _filament(3, "#FFFF00", "Yellow"),
            _filament(4, "#FFFFFF", "White"),
        ],
        "uncolored": None,
        "mix": {"components": 2, "step": 5, "pure_threshold": 1.0, "max_mixes": None, "model": "pigment"},
    },
    "pla-cmyg": {
        "summary": "Opaque cyan / magenta / yellow + grey (the set the reference FullSpectrum project used)",
        "note": (
            "Grey works as a desaturator and mid-tone; with no white or black the palette "
            "covers muted colours better than saturated ones. The pigment model matches the "
            "swatch the slicer draws, not the printed part."
        ),
        "base_filaments": [
            _filament(1, "#00FFFF", "Cyan"),
            _filament(2, "#FF00FF", "Magenta"),
            _filament(3, "#FFFF00", "Yellow"),
            _filament(4, "#808080", "Grey"),
        ],
        "uncolored": None,
        "mix": {"components": 2, "step": 5, "pure_threshold": 1.0, "max_mixes": None, "model": "pigment"},
    },
    "pla-rybw": {
        "summary": "Opaque red / yellow / blue + white (artist set, good for greens and oranges)",
        "note": (
            "The pigment model mixes these artistically (blue + yellow leans green), which is "
            "why this set is popular for illustration work. It is still a preview model, not a "
            "print measurement."
        ),
        "base_filaments": [
            _filament(1, "#FF0000", "Red"),
            _filament(2, "#FFFF00", "Yellow"),
            _filament(3, "#0000FF", "Blue"),
            _filament(4, "#FFFFFF", "White"),
        ],
        "uncolored": None,
        "mix": {"components": 3, "step": 5, "pure_threshold": 1.0, "max_mixes": None, "model": "pigment"},
    },
}


def names() -> tuple[str, ...]:
    return tuple(PRESETS)


def is_preset(name: str) -> bool:
    return name in PRESETS


def get(name: str) -> dict:
    """Return a copy of a preset config fragment."""

    try:
        return copy.deepcopy(PRESETS[name])
    except KeyError:
        raise ValueError(f"unknown preset {name!r}, expected one of {', '.join(names())}") from None


def describe(name: str) -> str:
    preset = PRESETS[name]
    spools = " | ".join(
        f"{entry['slot']}:{entry['name']} {entry['color']}" for entry in preset["base_filaments"]
    )
    mix = preset["mix"]
    model = mix["model"] + (" (experimental)" if mix["model"] in EXPERIMENTAL_MODELS else "")
    return (
        f"{name:<18} {preset['summary']}\n"
        f"{'':<18} {spools}\n"
        f"{'':<18} model={model} components={mix['components']} step={mix['step']}"
    )


def merge(base: dict, override: dict) -> dict:
    """Merge two config fragments; ``override`` wins, nested ``mix`` merges key-wise."""

    result = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = {**result[key], **value}
        else:
            result[key] = copy.deepcopy(value)
    return result
