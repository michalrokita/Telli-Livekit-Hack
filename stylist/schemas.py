"""stylist.schemas — the data contract (THE seam handed to the partner).

Every model in the styling engine, as plain stdlib ``@dataclass`` objects.
No pydantic, no numpy, no LiveKit, no network — pure data + validation.

Each model exposes:
  * ``Model.from_dict(d) -> Model`` — strict: unknown enum value -> ValueError,
    every ``*_confidence`` / 0..1 score validated in range, required fields
    must be present, hex colours must be ``#rrggbb``.
  * ``model.to_dict() -> dict`` — round-trippable (``from_dict(m.to_dict())`` re-validates).

Source of truth: ``stylist-engine-algorithm.md`` §3.1, §4.2, §4.3/§4.4, §5.3.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# --------------------------------------------------------------------------- #
# Enum value sets (single source per concept; reused across models).          #
# --------------------------------------------------------------------------- #
_ISSUES = frozenset(
    {"low_light", "motion_blur", "face_occluded", "torso_not_visible", "strong_color_cast"}
)
_FRAMING = frozenset({"head_only", "head_and_torso", "full_body"})
_WB_CAST = frozenset({"warm", "cool", "neutral", "unknown"})
_PERSON_PRESENTATION = frozenset({"masculine", "feminine", "androgynous"})
_PRODUCT_PRESENTATION = frozenset({"masculine", "feminine", "unisex"})
_UNDERTONE = frozenset({"warm", "cool", "neutral", "olive"})
_SKIN_DEPTH = frozenset({"light", "medium", "deep"})
_CONTRAST_LEVEL = frozenset({"high", "medium", "low"})
_SEASON = frozenset({"spring", "summer", "autumn", "winter", "unknown"})
_FACE_SHAPE = frozenset({"oval", "round", "square", "heart", "oblong", "diamond"})
_NECK_LENGTH = frozenset({"short", "average", "long"})
_BUILD_TYPE = frozenset({"slim", "athletic", "average", "broad", "fuller"})
_SHOULDER = frozenset({"narrow", "average", "broad"})
_COLOR_FAMILY = frozenset({"warm", "cool", "neutral"})
_COLOR_VALUE = frozenset({"light", "mid", "dark"})
_SATURATION = frozenset({"muted", "mid", "bright"})
_CATEGORY = frozenset({"hat", "tshirt"})
_CONTRAST_STRATEGY = frozenset({"bold", "tonal"})
_TRYON_STATUS = frozenset({"pending", "pass", "retry", "low_confidence", "error"})
_VERDICT = frozenset({"pass", "retry"})

_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


# --------------------------------------------------------------------------- #
# Tiny shared validation helpers. `from_dict` is built out of these.          #
# --------------------------------------------------------------------------- #
def _req(d: dict, key: str, field: str | None = None):
    """Fetch a required key; raise ValueError (not KeyError) if missing."""
    if not isinstance(d, dict):
        raise ValueError(f"{field or key}: expected an object, got {type(d).__name__}")
    if key not in d:
        raise ValueError(f"missing required field: {field or key}")
    return d[key]


def _enum(value, allowed: frozenset, field: str):
    if value not in allowed:
        raise ValueError(f"{field}: {value!r} not one of {sorted(allowed)}")
    return value


def _unit(value, field: str) -> float:
    """Validate a confidence / 0..1 score."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field}: expected a number in [0,1], got {type(value).__name__}")
    v = float(value)
    if not 0.0 <= v <= 1.0:
        raise ValueError(f"{field}: {v} is outside [0,1]")
    return v


def _score100(value, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field}: expected a number in [0,100], got {type(value).__name__}")
    v = float(value)
    if not 0.0 <= v <= 100.0:
        raise ValueError(f"{field}: {v} is outside [0,100]")
    return v


def _hex(value, field: str) -> str:
    if not isinstance(value, str) or not _HEX_RE.match(value):
        raise ValueError(f"{field}: {value!r} is not a #rrggbb hex colour")
    return value


def _number(value, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field}: expected a number, got {type(value).__name__}")
    return float(value)


def _bool(value, field: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{field}: expected a bool, got {type(value).__name__}")
    return value


def _str(value, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field}: expected a str, got {type(value).__name__}")
    return value


def _str_list(value, field: str) -> list:
    if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
        raise ValueError(f"{field}: expected a list[str]")
    return list(value)


def _enum_list(value, allowed: frozenset, field: str) -> list:
    items = _str_list(value, field)
    for it in items:
        _enum(it, allowed, f"{field}[]")
    return items


def _int_range(value, lo: int, hi: int, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field}: expected an int, got {type(value).__name__}")
    if not lo <= value <= hi:
        raise ValueError(f"{field}: {value} is outside [{lo},{hi}]")
    return value


def _nonneg_int(value, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field}: expected an int, got {type(value).__name__}")
    if value < 0:
        raise ValueError(f"{field}: {value} must be >= 0")
    return value


def _str_float_dict(value, field: str) -> dict:
    if not isinstance(value, dict):
        raise ValueError(f"{field}: expected a dict[str,float]")
    out: dict = {}
    for k, v in value.items():
        if not isinstance(k, str):
            raise ValueError(f"{field}: keys must be str")
        out[k] = _number(v, f"{field}[{k!r}]")
    return out


# =========================================================================== #
# StyleProfile (§3.1)                                                          #
# =========================================================================== #
@dataclass
class ImageQuality:
    usable: bool
    issues: list  # subset of _ISSUES
    framing: str  # _FRAMING
    white_balance_cast: str  # _WB_CAST
    wb_confidence: float  # [0,1]

    @classmethod
    def from_dict(cls, d: dict) -> "ImageQuality":
        f = "image_quality"
        return cls(
            usable=_bool(_req(d, "usable", f"{f}.usable"), f"{f}.usable"),
            issues=_enum_list(_req(d, "issues", f"{f}.issues"), _ISSUES, f"{f}.issues"),
            framing=_enum(_req(d, "framing", f"{f}.framing"), _FRAMING, f"{f}.framing"),
            white_balance_cast=_enum(
                _req(d, "white_balance_cast", f"{f}.white_balance_cast"),
                _WB_CAST,
                f"{f}.white_balance_cast",
            ),
            wb_confidence=_unit(
                _req(d, "wb_confidence", f"{f}.wb_confidence"), f"{f}.wb_confidence"
            ),
        )

    def to_dict(self) -> dict:
        return {
            "usable": self.usable,
            "issues": list(self.issues),
            "framing": self.framing,
            "white_balance_cast": self.white_balance_cast,
            "wb_confidence": self.wb_confidence,
        }


@dataclass
class Person:
    apparent_age_range: str
    presentation: str  # _PERSON_PRESENTATION (catalog filter, not identity)
    presentation_confidence: float  # [0,1]

    @classmethod
    def from_dict(cls, d: dict) -> "Person":
        f = "person"
        return cls(
            apparent_age_range=_str(
                _req(d, "apparent_age_range", f"{f}.apparent_age_range"),
                f"{f}.apparent_age_range",
            ),
            presentation=_enum(
                _req(d, "presentation", f"{f}.presentation"),
                _PERSON_PRESENTATION,
                f"{f}.presentation",
            ),
            presentation_confidence=_unit(
                _req(d, "presentation_confidence", f"{f}.presentation_confidence"),
                f"{f}.presentation_confidence",
            ),
        )

    def to_dict(self) -> dict:
        return {
            "apparent_age_range": self.apparent_age_range,
            "presentation": self.presentation,
            "presentation_confidence": self.presentation_confidence,
        }


@dataclass
class Coloring:
    skin_undertone: str  # _UNDERTONE
    undertone_cues: list
    undertone_confidence: float  # [0,1]
    skin_depth: str  # _SKIN_DEPTH
    hair_color: str
    eye_color: str
    contrast_level: str  # _CONTRAST_LEVEL
    season: str  # _SEASON
    season_confidence: float  # [0,1]

    @classmethod
    def from_dict(cls, d: dict) -> "Coloring":
        f = "coloring"
        return cls(
            skin_undertone=_enum(
                _req(d, "skin_undertone", f"{f}.skin_undertone"), _UNDERTONE, f"{f}.skin_undertone"
            ),
            undertone_cues=_str_list(
                _req(d, "undertone_cues", f"{f}.undertone_cues"), f"{f}.undertone_cues"
            ),
            undertone_confidence=_unit(
                _req(d, "undertone_confidence", f"{f}.undertone_confidence"),
                f"{f}.undertone_confidence",
            ),
            skin_depth=_enum(
                _req(d, "skin_depth", f"{f}.skin_depth"), _SKIN_DEPTH, f"{f}.skin_depth"
            ),
            hair_color=_str(_req(d, "hair_color", f"{f}.hair_color"), f"{f}.hair_color"),
            eye_color=_str(_req(d, "eye_color", f"{f}.eye_color"), f"{f}.eye_color"),
            contrast_level=_enum(
                _req(d, "contrast_level", f"{f}.contrast_level"),
                _CONTRAST_LEVEL,
                f"{f}.contrast_level",
            ),
            season=_enum(_req(d, "season", f"{f}.season"), _SEASON, f"{f}.season"),
            season_confidence=_unit(
                _req(d, "season_confidence", f"{f}.season_confidence"), f"{f}.season_confidence"
            ),
        )

    def to_dict(self) -> dict:
        return {
            "skin_undertone": self.skin_undertone,
            "undertone_cues": list(self.undertone_cues),
            "undertone_confidence": self.undertone_confidence,
            "skin_depth": self.skin_depth,
            "hair_color": self.hair_color,
            "eye_color": self.eye_color,
            "contrast_level": self.contrast_level,
            "season": self.season,
            "season_confidence": self.season_confidence,
        }


@dataclass
class Face:
    shape: str  # _FACE_SHAPE
    shape_confidence: float  # [0,1]
    neck_length: str  # _NECK_LENGTH
    notable_features: list

    @classmethod
    def from_dict(cls, d: dict) -> "Face":
        f = "face"
        return cls(
            shape=_enum(_req(d, "shape", f"{f}.shape"), _FACE_SHAPE, f"{f}.shape"),
            shape_confidence=_unit(
                _req(d, "shape_confidence", f"{f}.shape_confidence"), f"{f}.shape_confidence"
            ),
            neck_length=_enum(
                _req(d, "neck_length", f"{f}.neck_length"), _NECK_LENGTH, f"{f}.neck_length"
            ),
            notable_features=_str_list(
                _req(d, "notable_features", f"{f}.notable_features"), f"{f}.notable_features"
            ),
        )

    def to_dict(self) -> dict:
        return {
            "shape": self.shape,
            "shape_confidence": self.shape_confidence,
            "neck_length": self.neck_length,
            "notable_features": list(self.notable_features),
        }


@dataclass
class Build:
    type: str  # _BUILD_TYPE
    shoulder_width: str  # _SHOULDER
    build_confidence: float  # [0,1]

    @classmethod
    def from_dict(cls, d: dict) -> "Build":
        f = "build"
        return cls(
            type=_enum(_req(d, "type", f"{f}.type"), _BUILD_TYPE, f"{f}.type"),
            shoulder_width=_enum(
                _req(d, "shoulder_width", f"{f}.shoulder_width"), _SHOULDER, f"{f}.shoulder_width"
            ),
            build_confidence=_unit(
                _req(d, "build_confidence", f"{f}.build_confidence"), f"{f}.build_confidence"
            ),
        )

    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "shoulder_width": self.shoulder_width,
            "build_confidence": self.build_confidence,
        }


@dataclass
class CurrentStyle:
    detected_vibe: list
    currently_wearing: str
    accessories: list

    @classmethod
    def from_dict(cls, d: dict) -> "CurrentStyle":
        f = "current_style"
        return cls(
            detected_vibe=_str_list(
                _req(d, "detected_vibe", f"{f}.detected_vibe"), f"{f}.detected_vibe"
            ),
            currently_wearing=_str(
                _req(d, "currently_wearing", f"{f}.currently_wearing"), f"{f}.currently_wearing"
            ),
            accessories=_str_list(
                _req(d, "accessories", f"{f}.accessories"), f"{f}.accessories"
            ),
        )

    def to_dict(self) -> dict:
        return {
            "detected_vibe": list(self.detected_vibe),
            "currently_wearing": self.currently_wearing,
            "accessories": list(self.accessories),
        }


@dataclass
class TryOnFeasibility:
    hat: bool
    tshirt: bool

    @classmethod
    def from_dict(cls, d: dict) -> "TryOnFeasibility":
        f = "tryon_feasibility"
        return cls(
            hat=_bool(_req(d, "hat", f"{f}.hat"), f"{f}.hat"),
            tshirt=_bool(_req(d, "tshirt", f"{f}.tshirt"), f"{f}.tshirt"),
        )

    def to_dict(self) -> dict:
        return {"hat": self.hat, "tshirt": self.tshirt}


@dataclass
class StyleProfile:
    image_quality: ImageQuality
    person: Person
    coloring: Coloring
    face: Face
    build: Build
    current_style: CurrentStyle
    tryon_feasibility: TryOnFeasibility

    @classmethod
    def from_dict(cls, d: dict) -> "StyleProfile":
        return cls(
            image_quality=ImageQuality.from_dict(
                _req(d, "image_quality", "image_quality")
            ),
            person=Person.from_dict(_req(d, "person", "person")),
            coloring=Coloring.from_dict(_req(d, "coloring", "coloring")),
            face=Face.from_dict(_req(d, "face", "face")),
            build=Build.from_dict(_req(d, "build", "build")),
            current_style=CurrentStyle.from_dict(
                _req(d, "current_style", "current_style")
            ),
            tryon_feasibility=TryOnFeasibility.from_dict(
                _req(d, "tryon_feasibility", "tryon_feasibility")
            ),
        )

    def to_dict(self) -> dict:
        return {
            "image_quality": self.image_quality.to_dict(),
            "person": self.person.to_dict(),
            "coloring": self.coloring.to_dict(),
            "face": self.face.to_dict(),
            "build": self.build.to_dict(),
            "current_style": self.current_style.to_dict(),
            "tryon_feasibility": self.tryon_feasibility.to_dict(),
        }


# =========================================================================== #
# CatalogProduct (§4.2)                                                        #
# =========================================================================== #
@dataclass
class ProductColor:
    name: str
    hex: str  # #rrggbb
    family: str  # _COLOR_FAMILY
    value: str  # _COLOR_VALUE
    saturation: str  # _SATURATION

    @classmethod
    def from_dict(cls, d: dict) -> "ProductColor":
        f = "color"
        return cls(
            name=_str(_req(d, "name", f"{f}.name"), f"{f}.name"),
            hex=_hex(_req(d, "hex", f"{f}.hex"), f"{f}.hex"),
            family=_enum(_req(d, "family", f"{f}.family"), _COLOR_FAMILY, f"{f}.family"),
            value=_enum(_req(d, "value", f"{f}.value"), _COLOR_VALUE, f"{f}.value"),
            saturation=_enum(
                _req(d, "saturation", f"{f}.saturation"), _SATURATION, f"{f}.saturation"
            ),
        )

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "hex": self.hex,
            "family": self.family,
            "value": self.value,
            "saturation": self.saturation,
        }


@dataclass
class CatalogProduct:
    id: str
    category: str  # _CATEGORY
    title: str
    price: float
    sizes: list
    image_url: str
    archetype: str
    color: ProductColor
    pattern: str
    pattern_scale: str
    style_tags: list
    formality: int  # 1..5
    presentation: str  # _PRODUCT_PRESENTATION

    @classmethod
    def from_dict(cls, d: dict) -> "CatalogProduct":
        return cls(
            id=_str(_req(d, "id"), "id"),
            category=_enum(_req(d, "category"), _CATEGORY, "category"),
            title=_str(_req(d, "title"), "title"),
            price=_number(_req(d, "price"), "price"),
            sizes=_str_list(_req(d, "sizes"), "sizes"),
            image_url=_str(_req(d, "image_url"), "image_url"),
            archetype=_str(_req(d, "archetype"), "archetype"),
            color=ProductColor.from_dict(_req(d, "color")),
            pattern=_str(_req(d, "pattern"), "pattern"),
            pattern_scale=_str(_req(d, "pattern_scale"), "pattern_scale"),
            style_tags=_str_list(_req(d, "style_tags"), "style_tags"),
            formality=_int_range(_req(d, "formality"), 1, 5, "formality"),
            presentation=_enum(
                _req(d, "presentation"), _PRODUCT_PRESENTATION, "presentation"
            ),
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "category": self.category,
            "title": self.title,
            "price": self.price,
            "sizes": list(self.sizes),
            "image_url": self.image_url,
            "archetype": self.archetype,
            "color": self.color.to_dict(),
            "pattern": self.pattern,
            "pattern_scale": self.pattern_scale,
            "style_tags": list(self.style_tags),
            "formality": self.formality,
            "presentation": self.presentation,
        }


# =========================================================================== #
# MatchProfile (§4.2) — the deterministic query derived from a StyleProfile.   #
# =========================================================================== #
@dataclass
class PaletteColor:
    name: str
    hex: str  # #rrggbb
    family: str  # _COLOR_FAMILY

    @classmethod
    def from_dict(cls, d: dict) -> "PaletteColor":
        f = "palette[]"
        return cls(
            name=_str(_req(d, "name", f"{f}.name"), f"{f}.name"),
            hex=_hex(_req(d, "hex", f"{f}.hex"), f"{f}.hex"),
            family=_enum(_req(d, "family", f"{f}.family"), _COLOR_FAMILY, f"{f}.family"),
        )

    def to_dict(self) -> dict:
        return {"name": self.name, "hex": self.hex, "family": self.family}


@dataclass
class MatchHat:
    archetypes_ok: list
    archetypes_avoid: list
    scale: str

    @classmethod
    def from_dict(cls, d: dict) -> "MatchHat":
        f = "hat"
        return cls(
            archetypes_ok=_str_list(
                _req(d, "archetypes_ok", f"{f}.archetypes_ok"), f"{f}.archetypes_ok"
            ),
            archetypes_avoid=_str_list(
                _req(d, "archetypes_avoid", f"{f}.archetypes_avoid"), f"{f}.archetypes_avoid"
            ),
            scale=_str(_req(d, "scale", f"{f}.scale"), f"{f}.scale"),
        )

    def to_dict(self) -> dict:
        return {
            "archetypes_ok": list(self.archetypes_ok),
            "archetypes_avoid": list(self.archetypes_avoid),
            "scale": self.scale,
        }


@dataclass
class MatchTshirt:
    fits_ok: list
    necklines_ok: list
    avoid: list

    @classmethod
    def from_dict(cls, d: dict) -> "MatchTshirt":
        f = "tshirt"
        return cls(
            fits_ok=_str_list(_req(d, "fits_ok", f"{f}.fits_ok"), f"{f}.fits_ok"),
            necklines_ok=_str_list(
                _req(d, "necklines_ok", f"{f}.necklines_ok"), f"{f}.necklines_ok"
            ),
            avoid=_str_list(_req(d, "avoid", f"{f}.avoid"), f"{f}.avoid"),
        )

    def to_dict(self) -> dict:
        return {
            "fits_ok": list(self.fits_ok),
            "necklines_ok": list(self.necklines_ok),
            "avoid": list(self.avoid),
        }


@dataclass
class MatchProfile:
    palette: list  # list[PaletteColor]
    palette_strategy: str
    contrast_strategy: str  # _CONTRAST_STRATEGY
    hat: MatchHat
    tshirt: MatchTshirt
    vibe: dict  # dict[str,float]
    presentation_filter: str
    skin_depth: str  # _SKIN_DEPTH

    @classmethod
    def from_dict(cls, d: dict) -> "MatchProfile":
        palette_raw = _req(d, "palette", "palette")
        if not isinstance(palette_raw, list):
            raise ValueError("palette: expected a list")
        return cls(
            palette=[PaletteColor.from_dict(p) for p in palette_raw],
            palette_strategy=_str(
                _req(d, "palette_strategy"), "palette_strategy"
            ),
            contrast_strategy=_enum(
                _req(d, "contrast_strategy"), _CONTRAST_STRATEGY, "contrast_strategy"
            ),
            hat=MatchHat.from_dict(_req(d, "hat")),
            tshirt=MatchTshirt.from_dict(_req(d, "tshirt")),
            vibe=_str_float_dict(_req(d, "vibe"), "vibe"),
            presentation_filter=_str(
                _req(d, "presentation_filter"), "presentation_filter"
            ),
            skin_depth=_enum(_req(d, "skin_depth"), _SKIN_DEPTH, "skin_depth"),
        )

    def to_dict(self) -> dict:
        return {
            "palette": [p.to_dict() for p in self.palette],
            "palette_strategy": self.palette_strategy,
            "contrast_strategy": self.contrast_strategy,
            "hat": self.hat.to_dict(),
            "tshirt": self.tshirt.to_dict(),
            "vibe": dict(self.vibe),
            "presentation_filter": self.presentation_filter,
            "skin_depth": self.skin_depth,
        }


# =========================================================================== #
# recommend() output (§4.3 / §4.4)                                            #
# =========================================================================== #
@dataclass
class ScoreBreakdown:
    """Each field is the weighted CONTRIBUTION to the final score, in [0,1]."""

    colour: float
    shape: float
    vibe: float
    versatility: float

    @classmethod
    def from_dict(cls, d: dict) -> "ScoreBreakdown":
        f = "breakdown"
        return cls(
            colour=_unit(_req(d, "colour", f"{f}.colour"), f"{f}.colour"),
            shape=_unit(_req(d, "shape", f"{f}.shape"), f"{f}.shape"),
            vibe=_unit(_req(d, "vibe", f"{f}.vibe"), f"{f}.vibe"),
            versatility=_unit(_req(d, "versatility", f"{f}.versatility"), f"{f}.versatility"),
        )

    def to_dict(self) -> dict:
        return {
            "colour": self.colour,
            "shape": self.shape,
            "vibe": self.vibe,
            "versatility": self.versatility,
        }


@dataclass
class RecommendOption:
    product_id: str
    category: str  # _CATEGORY
    title: str
    color_hex: str  # #rrggbb
    price: float
    sizes: list
    score: float  # 0..100
    breakdown: ScoreBreakdown
    rationale: str  # may be ""

    @classmethod
    def from_dict(cls, d: dict) -> "RecommendOption":
        return cls(
            product_id=_str(_req(d, "product_id"), "product_id"),
            category=_enum(_req(d, "category"), _CATEGORY, "category"),
            title=_str(_req(d, "title"), "title"),
            color_hex=_hex(_req(d, "color_hex"), "color_hex"),
            price=_number(_req(d, "price"), "price"),
            sizes=_str_list(_req(d, "sizes"), "sizes"),
            score=_score100(_req(d, "score"), "score"),
            breakdown=ScoreBreakdown.from_dict(_req(d, "breakdown")),
            rationale=_str(_req(d, "rationale"), "rationale"),
        )

    def to_dict(self) -> dict:
        return {
            "product_id": self.product_id,
            "category": self.category,
            "title": self.title,
            "color_hex": self.color_hex,
            "price": self.price,
            "sizes": list(self.sizes),
            "score": self.score,
            "breakdown": self.breakdown.to_dict(),
            "rationale": self.rationale,
        }


@dataclass
class OutfitCombo:
    hat_id: str
    tshirt_id: str
    harmony_score: float  # [0,1]
    individual_quality: float  # [0,1]
    style_coherence: float  # [0,1]
    rationale: str

    @classmethod
    def from_dict(cls, d: dict) -> "OutfitCombo":
        return cls(
            hat_id=_str(_req(d, "hat_id"), "hat_id"),
            tshirt_id=_str(_req(d, "tshirt_id"), "tshirt_id"),
            harmony_score=_unit(_req(d, "harmony_score"), "harmony_score"),
            individual_quality=_unit(_req(d, "individual_quality"), "individual_quality"),
            style_coherence=_unit(_req(d, "style_coherence"), "style_coherence"),
            rationale=_str(_req(d, "rationale"), "rationale"),
        )

    def to_dict(self) -> dict:
        return {
            "hat_id": self.hat_id,
            "tshirt_id": self.tshirt_id,
            "harmony_score": self.harmony_score,
            "individual_quality": self.individual_quality,
            "style_coherence": self.style_coherence,
            "rationale": self.rationale,
        }


@dataclass
class Options:
    hats: list  # list[RecommendOption]
    tshirts: list  # list[RecommendOption]
    combos: list  # list[OutfitCombo]

    @classmethod
    def from_dict(cls, d: dict) -> "Options":
        hats_raw = _req(d, "hats", "hats")
        tshirts_raw = _req(d, "tshirts", "tshirts")
        combos_raw = _req(d, "combos", "combos")
        for name, raw in (("hats", hats_raw), ("tshirts", tshirts_raw), ("combos", combos_raw)):
            if not isinstance(raw, list):
                raise ValueError(f"{name}: expected a list")
        return cls(
            hats=[RecommendOption.from_dict(x) for x in hats_raw],
            tshirts=[RecommendOption.from_dict(x) for x in tshirts_raw],
            combos=[OutfitCombo.from_dict(x) for x in combos_raw],
        )

    def to_dict(self) -> dict:
        return {
            "hats": [x.to_dict() for x in self.hats],
            "tshirts": [x.to_dict() for x in self.tshirts],
            "combos": [x.to_dict() for x in self.combos],
        }


# =========================================================================== #
# TryOnResult (§5.3)                                                           #
# =========================================================================== #
@dataclass
class CriticReport:
    identity_preserved: float  # [0,1]
    pose_preserved: float  # [0,1]
    tshirt_correct: bool
    hat_natural: bool
    artifacts: list  # free-form tags, e.g. warped_face | color_bleed | floating_hat
    verdict: str  # _VERDICT
    fix_instruction: str  # may be ""

    @classmethod
    def from_dict(cls, d: dict) -> "CriticReport":
        f = "critic_report"
        return cls(
            identity_preserved=_unit(
                _req(d, "identity_preserved", f"{f}.identity_preserved"),
                f"{f}.identity_preserved",
            ),
            pose_preserved=_unit(
                _req(d, "pose_preserved", f"{f}.pose_preserved"), f"{f}.pose_preserved"
            ),
            tshirt_correct=_bool(
                _req(d, "tshirt_correct", f"{f}.tshirt_correct"), f"{f}.tshirt_correct"
            ),
            hat_natural=_bool(
                _req(d, "hat_natural", f"{f}.hat_natural"), f"{f}.hat_natural"
            ),
            artifacts=_str_list(_req(d, "artifacts", f"{f}.artifacts"), f"{f}.artifacts"),
            verdict=_enum(_req(d, "verdict", f"{f}.verdict"), _VERDICT, f"{f}.verdict"),
            fix_instruction=_str(
                _req(d, "fix_instruction", f"{f}.fix_instruction"), f"{f}.fix_instruction"
            ),
        )

    def to_dict(self) -> dict:
        return {
            "identity_preserved": self.identity_preserved,
            "pose_preserved": self.pose_preserved,
            "tshirt_correct": self.tshirt_correct,
            "hat_natural": self.hat_natural,
            "artifacts": list(self.artifacts),
            "verdict": self.verdict,
            "fix_instruction": self.fix_instruction,
        }


@dataclass
class TryOnResult:
    image_url: str
    status: str  # _TRYON_STATUS
    rendered_option_ids: list
    retry_count: int  # >= 0
    critic_report: "CriticReport | None" = None

    @classmethod
    def from_dict(cls, d: dict) -> "TryOnResult":
        cr_raw = d.get("critic_report")
        critic_report = None if cr_raw is None else CriticReport.from_dict(cr_raw)
        return cls(
            image_url=_str(_req(d, "image_url"), "image_url"),
            status=_enum(_req(d, "status"), _TRYON_STATUS, "status"),
            rendered_option_ids=_str_list(
                _req(d, "rendered_option_ids"), "rendered_option_ids"
            ),
            retry_count=_nonneg_int(_req(d, "retry_count"), "retry_count"),
            critic_report=critic_report,
        )

    def to_dict(self) -> dict:
        return {
            "image_url": self.image_url,
            "status": self.status,
            "rendered_option_ids": list(self.rendered_option_ids),
            "retry_count": self.retry_count,
            "critic_report": None if self.critic_report is None else self.critic_report.to_dict(),
        }


__all__ = [
    # StyleProfile + nested
    "StyleProfile",
    "ImageQuality",
    "Person",
    "Coloring",
    "Face",
    "Build",
    "CurrentStyle",
    "TryOnFeasibility",
    # Catalog
    "CatalogProduct",
    "ProductColor",
    # MatchProfile + nested
    "MatchProfile",
    "PaletteColor",
    "MatchHat",
    "MatchTshirt",
    # recommend output
    "ScoreBreakdown",
    "RecommendOption",
    "OutfitCombo",
    "Options",
    # tryon
    "TryOnResult",
    "CriticReport",
]
