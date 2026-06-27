"""stylist._color — pure-stdlib colour science for the deterministic rules engine.

No numpy, no network, no third-party deps. Everything here is the perceptual
machinery the §4.3 colour-fit axis and the §4.4 outfit-harmony rule need:

  * hex  -> sRGB                       ``hex_to_rgb``
  * sRGB -> CIE-Lab (D65)              ``srgb_to_lab``  (sRGB->linear->XYZ->Lab)
  * Lab  -> perceptual distance        ``delta_e_ciede2000`` (full CIEDE2000)
  * hex  -> hue/sat/light + harmony    ``hue_deg`` / ``saturation`` / ``lightness``
                                       ``hue_distance`` / ``is_analogous`` / ``is_complementary``

ΔE-CIEDE2000 is the perceptually-correct colour difference; we use it (not naive
RGB distance) so "is this product colour close to a palette colour?" matches how
a human eye reads closeness. The HSL helpers drive two-garment harmony, which is
about hue relationships, not absolute distance.
"""

from __future__ import annotations

import math
import re

_HEX_RE = re.compile(r"^#?[0-9a-fA-F]{6}$")

# D65 reference white (CIE 1931, 2°) in the same XYZ scale srgb_to_xyz emits (Y=1).
_XN, _YN, _ZN = 0.95047, 1.0, 1.08883


# --------------------------------------------------------------------------- #
# hex / RGB                                                                    #
# --------------------------------------------------------------------------- #
def hex_to_rgb(hex_str: str) -> tuple:
    """``'#rrggbb'`` (or ``'rrggbb'``) -> ``(r, g, b)`` ints in 0..255.

    Raises ``ValueError`` on anything that is not a 6-digit hex colour.
    """
    if not isinstance(hex_str, str) or not _HEX_RE.match(hex_str):
        raise ValueError(f"{hex_str!r} is not a #rrggbb hex colour")
    h = hex_str[1:] if hex_str.startswith("#") else hex_str
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def is_hex(hex_str) -> bool:
    """True iff ``hex_str`` is a valid 6-digit hex colour (``#`` optional)."""
    return isinstance(hex_str, str) and bool(_HEX_RE.match(hex_str))


# --------------------------------------------------------------------------- #
# sRGB -> CIE-Lab (D65)                                                        #
# --------------------------------------------------------------------------- #
def _srgb_to_linear(c: float) -> float:
    """One gamma-encoded sRGB channel in [0,1] -> linear-light in [0,1]."""
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def srgb_to_xyz(rgb: tuple) -> tuple:
    """``(r,g,b)`` 0..255 -> CIE-XYZ (D65, Y scaled to 1.0)."""
    r, g, b = (v / 255.0 for v in rgb)
    r, g, b = _srgb_to_linear(r), _srgb_to_linear(g), _srgb_to_linear(b)
    x = r * 0.4124564 + g * 0.3575761 + b * 0.1804375
    y = r * 0.2126729 + g * 0.7151522 + b * 0.0721750
    z = r * 0.0193339 + g * 0.1191920 + b * 0.9503041
    return (x, y, z)


def _f_lab(t: float) -> float:
    delta = 6.0 / 29.0
    return t ** (1.0 / 3.0) if t > delta ** 3 else (t / (3 * delta ** 2) + 4.0 / 29.0)


def srgb_to_lab(rgb: tuple) -> tuple:
    """``(r,g,b)`` 0..255 -> CIE-Lab ``(L, a, b)`` (D65). White -> (100,0,0)."""
    x, y, z = srgb_to_xyz(rgb)
    fx, fy, fz = _f_lab(x / _XN), _f_lab(y / _YN), _f_lab(z / _ZN)
    L = 116.0 * fy - 16.0
    a = 500.0 * (fx - fy)
    b = 200.0 * (fy - fz)
    return (L, a, b)


def hex_to_lab(hex_str: str) -> tuple:
    """Convenience: ``'#rrggbb'`` -> CIE-Lab ``(L, a, b)``."""
    return srgb_to_lab(hex_to_rgb(hex_str))


# --------------------------------------------------------------------------- #
# ΔE — CIEDE2000 (the perceptually-correct colour difference)                  #
# --------------------------------------------------------------------------- #
def delta_e_ciede2000(lab1: tuple, lab2: tuple, kL: float = 1.0,
                      kC: float = 1.0, kH: float = 1.0) -> float:
    """Full CIEDE2000 ΔE00 between two CIE-Lab colours.

    Reference implementation per Sharma, Wu & Dalal (2005). Returns 0 for
    identical colours and grows with perceptual difference.
    """
    L1, a1, b1 = lab1
    L2, a2, b2 = lab2

    C1 = math.hypot(a1, b1)
    C2 = math.hypot(a2, b2)
    Cbar = (C1 + C2) / 2.0

    Cbar7 = Cbar ** 7
    G = 0.5 * (1.0 - math.sqrt(Cbar7 / (Cbar7 + 25.0 ** 7)))

    a1p = (1.0 + G) * a1
    a2p = (1.0 + G) * a2

    C1p = math.hypot(a1p, b1)
    C2p = math.hypot(a2p, b2)

    def _h_prime(b_val: float, a_prime: float) -> float:
        if b_val == 0.0 and a_prime == 0.0:
            return 0.0
        h = math.degrees(math.atan2(b_val, a_prime))
        return h + 360.0 if h < 0.0 else h

    h1p = _h_prime(b1, a1p)
    h2p = _h_prime(b2, a2p)

    dLp = L2 - L1
    dCp = C2p - C1p

    if C1p * C2p == 0.0:
        dhp = 0.0
    else:
        diff = h2p - h1p
        if diff > 180.0:
            dhp = diff - 360.0
        elif diff < -180.0:
            dhp = diff + 360.0
        else:
            dhp = diff
    dHp = 2.0 * math.sqrt(C1p * C2p) * math.sin(math.radians(dhp / 2.0))

    Lbarp = (L1 + L2) / 2.0
    Cbarp = (C1p + C2p) / 2.0

    if C1p * C2p == 0.0:
        hbarp = h1p + h2p
    elif abs(h1p - h2p) > 180.0:
        hbarp = (h1p + h2p + 360.0) / 2.0 if (h1p + h2p) < 360.0 else (h1p + h2p - 360.0) / 2.0
    else:
        hbarp = (h1p + h2p) / 2.0

    T = (1.0
         - 0.17 * math.cos(math.radians(hbarp - 30.0))
         + 0.24 * math.cos(math.radians(2.0 * hbarp))
         + 0.32 * math.cos(math.radians(3.0 * hbarp + 6.0))
         - 0.20 * math.cos(math.radians(4.0 * hbarp - 63.0)))

    dtheta = 30.0 * math.exp(-(((hbarp - 275.0) / 25.0) ** 2))
    Cbarp7 = Cbarp ** 7
    Rc = 2.0 * math.sqrt(Cbarp7 / (Cbarp7 + 25.0 ** 7))

    Lbarp50 = (Lbarp - 50.0) ** 2
    Sl = 1.0 + (0.015 * Lbarp50) / math.sqrt(20.0 + Lbarp50)
    Sc = 1.0 + 0.045 * Cbarp
    Sh = 1.0 + 0.015 * Cbarp * T

    Rt = -math.sin(math.radians(2.0 * dtheta)) * Rc

    return math.sqrt(
        (dLp / (kL * Sl)) ** 2
        + (dCp / (kC * Sc)) ** 2
        + (dHp / (kH * Sh)) ** 2
        + Rt * (dCp / (kC * Sc)) * (dHp / (kH * Sh))
    )


def delta_e_hex(hex1: str, hex2: str) -> float:
    """Convenience: perceptual ΔE-CIEDE2000 between two hex colours."""
    return delta_e_ciede2000(hex_to_lab(hex1), hex_to_lab(hex2))


# --------------------------------------------------------------------------- #
# HSL helpers (harmony — hue relationships, not absolute distance)            #
# --------------------------------------------------------------------------- #
def rgb_to_hsl(rgb: tuple) -> tuple:
    """``(r,g,b)`` 0..255 -> ``(h_deg [0,360), s [0,1], l [0,1])``."""
    r, g, b = (v / 255.0 for v in rgb)
    mx, mn = max(r, g, b), min(r, g, b)
    l = (mx + mn) / 2.0
    if mx == mn:
        return (0.0, 0.0, l)
    d = mx - mn
    s = d / (2.0 - mx - mn) if l > 0.5 else d / (mx + mn)
    if mx == r:
        h = (g - b) / d + (6.0 if g < b else 0.0)
    elif mx == g:
        h = (b - r) / d + 2.0
    else:
        h = (r - g) / d + 4.0
    return (h * 60.0, s, l)


def hsl_of_hex(hex_str: str) -> tuple:
    return rgb_to_hsl(hex_to_rgb(hex_str))


def hue_deg(hex_str: str) -> float:
    """Hue of a hex colour in degrees [0,360)."""
    return hsl_of_hex(hex_str)[0]


def saturation(hex_str: str) -> float:
    """HSL saturation of a hex colour, [0,1]."""
    return hsl_of_hex(hex_str)[1]


def lightness(hex_str: str) -> float:
    """HSL lightness of a hex colour, [0,1]."""
    return hsl_of_hex(hex_str)[2]


def hue_distance(h1: float, h2: float) -> float:
    """Smallest circular distance between two hue angles, in degrees [0,180]."""
    d = abs(h1 - h2) % 360.0
    return d if d <= 180.0 else 360.0 - d


def is_analogous(hex1: str, hex2: str, tol_deg: float = 30.0) -> bool:
    """True when two colours sit within ``tol_deg`` (default 30°) on the wheel."""
    return hue_distance(hue_deg(hex1), hue_deg(hex2)) <= tol_deg


def is_complementary(hex1: str, hex2: str, lo: float = 150.0, hi: float = 210.0) -> bool:
    """True when the two hues are roughly opposite (~150-210° apart).

    Circular distance tops out at 180°, so the 150-210 band maps to a circular
    distance >= 150° (210° wraps to 150°).
    """
    cd = hue_distance(hue_deg(hex1), hue_deg(hex2))
    lo_cd = min(lo, 360.0 - hi)  # = 150 for the default band
    return cd >= lo_cd


__all__ = [
    "hex_to_rgb",
    "is_hex",
    "srgb_to_xyz",
    "srgb_to_lab",
    "hex_to_lab",
    "delta_e_ciede2000",
    "delta_e_hex",
    "rgb_to_hsl",
    "hsl_of_hex",
    "hue_deg",
    "saturation",
    "lightness",
    "hue_distance",
    "is_analogous",
    "is_complementary",
]
