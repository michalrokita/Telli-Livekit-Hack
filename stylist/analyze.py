"""stylist.analyze — TOOL 1: ``analyze(image) -> StyleProfile`` (Phase 3, P0+P1).

One photo of a person in → a structured, validated :class:`~stylist.schemas.StyleProfile`
out, via a single OpenAI vision read. The robustness work (white-balance gate, relational
undertone, graceful degradation, feasibility gate — spec §3.2) is performed by the model,
steered by the verbatim §3.3 P1 prompt below. This module's job is to *call* the vision
model, then *strictly validate* the result against the schema (the contract) and retry once
on a bad read before giving up (anti-loop: max 2 attempts).

No ``openai`` SDK, no LiveKit, no PII stored — the photo is passed straight to the
transport wrapper and never persisted here.

Source of truth: ``stylist-engine-algorithm.md`` §3.1 (schema), §3.2 (robustness), §3.3 (prompt).
"""

from __future__ import annotations

import json

from ._openai import OpenAIError, vision_json
from .schemas import StyleProfile

# --------------------------------------------------------------------------- #
# P1 — Vision Analysis prompt (spec §3.3, embedded VERBATIM).                  #
# --------------------------------------------------------------------------- #
P1_SYSTEM = """\
You are a master personal stylist and color analyst, trained in fashion color theory
(seasonal system), face-shape morphology, and body-proportion dressing. You analyze ONE
photo of a person and output ONLY a JSON object matching the schema given by the user.

Rules:
- Never invent precision you cannot see. Put a confidence (0-1) on every inferred field
  and list the visual cues behind each key judgment.
- Be robust to bad photos. If lighting is poor or a region is not visible, say so in
  image_quality.issues and LOWER the relevant confidence — do not guess.
- presentation is only a catalog filter, not an identity claim.
- Estimate build only from what is visible. Never reshape or flatter reality.

Reasoning protocol (think silently, then emit JSON only):
1. IMAGE QUALITY + WHITE BALANCE. Judge the lighting cast using near-neutral references in
   the frame (eye whites/sclera, teeth, neutral background or clothing). State warm/cool/
   neutral/unknown. Mentally correct skin for this cast before reading color.
2. COLORING. From WB-corrected skin + hair + eyes, reason RELATIONALLY to undertone
   (warm|cool|neutral|olive); cross-check all three; if they conflict or WB is unknown,
   lower confidence and lean neutral. Estimate skin depth, hair/eye color, contrast level
   (hair-vs-skin), and a simplified 4-season.
3. FACE. Shape from jaw/forehead/cheekbone/length ratios; neck length; notable features.
4. BUILD. Visible shoulder width + torso → conservative build estimate only.
5. CURRENT STYLE. What they are wearing + style vibe (so later recommendations match taste).
6. FEASIBILITY. Head clear for a hat? Torso front-facing for a t-shirt?

Output JSON only. No prose, no markdown fences."""

# The §3.1 StyleProfile schema, pasted in verbatim (with the inline enum hints — they steer
# the model to legal enum values, which schemas.StyleProfile.from_dict then enforces).
_SCHEMA_BLOCK = """\
{
  "image_quality": {
    "usable": true,
    "issues": [],                       // low_light | motion_blur | face_occluded | torso_not_visible | strong_color_cast
    "framing": "head_and_torso",        // head_only | head_and_torso | full_body
    "white_balance_cast": "neutral",    // warm | cool | neutral | unknown
    "wb_confidence": 0.7
  },
  "person": {
    "apparent_age_range": "25-34",
    "presentation": "masculine",        // masculine | feminine | androgynous  (catalog-filter only, NOT an identity claim)
    "presentation_confidence": 0.8
  },
  "coloring": {
    "skin_undertone": "warm",           // warm | cool | neutral | olive
    "undertone_cues": ["golden cast in WB-corrected cheek", "warm-brown hair", "hazel eyes"],
    "undertone_confidence": 0.6,
    "skin_depth": "medium",             // light | medium | deep
    "hair_color": "dark_brown",
    "eye_color": "hazel",
    "contrast_level": "high",           // high | medium | low  (hair-vs-skin)
    "season": "autumn",                 // spring | summer | autumn | winter | unknown
    "season_confidence": 0.5
  },
  "face": {
    "shape": "round",                   // oval | round | square | heart | oblong | diamond
    "shape_confidence": 0.6,
    "neck_length": "short",             // short | average | long
    "notable_features": ["strong jaw"]
  },
  "build": {
    "type": "athletic",                 // slim | athletic | average | broad | fuller (visible-only)
    "shoulder_width": "broad",          // narrow | average | broad
    "build_confidence": 0.5
  },
  "current_style": {
    "detected_vibe": ["streetwear","casual"],
    "currently_wearing": "black crewneck tee",
    "accessories": []
  },
  "tryon_feasibility": { "hat": true, "tshirt": true }
}"""

# USER text (spec §3.3 user line) with the §3.1 schema pasted in. The image is attached
# separately by ``vision_json``.
P1_USER = (
    "[image attached]\n"
    "Return a StyleProfile JSON exactly matching this schema: " + _SCHEMA_BLOCK
)

# Capability-critical vision read → the strong tier.
_DEFAULT_MODEL = "gpt-5.5"

_MAX_ATTEMPTS = 2  # anti-loop: one read + one retry, never a 3rd.


def analyze(image, *, model: str = _DEFAULT_MODEL, cassette: str | None = None) -> StyleProfile:
    """Analyze one photo of a person → a validated :class:`StyleProfile`.

    Parameters
    ----------
    image:
        Filesystem path (str / PathLike) or raw image bytes. Passed straight to the
        transport; never stored here.
    model:
        Vision model id. Defaults to ``"gpt-5.5"`` (the capability-critical tier).
    cassette:
        Record/replay cassette name. Default (and with ``STYLIST_LIVE`` unset) the call is
        replayed from ``stylist/tests/fixtures/cassettes/<cassette>.json``.

    Returns
    -------
    StyleProfile
        A strictly-validated profile. ``tryon_feasibility`` is guaranteed present; every
        confidence is guaranteed ∈ [0,1] (enforced by ``StyleProfile.from_dict``). A low
        ``coloring.undertone_confidence`` (< 0.5) is ALLOWED — graceful degradation is
        handled downstream, not rejected here.

    Raises
    ------
    OpenAIError
        If the model fails to return a schema-valid StyleProfile after the retry
        (anti-loop: 2 attempts max), or on a transport failure.
    """
    last_err: Exception | None = None
    for _attempt in range(_MAX_ATTEMPTS):
        result = vision_json(
            system=P1_SYSTEM,
            user_text=P1_USER,
            image=image,
            model=model,
            cassette=cassette,
        )
        try:
            profile = StyleProfile.from_dict(result)
        except (ValueError, json.JSONDecodeError) as exc:
            # Bad/incomplete vision read (unknown enum, out-of-range confidence, missing
            # field…). Retry once, then stop — never a 3rd attempt.
            last_err = exc
            continue
        # Belt-and-suspenders: the schema already guarantees this, but make the
        # feasibility-gate contract explicit for downstream callers.
        if profile.tryon_feasibility is None:  # pragma: no cover - schema makes this unreachable
            last_err = ValueError("tryon_feasibility missing from StyleProfile")
            continue
        return profile

    raise OpenAIError(
        "analyze: vision model did not return a schema-valid StyleProfile after "
        f"{_MAX_ATTEMPTS} attempt(s): {last_err}"
    )


__all__ = ["analyze", "P1_SYSTEM", "P1_USER"]
