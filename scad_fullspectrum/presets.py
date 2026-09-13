"""Built-in spool presets.

A preset is just a config fragment: the four spools in toolhead order plus the
mix settings that suit them.  It is merged with, and overridden by, a user config
file and the command line flags, so ``--preset pla-cmyw -c my.json`` keeps the
preset spools and lets the file change whatever it wants.

A name is ``<material>-<codes>`` where ``<codes>`` is ``SLOT_CODES`` concatenated
in slot order, exactly as in ``pla-cmyk``, ``pla-cmyw``, ``pla-cmyn`` and
``pla-rybw``; :func:`validate` enforces that spelling.

Slot order follows the toolheads: slot 1 is the first extruder.  Every colour is
an *idealised* value - measure your own spools (printed patch at the working
thickness, backing and light) and put those hex values in your config.
"""

from __future__ import annotations

import copy

from .color import EXPERIMENTAL_MODELS, MIX_MODELS

__all__ = ["PRESETS", "SLOT_CODES", "names", "get", "is_preset", "describe", "merge", "validate"]

#: Single-letter codes used in preset names.  ``G`` is **green** and ``N`` is the
#: neutral grey, so a six- or eight-spool set that contains both stays readable.
#: Only these letters are single-letter codes; anything else (a future "natural"
#: spool, for instance) is spelled out in full.
SLOT_CODES: dict[str, str] = {
    "C": "cyan",
    "M": "magenta",
    "Y": "yellow",
    "K": "black",
    "W": "white",
    "R": "red",
    "B": "blue",
    "G": "green",
    "N": "grey",
}

#: Accepted spellings for each code's filament name (used by :func:`validate`).
SLOT_NAME_WORDS: dict[str, tuple[str, ...]] = {
    "N": ("grey", "gray", "neutral"),
}


def _filament(slot: int, color: str, name: str) -> dict:
    return {"slot": slot, "color": color, "name": name}


PRESETS: dict[str, dict] = {
    "translucent-cmyn": {
        "codes": ["C", "M", "Y", "N"],
        "summary": "Translucent cyan / magenta / yellow + translucent neutral grey (e.g. Polymaker Panchroma CMYK kit)",
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
            _filament(4, "#808080", "Translucent Neutral Grey"),
        ],
        "uncolored": None,
        "mix": {
            "components": 4,
            "step": 1,
            "pure_threshold": 1.0,
            "max_mixes": None,
            "model": "transmission",
        },
    },
    "pla-cmyk": {
        "codes": ["C", "M", "Y", "K"],
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
        "mix": {"components": 4, "step": 5, "pure_threshold": 1.0, "max_mixes": None, "model": "pigment"},
    },
    "pla-cmyw": {
        "codes": ["C", "M", "Y", "W"],
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
        "mix": {"components": 4, "step": 5, "pure_threshold": 1.0, "max_mixes": None, "model": "pigment"},
    },
    "pla-cmyn": {
        "codes": ["C", "M", "Y", "N"],
        "summary": "Opaque cyan / magenta / yellow + neutral grey (the set the reference FullSpectrum project used)",
        "note": (
            "Grey works as a desaturator and mid-tone; with no white or black the palette "
            "covers muted colours better than saturated ones. The pigment model matches the "
            "swatch the slicer draws, not the printed part."
        ),
        "base_filaments": [
            _filament(1, "#00FFFF", "Cyan"),
            _filament(2, "#FF00FF", "Magenta"),
            _filament(3, "#FFFF00", "Yellow"),
            _filament(4, "#808080", "Neutral Grey"),
        ],
        "uncolored": None,
        "mix": {"components": 4, "step": 5, "pure_threshold": 1.0, "max_mixes": None, "model": "pigment"},
    },
    "pla-rybw": {
        "codes": ["R", "Y", "B", "W"],
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
        "mix": {"components": 4, "step": 5, "pure_threshold": 1.0, "max_mixes": None, "model": "pigment"},
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
        f"{entry['slot']} {code}:{entry['name']} {entry['color']}"
        for entry, code in zip(preset["base_filaments"], preset.get("codes", []))
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


def validate() -> list[str]:
    """Return the problems found in the registry (empty when everything is sane)."""

    problems: list[str] = []
    for name, preset in PRESETS.items():
        spools = preset.get("base_filaments", [])
        codes = preset.get("codes", [])
        if len(spools) != len(codes):
            problems.append(f"{name}: {len(codes)} codes for {len(spools)} spools")
        else:
            for entry, code in zip(spools, codes):
                if code not in SLOT_CODES:
                    problems.append(f"{name}: unknown slot code {code!r}")
                    continue
                words = SLOT_NAME_WORDS.get(code, (SLOT_CODES[code],))
                label = str(entry.get("name", "")).lower()
                if not any(word in label for word in words):
                    problems.append(
                        f"{name}: slot {entry.get('slot')} is coded {code!r} "
                        f"({SLOT_CODES[code]}) but named {entry.get('name')!r}"
                    )
        if len(spools) != 4:
            problems.append(f"{name}: {len(spools)} spools; the bundled template has four")
        mix = preset.get("mix", {})
        if mix.get("model") not in MIX_MODELS:
            problems.append(f"{name}: unknown model {mix.get('model')!r}")
        if not preset.get("summary"):
            problems.append(f"{name}: no summary")
        token = name.rsplit("-", 1)[-1].upper()
        expected_token = "".join(codes)
        if token != expected_token:
            problems.append(f"{name}: name says {token!r} but its codes are {expected_token!r}")
    return problems
