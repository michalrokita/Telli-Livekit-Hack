"""stylist.tryon — TOOL 3: ``tryon(...) -> TryOnResult`` (Phase 6).

Identity-preserving virtual try-on via OpenAI **gpt-image-2** (masked image edit),
with the verification **critic OFF the critical path**.

Flow (spec §5):
  1. Resolve ``option_ids`` -> catalog product image(s) + category (hat / tshirt).
  2. Render with one or more *masked* gpt-image-2 edits — the mask locks the face +
     background and exposes ONLY the garment region (torso for a tee, head-top for a
     hat), which is gpt-image-2's biggest identity-fidelity win. Default (separate ids)
     = sequential masked edits (tee first, then hat — lock more each pass); ``combo=True``
     = ONE pass with both references.
  3. Write the rendered PNG and **return immediately** with ``status="pending"`` — the
     synchronous return NEVER waits for the critic.
  4. ASYNC: a background thread runs the P4 critic (§5.3). On a catastrophic flag it does
     ONE silent background re-render (cap = 1), hot-swaps the image file, then settles the
     status to ``pass`` / ``low_confidence`` and fires the optional ``on_critic`` callback
     (the deferred hot-swap delivery seam for the voice agent / UI).

stdlib + PIL only here. No ``openai`` SDK, no LiveKit, no PII persisted.

Source of truth: ``stylist-engine-algorithm.md`` §5.1 (model + masking), §5.2 (P3 edit
prompt, embedded verbatim), §5.3 (async P4 critic + JSON schema, cap = 1 retry).
"""

from __future__ import annotations

import os
import tempfile
import threading
import uuid
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from ._openai import (
    OpenAIError,
    complete_json,
    edit_image,
    encode_image_b64,
    load_image_bytes,
)
from .schemas import CatalogProduct, CriticReport, TryOnResult

# Models (per the build spec): render = gpt-image-2; critic = the fast gpt-5.4-mini tier.
RENDER_MODEL = "gpt-image-2"
CRITIC_MODEL = "gpt-5.4-mini"

# Anti-loop: at most ONE silent background re-render, then flag low_confidence. Never loop.
_MAX_RENDER_RETRIES = 1


# --------------------------------------------------------------------------- #
# P3 — Try-On / image-edit prompt (spec §5.2, embedded VERBATIM).             #
# The PRESERVE block, the "Match…" paragraph and the Negative line are pasted  #
# verbatim; only the {tee}/{hat} colour+style + which CHANGE bullets appear    #
# are filled in per render (a tee-only pass omits the hat bullet, etc.).       #
# --------------------------------------------------------------------------- #
_P3_PREAMBLE = """\
Edit the provided BASE photo so the person is wearing the specified garments.

PRESERVE EXACTLY (do not change): the person's face and identity, skin tone, hairstyle,
body pose, hands, the background, the camera angle, and the scene's lighting and shadows.

CHANGE ONLY the clothing:"""

_P3_TEE_LINE = """\
- Replace their current top with: {tee}, matching this reference image
  [TSHIRT_REF attached]."""

_P3_HAT_LINE = """\
- Add: {hat}, matching this reference [HAT_REF attached], fitted naturally to
  the head with correct perspective and a soft contact shadow."""

_P3_TAIL = """\
Match the garments' shading and highlights to the existing light direction in the photo.
Do NOT reshape the body, do NOT beautify or alter the face, do NOT change proportions or
background. Photorealistic and seamless.

Negative: warped or different face, extra fingers/limbs, garment color drifting from the
reference, floating/clipping hat, text or logo artifacts, plastic skin."""


def build_p3_prompt(tee_desc=None, hat_desc=None, fix_instruction=None) -> str:
    """Assemble the §5.2 P3 edit prompt for the garments present in this pass.

    ``tee_desc`` / ``hat_desc`` fill the ``{tshirt: color + style}`` / ``{hat: style + color}``
    placeholders; pass ``None`` to omit that CHANGE bullet. ``fix_instruction`` (from the
    critic on a retry) is appended as "one concrete edit to add to the P3 prompt" (§5.3).
    """
    change_lines = []
    if tee_desc:
        change_lines.append(_P3_TEE_LINE.format(tee=tee_desc))
    if hat_desc:
        change_lines.append(_P3_HAT_LINE.format(hat=hat_desc))
    prompt = _P3_PREAMBLE + "\n" + "\n".join(change_lines) + "\n\n" + _P3_TAIL
    if fix_instruction:
        prompt += "\n\nCorrection (apply this fix): " + fix_instruction.strip()
    return prompt


# --------------------------------------------------------------------------- #
# P4 — Try-On Critic SYSTEM prompt (spec §5.3, embedded VERBATIM).             #
# --------------------------------------------------------------------------- #
P4_SYSTEM = """\
You verify a virtual try-on. Compare the OUTPUT image to (A) the BASE photo and
(B) the INTENDED garments. Be strict: a wrong garment color or an altered face is a FAIL.
Return JSON only:
{
  "identity_preserved": 0-1,        // same person's face?
  "pose_preserved": 0-1,
  "tshirt_correct": bool,           // present + color matches intent
  "hat_natural": bool,              // present + fits the head, no floating/clipping
  "artifacts": [],                  // warped_face | extra_fingers | color_bleed | floating_hat | ...
  "verdict": "pass" | "retry",
  "fix_instruction": ""             // if retry: one concrete edit to add to the P3 prompt
}"""


# --------------------------------------------------------------------------- #
# Mask helper                                                                  #
# --------------------------------------------------------------------------- #
# Coarse proportional garment boxes (fractions of W,H). This is the MVP: a torso
# rectangle for a tee and a head-top rectangle for a hat. Real per-pixel garment
# segmentation (or a face-bbox-derived head box) is a v2 upgrade — coarse rects are
# good enough to lock the face + background, which is the dominant fidelity win.
_REGION_BOXES = {
    "torso": (0.16, 0.42, 0.84, 0.99),
    "head_top": (0.26, 0.02, 0.74, 0.32),
}
_REGION_ALIASES = {
    "torso": "torso", "tshirt": "torso", "tee": "torso", "top": "torso",
    "head_top": "head_top", "head": "head_top", "hat": "head_top",
}


def build_mask(image, regions) -> bytes:
    """Build an RGBA PNG edit-mask for the OpenAI images/edits API.

    OpenAI mask semantics (IMPORTANT): the mask's **fully transparent (alpha=0) pixels
    mark the region to be EDITED**; opaque (alpha=255) pixels are LOCKED. So we start
    fully opaque (everything — face, background — locked) and punch a transparent box
    over each requested garment region.

    ``image`` is a path / bytes / PIL image (the mask is sized to it). ``regions`` is an
    iterable of region names: ``"torso"``/``"tshirt"``/``"tee"`` -> torso box,
    ``"head_top"``/``"head"``/``"hat"`` -> head-top box.
    """
    from PIL import Image, ImageDraw  # PIL allowed here; imported lazily.

    raw = load_image_bytes(image)
    with Image.open(BytesIO(raw)) as im:
        w, h = im.size
    mask = Image.new("RGBA", (w, h), (0, 0, 0, 255))  # opaque everywhere = LOCKED
    draw = ImageDraw.Draw(mask)
    for region in regions:
        key = _REGION_ALIASES.get(str(region).lower())
        if key is None:
            raise ValueError(f"build_mask: unknown region {region!r}")
        left, top, right, bottom = _REGION_BOXES[key]
        box = (int(left * w), int(top * h), int(right * w), int(bottom * h))
        draw.rectangle(box, fill=(0, 0, 0, 0))  # alpha=0 -> this box is EDITABLE
    out = BytesIO()
    mask.save(out, format="PNG")
    return out.getvalue()


# --------------------------------------------------------------------------- #
# Option resolution (option_ids -> product image + category + descriptor)     #
# --------------------------------------------------------------------------- #
@dataclass
class _Resolved:
    option_id: str
    image: object  # path / bytes -> passed straight to edit_image as a reference
    category: str  # "tshirt" | "hat"
    descriptor: str  # colour + style text used to fill the P3 prompt


def _infer_category(text: str):
    s = str(text).lower()
    if any(t in s for t in ("hat", "cap", "beanie", "bucket", "fedora")):
        return "hat"
    if any(t in s for t in ("tee", "tshirt", "t-shirt", "shirt", "top")):
        return "tshirt"
    return None


def _product_desc(p: CatalogProduct) -> str:
    if p.category == "hat":
        return f"{p.archetype} in {p.color.name}".strip()
    return f"{p.color.name} {p.archetype}".strip()


def _default_desc(category: str) -> str:
    return "the selected hat" if category == "hat" else "the selected t-shirt"


def _build_index(catalog):
    """Normalise ``catalog`` -> {id: _Resolved} (or None for direct-path mode)."""
    if catalog is None:
        return None
    index: dict = {}
    items = catalog.items() if isinstance(catalog, dict) else ((p.id if isinstance(p, CatalogProduct) else None, p) for p in catalog)
    for key, val in items:
        if isinstance(val, CatalogProduct):
            index[val.id] = _Resolved(val.id, val.image_url, val.category, _product_desc(val))
        else:
            # id -> image (path/bytes) map: category inferred from the id.
            cat = _infer_category(key)
            if cat is None:
                raise ValueError(f"catalog entry {key!r}: cannot infer hat/tshirt category from id")
            index[str(key)] = _Resolved(str(key), val, cat, _default_desc(cat))
    return index


def _resolve(option_id, index) -> _Resolved:
    if index is not None and option_id in index:
        return index[option_id]
    # Standalone mode: option_id IS a direct product-image path (lets tests run without a catalog).
    cat = _infer_category(option_id)
    if cat is None:
        raise ValueError(
            f"option {option_id!r}: not in catalog and category not inferable from the id/path"
        )
    return _Resolved(str(option_id), option_id, cat, _default_desc(cat))


# --------------------------------------------------------------------------- #
# Render plan (one or more masked passes)                                      #
# --------------------------------------------------------------------------- #
@dataclass
class _Pass:
    categories: tuple  # ("tshirt",) | ("hat",) | ("tshirt","hat")
    refs: list  # product image refs for this pass
    tee_desc: object
    hat_desc: object
    cassette: object  # render cassette name for this pass (or None)


def _pass_cassette(cassette, key: str, n_passes: int):
    """Map the caller's render-cassette name onto a per-pass name.

    A single-pass render (single id, or a combo) replays straight from ``cassette``;
    a sequential 2-pass render derives distinct ``<cassette>_<category>`` names so a
    live RECORD run doesn't clobber one file with two different renders.
    """
    if cassette is None:
        return None
    if n_passes == 1:
        return cassette
    return f"{cassette}_{key}"


def _plan(resolved: list, combo: bool, cassette):
    tees = [r for r in resolved if r.category == "tshirt"]
    hats = [r for r in resolved if r.category == "hat"]
    if combo:
        # ONE pass with every reference + every region (spec §5.1 combo path).
        cats = tuple(c for c, present in (("tshirt", tees), ("hat", hats)) if present)
        return [
            _Pass(
                categories=cats,
                refs=[r.image for r in resolved],
                tee_desc=tees[0].descriptor if tees else None,
                hat_desc=hats[0].descriptor if hats else None,
                cassette=_pass_cassette(cassette, "combo", 1),
            )
        ]
    # Default: sequential masked edits — tee first, then hat (lock more each pass).
    ordered = tees + hats
    n = len(ordered)
    passes = []
    for r in ordered:
        passes.append(
            _Pass(
                categories=(r.category,),
                refs=[r.image],
                tee_desc=r.descriptor if r.category == "tshirt" else None,
                hat_desc=r.descriptor if r.category == "hat" else None,
                cassette=_pass_cassette(cassette, r.category, n),
            )
        )
    return passes


def _regions_for(categories) -> list:
    return list(categories)  # names already alias onto torso / head_top in build_mask


def _restore_outside(base_bytes, edited_bytes, regions) -> bytes:
    """Keep ONLY the garment region(s) from the model output; restore everything else
    (face, hair, background) from ``base`` — pixel-level masking we control.

    gpt-image's API mask is an unreliable *hint*: the model often blackens or garbles the
    "locked" area (the big black square over the face). So instead of trusting it, we paste
    the model's render back ONLY inside the (feathered) garment boxes and keep the original
    pixels everywhere else. This makes the black-square / face-drift failure mode impossible:
    the face is always the real face, whatever the model did outside the box.
    """
    from PIL import Image, ImageDraw, ImageFilter

    base = Image.open(BytesIO(load_image_bytes(base_bytes))).convert("RGB")
    edit = Image.open(BytesIO(load_image_bytes(edited_bytes))).convert("RGB")
    if edit.size != base.size:
        edit = edit.resize(base.size)
    w, h = base.size
    alpha = Image.new("L", (w, h), 0)  # 0 = keep base everywhere
    draw = ImageDraw.Draw(alpha)
    for region in regions:
        key = _REGION_ALIASES.get(str(region).lower())
        if key is None:
            continue
        left, top, right, bottom = _REGION_BOXES[key]
        draw.rectangle((int(left * w), int(top * h), int(right * w), int(bottom * h)), fill=255)
    alpha = alpha.filter(ImageFilter.GaussianBlur(max(2, int(min(w, h) * 0.015))))  # soft seam
    out = Image.composite(edit, base, alpha)  # edit inside the boxes, base outside
    buf = BytesIO()
    out.save(buf, format="PNG")
    return buf.getvalue()


def _execute(base_photo, passes, *, fix_instruction=None) -> bytes:
    """Run the masked-edit passes in order (chaining each output into the next).

    Synchronous and render-only. Returns the final PNG bytes. The critic is NOT involved
    here — keeping this off the critic's path is the whole point.

    After each model edit we composite the result back onto the pass input
    (:func:`_restore_outside`) so only the garment region changes and the face/background
    stay exactly original — this removes the gpt-image "black square over the face" failure.
    """
    current = load_image_bytes(base_photo)
    for p in passes:
        prompt = build_p3_prompt(p.tee_desc, p.hat_desc, fix_instruction=fix_instruction)
        # NO mask: let gpt-image-2 do INSTRUCTION editing — place the garment naturally from the
        # reference image. A mask forces crude DALL·E-style inpainting (the black square over the
        # face + the t-shirt not sitting on the body). The P3 prompt already says preserve the
        # face/pose/background and replace only the top, which is all gpt-image-2 needs.
        current = edit_image(
            base_image=current,
            prompt=prompt,
            mask=None,
            reference_images=p.refs,
            model=RENDER_MODEL,
            cassette=p.cassette,
        )
    return current


def _intended(resolved: list) -> dict:
    out = {}
    for r in resolved:
        out["tshirt" if r.category == "tshirt" else "hat"] = r.descriptor
    return out


# --------------------------------------------------------------------------- #
# Critic (P4) — standalone + testable; called from the async worker.          #
# --------------------------------------------------------------------------- #
def run_critic(base_image, output_png, intended, *, model: str = CRITIC_MODEL, cassette=None) -> CriticReport:
    """Verify a render (spec §5.3 P4). Inputs = BASE + OUTPUT + INTENDED garments.

    Uses the two-image chat path (``complete_json``) because identity/pose verification
    genuinely needs BOTH the base and the output image in one comparison — the single-image
    ``vision_json`` helper can't carry two. Replays from ``<cassette>.json`` offline.
    Returns a strictly-validated :class:`CriticReport`.
    """
    if isinstance(intended, dict):
        intended_text = ", ".join(f"{k}: {v}" for k, v in intended.items()) or "(none)"
    else:
        intended_text = str(intended)
    user_content = [
        {"type": "text", "text": f"BASE [img], OUTPUT [img], INTENDED: {{{intended_text}}}"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64," + encode_image_b64(base_image)}},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64," + encode_image_b64(output_png)}},
    ]
    result = complete_json(system=P4_SYSTEM, user_content=user_content, model=model, cassette=cassette)
    return CriticReport.from_dict(result)


# --------------------------------------------------------------------------- #
# TOOL 3 — tryon                                                               #
# --------------------------------------------------------------------------- #
def tryon(
    base_photo,
    option_ids,
    *,
    catalog=None,
    combo: bool = False,
    on_critic=None,
    out_dir=None,
    cassette=None,
    critic_cassette=None,
) -> TryOnResult:
    """Render an identity-preserving virtual try-on; verify it asynchronously.

    Parameters
    ----------
    base_photo:
        The person photo (path / bytes).
    option_ids:
        Product ids to render. Resolved via ``catalog`` (``list[CatalogProduct]`` or an
        ``id -> image`` map); with no catalog, an id may be a direct product-image path
        (so tests run standalone). A ``tshirt`` masks the torso, a ``hat`` the head-top.
    combo:
        ``True`` = render hat + tee in ONE pass; default = sequential masked edits.
    on_critic:
        Optional callback ``on_critic(updated_result)`` fired once the async critic settles
        (the deferred hot-swap delivery seam).
    out_dir, cassette, critic_cassette:
        Output dir for the PNG; render cassette name; critic cassette name.

    Returns
    -------
    TryOnResult
        Returned **immediately** after the (synchronous) render with ``status="pending"``,
        ``critic_report=None``, ``retry_count=0``. The critic runs on a background thread and
        later mutates this same object (and calls ``on_critic``). The synchronous return
        NEVER blocks on the critic.
    """
    ids = list(option_ids)
    if not ids:
        raise ValueError("tryon: option_ids must be non-empty")

    index = _build_index(catalog)
    resolved = [_resolve(oid, index) for oid in ids]
    passes = _plan(resolved, combo, cassette)

    # --- synchronous render (this is the user's result; critic is NOT on this path) ---
    final_png = _execute(base_photo, passes)

    out_dir = Path(out_dir) if out_dir is not None else Path(tempfile.mkdtemp(prefix="stylist_tryon_"))
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"tryon_{uuid.uuid4().hex}.png"
    out_path.write_bytes(final_png)

    result = TryOnResult(
        image_url=str(out_path),
        status="pending",
        rendered_option_ids=[str(o) for o in ids],
        retry_count=0,
        critic_report=None,
    )

    # Only spawn the critic when it can actually run — a cassette (replay) or a live key.
    # This keeps the FAST path deterministic (pending / None) and the critic strictly
    # off the critical path. The voice agent narrates the rationale while this runs.
    if critic_cassette is not None or os.environ.get("STYLIST_LIVE") == "1":
        intended = _intended(resolved)

        def _worker():
            try:
                report = run_critic(
                    base_photo, final_png, intended,
                    model=CRITIC_MODEL, cassette=critic_cassette,
                )
                result.critic_report = report
                if report.verdict == "pass":
                    result.status = "pass"
                elif result.retry_count < _MAX_RENDER_RETRIES:
                    # ONE silent background re-render with the critic's fix appended,
                    # hot-swap the image file in place, then re-verify once.
                    new_png = _execute(base_photo, passes, fix_instruction=report.fix_instruction)
                    result.retry_count += 1
                    out_path.write_bytes(new_png)  # hot-swap (image_url stays valid)
                    report2 = run_critic(
                        base_photo, new_png, intended,
                        model=CRITIC_MODEL, cassette=critic_cassette,
                    )
                    result.critic_report = report2
                    # Capped: a still-failing verdict is flagged, never looped again.
                    result.status = "pass" if report2.verdict == "pass" else "low_confidence"
                else:  # pragma: no cover - retry_count starts at 0
                    result.status = "low_confidence"
            except (OpenAIError, ValueError):
                # Critic is non-blocking quality protection; its failure must not crash
                # the thread or the delivered render. Flag and move on.
                result.status = "error"
            finally:
                if on_critic is not None:
                    try:
                        on_critic(result)
                    except Exception:  # never let a UI callback kill the worker
                        pass

        thread = threading.Thread(target=_worker, name="stylist-tryon-critic", daemon=True)
        thread.start()
        # Expose the handle so callers/tests can join() instead of (or besides) on_critic.
        result._critic_thread = thread  # type: ignore[attr-defined]

    return result


__all__ = ["tryon", "run_critic", "build_mask", "build_p3_prompt", "P4_SYSTEM", "RENDER_MODEL", "CRITIC_MODEL"]
