"""Colour helpers: hex parsing, the FullSpectrum blend model and CIEDE2000.

The blend model is the sRGB-space weighted average.  That is the model the
FullSpectrum fork uses to preview a mixed filament (verified externally against
its own "Mix Effect" swatches), and it is also the model the physical result
approximates when thin layers of two filaments alternate below the eye's
resolving power.  It is a heuristic: real printed colour also depends on
filament opacity (TD), temperature and speed.  ``delta_e_2000`` is used to rank
recipes perceptually rather than in raw RGB distance.
"""

from __future__ import annotations

import math

__all__ = [
    "RGB",
    "hex_to_rgb",
    "rgb_to_hex",
    "blend_rgb",
    "blend_hex",
    "rgb_to_lab",
    "delta_e_2000",
    "grade",
]

RGB = tuple[int, int, int]


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


def blend_hex(colors: list[tuple[RGB, float]]) -> str:
    return rgb_to_hex(blend_rgb(colors))


def rgb_to_lab(rgb: RGB) -> tuple[float, float, float]:
    """sRGB (D65) to CIELAB."""

    def linearize(channel: int) -> float:
        value = channel / 255.0
        return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4

    r, g, b = (linearize(channel) for channel in rgb)
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
