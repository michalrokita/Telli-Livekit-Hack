"""stylist.rules — the deterministic styling brain (§4.1 tables + §4.3 scoring + §4.4 harmony).

NO network, NO LLM, stdlib only. This is where "correctness lives" (the LLM later
only writes prose). Everything is a pure function over the ``schemas`` dataclasses:

    StyleProfile ──build_match_profile()──▶ MatchProfile   (the query, via §4.1 rule tables)
    CatalogProduct ─score_product(match,·)─▶ {score, breakdown, hard_filtered, reasons}
    (hat_hex, tee_hex, contrast) ─outfit_harmony()─▶ harmony ∈ [0,1]   (§4.4)
    StyleProfile ──feasible_categories()──▶ {"hat","tshirt"} subset   (§3 feasibility gate)

The rule tables below ARE the §4.1 stylist heuristics, encoded as data so they can
be inspected, tested, and tuned without touching logic.
"""

from __future__ import annotations

import math

from . import _color, schemas

# =========================================================================== #
# §4.1 RULE TABLES (encoded stylist heuristics — data, not logic)             #
# =========================================================================== #

# --- Face shape -> hat archetypes {recommend[], avoid[]} -------------------- #
FACE_SHAPE_HAT = {
    "oval":    {"recommend": ["balanced brim", "most styles", "6-panel cap", "short-brim fedora"],
                "avoid": []},
    "round":   {"recommend": ["structured", "angular", "tall crown", "straight brim",
                              "6-panel cap", "short-brim fedora"],
                "avoid": ["round beanie low", "snug bucket"]},
    "square":  {"recommend": ["rounded crown", "soft fedora", "medium brim"],
                "avoid": ["hard flat structured brim"]},
    "oblong":  {"recommend": ["wide brim", "medium brim", "low crown", "fuller beanie"],
                "avoid": ["tall crown", "brimless"]},
    "heart":   {"recommend": ["medium brim", "downward tilt", "soft fedora"],
                "avoid": ["wide tall crown"]},
    "diamond": {"recommend": ["medium brim", "fuller crown", "soft fedora"],
                "avoid": ["narrow brim"]},
}

# --- Undertone/season -> palette {wear:[(name,hex,family)], avoid:[...]} ----- #
# Every wear colour carries a real #rrggbb; family ∈ {warm,cool,neutral}.
PALETTES = {
    "warm-autumn": {
        "wear": [
            ("olive", "#556b2f", "warm"), ("rust", "#b7410e", "warm"),
            ("mustard", "#c9a227", "warm"), ("terracotta", "#cc6b49", "warm"),
            ("cream", "#f5f0e1", "warm"), ("forest", "#2e4d2e", "warm"),
            ("warm brown", "#6f4e37", "warm"),
        ],
        "avoid": ["icy pastels", "pure white"],
    },
    "warm-spring": {
        "wear": [
            ("coral", "#ff6f61", "warm"), ("peach", "#ffcba4", "warm"),
            ("warm turquoise", "#30d5c8", "warm"), ("golden yellow", "#ffd700", "warm"),
            ("camel", "#c19a6b", "warm"), ("ivory", "#fffff0", "warm"),
        ],
        "avoid": ["heavy black", "muted grey"],
    },
    "cool-winter": {
        "wear": [
            ("true white", "#ffffff", "neutral"), ("black", "#1a1a1a", "neutral"),
            ("navy", "#1f2a44", "cool"), ("royal", "#4169e1", "cool"),
            ("emerald", "#009b77", "cool"), ("magenta", "#c71585", "cool"),
            ("cool red", "#c8102e", "cool"),
        ],
        "avoid": ["orange", "mustard", "camel"],
    },
    "cool-summer": {
        "wear": [
            ("soft navy", "#3b4a6b", "cool"), ("slate", "#708090", "cool"),
            ("lavender", "#b57edc", "cool"), ("rose", "#c08081", "cool"),
            ("soft teal", "#6fb1a0", "cool"), ("grey", "#808080", "neutral"),
        ],
        "avoid": ["bright orange", "warm gold"],
    },
    # olive / neutral undertone OR low-confidence -> the safe-universal palette.
    "safe-universal": {
        "wear": [
            ("navy", "#1f2a44", "cool"), ("teal", "#008080", "cool"),
            ("true red", "#cf2030", "neutral"), ("charcoal", "#36454f", "neutral"),
            ("sapphire", "#0f52ba", "cool"), ("emerald", "#009b77", "cool"),
        ],
        "avoid": ["very warm extremes", "very cool extremes"],
    },
}

# --- Contrast level -> contrast_strategy (enum bold|tonal) ------------------- #
# high contrast carries bold colour-blocking; low contrast wants tonal/monochrome
# (avoid stark black↔white). medium can still carry bold.
CONTRAST_STRATEGY = {"high": "bold", "medium": "bold", "low": "tonal"}

# --- Build -> t-shirt {fits_ok, necklines_ok, avoid} ------------------------ #
BUILD_TSHIRT = {
    "slim":     {"fits_ok": ["slim", "regular"], "necklines_ok": ["crew", "henley"],
                 "avoid": ["oversized", "boxy"]},
    "athletic": {"fits_ok": ["fitted", "regular"], "necklines_ok": ["crew"],
                 "avoid": ["clingy"]},
    "average":  {"fits_ok": ["regular"], "necklines_ok": ["crew", "v"],
                 "avoid": []},
    "broad":    {"fits_ok": ["regular"], "necklines_ok": ["crew", "slight v"],
                 "avoid": ["clingy", "skin-tight"]},
    "fuller":   {"fits_ok": ["regular", "drape"], "necklines_ok": ["v", "vertical"],
                 "avoid": ["clingy", "big horizontal stripe"]},
}

# --- Neck length -> neckline additions (long->crew/high; short->V/scoop) ----- #
NECK_NECKLINE = {
    "long":    ["crew", "high"],
    "average": [],
    "short":   ["v", "scoop"],
}

# --- Face shape -> neckline (round face -> V; angular face -> crew) ---------- #
FACE_NECKLINE = {
    "round":   ["v", "slight v"],
    "square":  ["crew"],
    "diamond": ["crew"],
    "heart":   [],
    "oblong":  [],
    "oval":    [],
}

# Scoring weights (§4.3) — colour is the highest-impact axis.
WEIGHTS = {"colour": 0.40, "shape": 0.30, "vibe": 0.20, "versatility": 0.10}

# ΔE at/above which a product colour scores ~0 on the distance component.
_DELTA_E_MAX = 45.0

# Tokens that carry no discriminative styling meaning when matching archetypes.
_GENERIC = {"and", "the", "with", "a", "of", "most", "styles", "style", "fit"}
# Generic qualifiers stripped from "avoid" phrases before deciding a hard filter.
_GENERIC_AVOID = {"big", "low", "very", "heavy", "worn"}


# =========================================================================== #
# small token helpers (free-form archetype / attribute strings)               #
# =========================================================================== #
def _tokens(*parts) -> set:
    out = set()
    for p in parts:
        if not p:
            continue
        if isinstance(p, (list, tuple, set)):
            for x in p:
                out |= _tokens(x)
            continue
        cur = ""
        for ch in str(p).lower():
            if ch.isalnum():
                cur += ch
            else:
                if cur:
                    out.add(cur)
                cur = ""
        if cur:
            out.add(cur)
    return {t for t in out if t not in _GENERIC}


def _coverage(product_tokens: set, phrase: str) -> float:
    """Fraction of ``phrase``'s meaningful tokens present in ``product_tokens``."""
    pt = _tokens(phrase)
    if not pt:
        return 0.0
    return len(product_tokens & pt) / len(pt)


def _best_coverage(product_tokens: set, phrases) -> float:
    return max((_coverage(product_tokens, p) for p in phrases), default=0.0)


# =========================================================================== #
# §4.1 -> MatchProfile                                                         #
# =========================================================================== #
def _resolve_palette_strategy(coloring) -> str:
    """Pick a §4.1 palette key from undertone/season, with the safe fallback."""
    # Graceful degradation: a robust "good" beats a confident "wrong".
    if coloring.undertone_confidence < 0.5:
        return "safe-universal"
    u, s = coloring.skin_undertone, coloring.season
    if u == "warm":
        return "warm-spring" if s == "spring" else "warm-autumn"
    if u == "cool":
        return "cool-summer" if s == "summer" else "cool-winter"
    # olive / neutral -> safe-universal (per §4.1 table)
    return "safe-universal"


def _vibe_weights(tags) -> dict:
    """Normalise a ranked vibe list into weights summing to 1 (first = heaviest)."""
    seen, ordered = set(), []
    for t in tags:
        if t and t not in seen:
            seen.add(t)
            ordered.append(t)
    if not ordered:
        return {"casual": 1.0}
    n = len(ordered)
    raw = {t: (n - i) for i, t in enumerate(ordered)}
    total = float(sum(raw.values()))
    return {t: w / total for t, w in raw.items()}


def build_match_profile(profile: schemas.StyleProfile) -> schemas.MatchProfile:
    """Apply the §4.1 rule tables to a StyleProfile → a MatchProfile query.

    No LLM. Uses the safe-universal palette (palette_strategy="safe-universal")
    when ``coloring.undertone_confidence < 0.5``; otherwise an undertone/season
    strategy such as "warm-autumn". contrast_strategy comes from contrast_level.
    """
    coloring, face, build, person = (
        profile.coloring, profile.face, profile.build, profile.person,
    )

    strategy = _resolve_palette_strategy(coloring)
    palette = [
        {"name": n, "hex": hx, "family": fam}
        for (n, hx, fam) in PALETTES[strategy]["wear"]
    ]

    hat_rules = FACE_SHAPE_HAT.get(face.shape, FACE_SHAPE_HAT["oval"])
    tee_rules = BUILD_TSHIRT.get(build.type, BUILD_TSHIRT["average"])

    # necklines = build base ∪ neck-length rule ∪ face-shape rule (deduped, order-stable)
    necklines, seen = [], set()
    for src in (tee_rules["necklines_ok"],
                NECK_NECKLINE.get(face.neck_length, []),
                FACE_NECKLINE.get(face.shape, [])):
        for nl in src:
            if nl not in seen:
                seen.add(nl)
                necklines.append(nl)

    match_dict = {
        "palette": palette,
        "palette_strategy": strategy,
        "contrast_strategy": CONTRAST_STRATEGY.get(coloring.contrast_level, "tonal"),
        "hat": {
            "archetypes_ok": list(hat_rules["recommend"]),
            "archetypes_avoid": list(hat_rules["avoid"]),
            "scale": "regular",
        },
        "tshirt": {
            "fits_ok": list(tee_rules["fits_ok"]),
            "necklines_ok": necklines,
            "avoid": list(tee_rules["avoid"]),
        },
        "vibe": _vibe_weights(profile.current_style.detected_vibe),
        "presentation_filter": person.presentation,
        "skin_depth": coloring.skin_depth,
    }
    # Build through from_dict so the contract (enums/hex/ranges) is re-validated.
    return schemas.MatchProfile.from_dict(match_dict)


# =========================================================================== #
# §3 feasibility gate (recommend.py will use this to drop a category)         #
# =========================================================================== #
def feasible_categories(profile: schemas.StyleProfile) -> set:
    """Categories the photo can actually support a try-on for, from §3.1's
    ``tryon_feasibility``. MatchProfile itself has no feasibility field (the
    contract is intentionally kept intact); recommend() reads this set to drop
    an infeasible category before scoring.
    """
    feas = profile.tryon_feasibility
    out = set()
    if feas.hat:
        out.add("hat")
    if feas.tshirt:
        out.add("tshirt")
    return out


# =========================================================================== #
# §4.3 scoring                                                                 #
# =========================================================================== #
# value (light|mid|dark) suitability per skin_depth (light|medium|deep).
_VALUE_SKIN = {
    "light":  {"light": 0.6, "mid": 1.0, "dark": 0.9},
    "medium": {"light": 0.9, "mid": 1.0, "dark": 0.9},
    "deep":   {"light": 1.0, "mid": 1.0, "dark": 0.85},
}
# saturation obeys contrast_strategy.
_CONTRAST_SAT = {
    "tonal": {"muted": 1.0, "mid": 0.8, "bright": 0.5},
    "bold":  {"muted": 0.7, "mid": 0.9, "bright": 1.0},
}


def _colour_axis(match: schemas.MatchProfile, product: schemas.CatalogProduct):
    """ΔE-to-nearest-palette + family + value-vs-skin + contrast → raw [0,1]."""
    phex = product.color.hex
    nearest, best_de = None, float("inf")
    for pc in match.palette:
        de = _color.delta_e_hex(phex, pc.hex)
        if de < best_de:
            best_de, nearest = de, pc
    de_score = max(0.0, 1.0 - best_de / _DELTA_E_MAX)

    families = {pc.family for pc in match.palette}
    if nearest is not None and product.color.family == nearest.family:
        family_match = 1.0
    elif product.color.family in families:
        family_match = 0.5
    else:
        family_match = 0.0

    value_score = _VALUE_SKIN.get(match.skin_depth, _VALUE_SKIN["medium"]).get(
        product.color.value, 0.8)
    contrast_obey = _CONTRAST_SAT.get(match.contrast_strategy, _CONTRAST_SAT["tonal"]).get(
        product.color.saturation, 0.8)

    raw = 0.55 * de_score + 0.20 * family_match + 0.15 * value_score + 0.10 * contrast_obey
    reason = (f"colour: ΔE {best_de:.1f} to {nearest.name if nearest else '?'} "
              f"({match.palette_strategy} palette), "
              f"{product.color.family}-family {product.color.value}/{product.color.saturation}")
    return raw, reason


def _shape_axis(match: schemas.MatchProfile, product: schemas.CatalogProduct):
    """Category-aware shape fit → raw [0,1]. (avoid is already hard-filtered.)"""
    ptoks = _tokens(product.archetype, product.title)
    if product.category == "hat":
        cov = _best_coverage(ptoks, match.hat.archetypes_ok)
        if cov >= 0.5:
            raw, note = 1.0, f"shape: archetype matches recommended ({match.hat.scale})"
        elif cov > 0.0:
            raw, note = 0.6, "shape: partial match to recommended hat archetypes"
        else:
            raw, note = 0.3, "shape: neutral — not a recommended hat archetype"
        return raw, note
    # tshirt: fit ∈ fits_ok, neckline ∈ necklines_ok
    fit_ok = any(_tokens(f) & ptoks for f in match.tshirt.fits_ok)
    neck_ok = any(_tokens(n) & ptoks for n in match.tshirt.necklines_ok)
    raw = 0.5 * (1.0 if fit_ok else 0.4) + 0.5 * (1.0 if neck_ok else 0.5)
    note = ("shape: fit "
            + ("flatters build" if fit_ok else "neutral")
            + ", neckline "
            + ("suits face/neck" if neck_ok else "neutral"))
    return raw, note


def _vibe_axis(match: schemas.MatchProfile, product: schemas.CatalogProduct):
    """cosine(product style_tags one-hot, match.vibe weights) → raw [0,1]."""
    vocab = set(match.vibe) | set(product.style_tags)
    if not vocab:
        return 0.0, "vibe: no tags to compare"
    pset = set(product.style_tags)
    dot = sum(match.vibe.get(t, 0.0) * (1.0 if t in pset else 0.0) for t in vocab)
    mag_m = math.sqrt(sum(w * w for w in match.vibe.values()))
    mag_p = math.sqrt(float(len(pset)))
    raw = dot / (mag_m * mag_p) if mag_m > 0 and mag_p > 0 else 0.0
    overlap = sorted(set(match.vibe) & pset)
    note = (f"vibe: matches {', '.join(overlap)}" if overlap
            else "vibe: outside stated taste")
    return raw, note


def _versatility_axis(product: schemas.CatalogProduct):
    """formality fit + solid>busy tiebreak → raw [0,1]."""
    solid = (product.pattern in ("solid", "none", "")
             or product.pattern_scale in ("none", "")) and product.pattern != "bold-graphic"
    solid_score = 1.0 if solid else 0.6
    formality_score = {1: 0.8, 2: 1.0, 3: 0.9, 4: 0.7, 5: 0.5}.get(product.formality, 0.8)
    raw = 0.6 * solid_score + 0.4 * formality_score
    note = ("versatility: solid + " if solid else "versatility: patterned + ") + \
           f"formality {product.formality}"
    return raw, note


def _hard_filters(match: schemas.MatchProfile, product: schemas.CatalogProduct, feasible: bool):
    """Return a list of hard-filter reasons (empty → product passes)."""
    reasons = []

    if not feasible:
        reasons.append("infeasible category for this photo")

    # wrong presentation (and not unisex). androgynous filter accepts anything.
    pf = match.presentation_filter
    if pf in ("masculine", "feminine") and product.presentation not in (pf, "unisex"):
        reasons.append(f"presentation {product.presentation} != filter {pf}")

    # no size available
    if not product.sizes:
        reasons.append("no size available")

    ptoks = _tokens(product.archetype, product.pattern, product.pattern_scale,
                    product.style_tags, product.title)

    if product.category == "hat":
        # archetype ∈ archetypes_avoid
        for av in match.hat.archetypes_avoid:
            if _coverage(ptoks, av) >= 0.5:
                reasons.append(f"hat archetype in avoid: {av}")
                break
    else:
        # product attribute ∈ tshirt.avoid
        for av in match.tshirt.avoid:
            distinctive = _tokens(av) - _GENERIC_AVOID
            if distinctive and (ptoks & distinctive):
                reasons.append(f"attribute in tshirt.avoid: {av}")
                break

    return reasons


def score_product(match: schemas.MatchProfile, product: schemas.CatalogProduct,
                  *, feasible: bool = True) -> dict:
    """Hard-filter then weighted-score a product against a MatchProfile (§4.3).

    Returns::

        {
          "score": float in [0,100],
          "breakdown": {"colour","shape","vibe","versatility"},  # WEIGHTED contributions
          "hard_filtered": bool,
          "reasons": [str, ...],
        }

    Each breakdown value is the axis' weighted contribution (raw*weight) in
    [0,1]; the four sum to ``score/100`` so the result is fully explainable.
    Weights: colour .40 / shape .30 / vibe .20 / versatility .10.
    """
    filtered = _hard_filters(match, product, feasible)
    if filtered:
        return {
            "score": 0.0,
            "breakdown": {"colour": 0.0, "shape": 0.0, "vibe": 0.0, "versatility": 0.0},
            "hard_filtered": True,
            "reasons": [f"HARD FILTER: {r}" for r in filtered],
        }

    colour_raw, colour_reason = _colour_axis(match, product)
    shape_raw, shape_reason = _shape_axis(match, product)
    vibe_raw, vibe_reason = _vibe_axis(match, product)
    vers_raw, vers_reason = _versatility_axis(product)

    breakdown = {
        "colour": WEIGHTS["colour"] * colour_raw,
        "shape": WEIGHTS["shape"] * shape_raw,
        "vibe": WEIGHTS["vibe"] * vibe_raw,
        "versatility": WEIGHTS["versatility"] * vers_raw,
    }
    score = 100.0 * sum(breakdown.values())

    return {
        "score": round(score, 2),
        "breakdown": {k: round(v, 4) for k, v in breakdown.items()},
        "hard_filtered": False,
        "reasons": [colour_reason, shape_reason, vibe_reason, vers_reason],
    }


# =========================================================================== #
# §4.4 outfit harmony (two-garment colour relationship)                       #
# =========================================================================== #
def outfit_harmony(hat_hex: str, tee_hex: str, contrast_strategy: str) -> float:
    """Colour harmony between a hat and tee hex, ∈ [0,1], respecting strategy.

    Rewards tonal/monochrome, analogous (≤30°) and balanced complementary;
    penalises two competing saturated hues. A low-contrast (tonal) person is
    nudged toward tonal looks; a bold strategy tolerates a contrast pairing.
    """
    h1, h2 = _color.hue_deg(hat_hex), _color.hue_deg(tee_hex)
    s1, s2 = _color.saturation(hat_hex), _color.saturation(tee_hex)
    hd = _color.hue_distance(h1, h2)

    neutralish = min(s1, s2) < 0.18      # at least one near-neutral anchor
    both_sat = s1 >= 0.35 and s2 >= 0.35

    if neutralish:
        base, rel = 0.85, "neutral-anchored"
    elif hd <= 15.0:
        base, rel = 0.92, "tonal"
    elif hd <= 30.0:
        base, rel = 0.82, "analogous"
    elif hd >= 150.0:
        base, rel = (0.72 if both_sat else 0.80), "complementary"
    else:
        base, rel = (0.40 if both_sat else 0.62), "clash"

    if contrast_strategy == "tonal":
        if rel in ("tonal", "analogous", "neutral-anchored"):
            base += 0.06
        elif rel == "complementary":
            base -= 0.18
        elif rel == "clash":
            base -= 0.12
    else:  # bold
        if rel == "complementary":
            base += 0.10
        elif rel == "clash":
            base += 0.05

    return max(0.0, min(1.0, base))


__all__ = [
    "FACE_SHAPE_HAT", "PALETTES", "CONTRAST_STRATEGY", "BUILD_TSHIRT",
    "NECK_NECKLINE", "FACE_NECKLINE", "WEIGHTS",
    "build_match_profile", "feasible_categories", "score_product", "outfit_harmony",
]
