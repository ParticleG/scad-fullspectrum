"""Colour helpers: hex parsing, blend models and CIEDE2000.

Three models answer "what colour does this recipe produce?" (see ``MIX_MODELS``):

* ``average`` - weighted average in sRGB space; a cheap stand-in for opaque
  filaments.
* ``pigment`` - the degree-4 pigment polynomial the slicers use to draw their
  mix preview, so predictions can be compared against what the GUI shows.
* ``transmission`` - experimental, uncalibrated heuristic for translucent
  filament; see :func:`blend_transmission` for what it assumes and why its ΔE
  must not be read as printed accuracy.

All of them are models: real printed colour also depends on filament opacity
(TD), layer height, temperature, speed, the substrate and the viewing light.
``delta_e_2000`` ranks recipes perceptually rather than in raw RGB distance.
"""

from __future__ import annotations

import functools
import math

from . import _pigment_model

__all__ = [
    "RGB",
    "hex_to_rgb",
    "rgb_to_hex",
    "srgb_to_linear",
    "linear_to_srgb",
    "blend_rgb",
    "blend_hex",
    "blend_pigment",
    "blend_transmission",
    "mix_model",
    "MIX_MODELS",
    "rgb_to_lab",
    "delta_e_2000",
    "grade",
]

RGB = tuple[int, int, int]

#: Blend models, all taking ``[(rgb, weight), ...]`` and returning an ``RGB``.
#:
#: * ``average``      - weighted average in sRGB space (opaque filaments, fast).
#: * ``pigment``      - the degree-4 pigment polynomial the slicers use for their
#:                      mix preview (matches the swatch shown in the GUI).
#: * ``transmission`` - **experimental, uncalibrated heuristic** for translucent
#:                      filaments: weighted geometric mean in linear light, with
#:                      no reference thickness, no measured absorption data and
#:                      no substrate/illumination model. See
#:                      :func:`blend_transmission` before trusting a number.
MIX_MODELS = ("average", "pigment", "transmission")

#: Models whose output is a rough guess that must be validated by printing.
EXPERIMENTAL_MODELS = ("transmission",)


def hex_to_rgb(text: str) -> RGB:
    """Parse ``#RRGGBB`` / ``RRGGBB`` into an ``(r, g, b)`` triple."""

    value = text.strip().lstrip("#")
    if len(value) == 3:  # #abc shorthand
        value = "".join(ch * 2 for ch in value)
    if len(value) != 6:
        raise ValueError(f"not a hex colour: {text!r}")
    return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16))


def rgb_to_hex(rgb: RGB) -> str:
    return "#{:02X}{:02X}{:02X}".format(*(max(0, min(255, int(round(c)))) for c in rgb))


def srgb_to_linear(value: float) -> float:
    """sRGB 0..1 to linear light."""

    return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4


def linear_to_srgb(value: float) -> float:
    """Linear light to sRGB 0..1."""

    return 12.92 * value if value <= 0.0031308 else 1.055 * value ** (1.0 / 2.4) - 0.055


def blend_rgb(colors: list[tuple[RGB, float]]) -> RGB:
    """Weighted average in sRGB space; weights are normalised."""

    total = sum(weight for _, weight in colors)
    if total <= 0:
        raise ValueError("blend needs at least one positive weight")
    out = [0.0, 0.0, 0.0]
    for rgb, weight in colors:
        for channel in range(3):
            out[channel] += rgb[channel] * weight / total
    return tuple(int(round(channel)) for channel in out)  # type: ignore[return-value]


@functools.lru_cache(maxsize=1024)
def _pigment_pair_terms(a: RGB, b: RGB) -> tuple[tuple[float, float, float], ...]:
    """Group the polynomial terms of one colour pair by their power of ``t``.

    The full evaluation is ``INTERCEPT + sum_k t**k * terms[k]``, so a pair costs
    one table build and 15 multiply-adds per ratio afterwards.
    """

    terms = [[0.0, 0.0, 0.0] for _ in range(5)]
    channels = a + b
    for powers, coefficient in zip(_pigment_model.POWERS, _pigment_model.COEF):
        monomial = 1.0
        for index, exponent in enumerate(powers[:6]):
            if exponent:
                monomial *= channels[index] ** exponent
        row = terms[powers[6]]
        for channel in range(3):
            row[channel] += monomial * coefficient[channel]
    return tuple(tuple(row) for row in terms)  # type: ignore[return-value]


def _pigment_pair(a: RGB, b: RGB, t: float) -> RGB:
    """One step of the slicer's pigment mixer (matches ``filament_mixer::lerp``)."""

    if t <= 0.0:
        return a
    if t >= 1.0:
        return b
    terms = _pigment_pair_terms(a, b)
    out: list[int] = []
    for channel in range(3):
        value = _pigment_model.INTERCEPT[channel]
        power = 1.0
        for k in range(5):
            value += terms[k][channel] * power
            power *= t
        out.append(max(0, min(255, int(value))))
    return (out[0], out[1], out[2])


def blend_pigment(colors: list[tuple[RGB, float]]) -> RGB:
    """The slicers' mix preview: pairwise pigment polynomial, weighted in order."""

    components = [(rgb, float(weight)) for rgb, weight in colors if weight > 0]
    if not components:
        raise ValueError("blend needs at least one positive weight")
    current, accumulated = components[0][0], components[0][1]
    for rgb, weight in components[1:]:
        total = accumulated + weight
        current = _pigment_pair(current, rgb, weight / total)
        accumulated = total
    return current


def blend_transmission(colors: list[tuple[RGB, float]]) -> RGB:
    """**Experimental heuristic** for translucent filaments - not a prediction.

    Translucent layers filter light instead of covering it, so the physical
    behaviour is multiplicative.  This function assumes the simplest possible
    version of that: the entered hex values are treated as transmittances, and
    the per-channel result is their weighted geometric mean in linear light.
    That is enough to make the *direction* of the effect visible (magenta +
    yellow layers tend towards red instead of pink), but it is not calibrated:

    * the input hex values are the colours of the filament *as displayed*, not
      measured transmittance spectra, and nothing knows the layer thickness the
      colour was measured at;
    * a zero channel is floored at ``1e-6``, so "fully transmitting" channels
      darken instead of staying open - an artefact of the implementation;
    * the substrate, the number of layers, the viewing light, layer interfaces
      and purging are all absent from the model.

    Its ΔE numbers therefore only describe this formula.  They become physically
    meaningful only after the inputs are measured (patch prints of each spool at
    a fixed thickness) and the predictions have been checked against printed
    mixture swatches.  Prefer printed swatches, and treat the tool output as a
    search heuristic.
    """

    total = sum(weight for _, weight in colors)
    if total <= 0:
        raise ValueError("blend needs at least one positive weight")
    out = [0.0, 0.0, 0.0]
    for rgb, weight in colors:
        share = weight / total
        if share == 0:
            continue
        for channel in range(3):
            out[channel] += share * math.log(max(srgb_to_linear(rgb[channel] / 255.0), 1e-6))
    return tuple(  # type: ignore[return-value]
        max(0, min(255, int(round(linear_to_srgb(math.exp(value)) * 255.0)))) for value in out
    )


def mix_model(name: str):
    """Look up a blend model by name."""

    try:
        return _MIX_MODEL_TABLE[name]
    except KeyError:
        raise ValueError(f"unknown mix model {name!r}, expected one of {MIX_MODELS}") from None


_MIX_MODEL_TABLE = {
    "average": blend_rgb,
    "pigment": blend_pigment,
    "transmission": blend_transmission,
}


def blend_hex(colors: list[tuple[RGB, float]]) -> str:
    """Weighted-average blend as a hex string (kept for callers of the average model)."""

    return rgb_to_hex(blend_rgb(colors))


def rgb_to_lab(rgb: RGB) -> tuple[float, float, float]:
    """sRGB (D65) to CIELAB."""

    r, g, b = (srgb_to_linear(channel / 255.0) for channel in rgb)
    x = (0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047
    y = 0.2126 * r + 0.7152 * g + 0.0722 * b
    z = (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883

    def f(t: float) -> float:
        return t ** (1.0 / 3.0) if t > 0.008856 else (7.787 * t + 16.0 / 116.0)

    fx, fy, fz = f(x), f(y), f(z)
    return (116.0 * fy - 16.0, 500.0 * (fx - fy), 200.0 * (fy - fz))


def delta_e_2000(lab1: tuple[float, float, float], lab2: tuple[float, float, float]) -> float:
    """CIEDE2000 colour difference (1.0 is roughly the just-noticeable step)."""

    l1, a1, b1 = lab1
    l2, a2, b2 = lab2
    rad = math.pi / 180.0

    c1 = math.hypot(a1, b1)
    c2 = math.hypot(a2, b2)
    c_bar = (c1 + c2) / 2.0
    g = 0.5 * (1.0 - math.sqrt(c_bar**7 / (c_bar**7 + 25.0**7)))
    a1p = a1 * (1.0 + g)
    a2p = a2 * (1.0 + g)
    c1p = math.hypot(a1p, b1)
    c2p = math.hypot(a2p, b2)
    h1p = math.degrees(math.atan2(b1, a1p)) % 360.0
    h2p = math.degrees(math.atan2(b2, a2p)) % 360.0

    d_lp = l2 - l1
    d_cp = c2p - c1p
    d_hp = 0.0
    if c1p * c2p != 0.0:
        d_hp = h2p - h1p
        if d_hp > 180.0:
            d_hp -= 360.0
        elif d_hp < -180.0:
            d_hp += 360.0
    d_big_h = 2.0 * math.sqrt(c1p * c2p) * math.sin(d_hp / 2.0 * rad)

    l_bar = (l1 + l2) / 2.0
    c_bar_p = (c1p + c2p) / 2.0
    if c1p * c2p == 0.0:
        h_bar = h1p + h2p
    else:
        h_bar = h1p + h2p
        if abs(h1p - h2p) > 180.0:
            h_bar += 360.0 if h_bar < 360.0 else -360.0
        h_bar /= 2.0

    t = (
        1.0
        - 0.17 * math.cos((h_bar - 30.0) * rad)
        + 0.24 * math.cos(2.0 * h_bar * rad)
        + 0.32 * math.cos((3.0 * h_bar + 6.0) * rad)
        - 0.20 * math.cos((4.0 * h_bar - 63.0) * rad)
    )
    d_theta = 30.0 * math.exp(-(((h_bar - 275.0) / 25.0) ** 2))
    r_c = 2.0 * math.sqrt(c_bar_p**7 / (c_bar_p**7 + 25.0**7))
    s_l = 1.0 + (0.015 * (l_bar - 50.0) ** 2) / math.sqrt(20.0 + (l_bar - 50.0) ** 2)
    s_c = 1.0 + 0.045 * c_bar_p
    s_h = 1.0 + 0.015 * c_bar_p * t
    r_t = -math.sin(2.0 * d_theta * rad) * r_c

    return math.sqrt(
        (d_lp / s_l) ** 2
        + (d_cp / s_c) ** 2
        + (d_big_h / s_h) ** 2
        + r_t * (d_cp / s_c) * (d_big_h / s_h)
    )


def grade(delta_e: float) -> str:
    """Coarse quality bucket used in the report."""

    if delta_e <= 2.0:
        return "exact"
    if delta_e <= 5.0:
        return "close"
    if delta_e <= 10.0:
        return "approximate"
    return "out-of-gamut"
