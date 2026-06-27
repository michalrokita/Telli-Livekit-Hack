"""stylist.recommend — TOOL 2: ``recommend(profile, n, combo) -> Options`` (Phase 5).

The agent-facing engine. **Deterministic scoring over the pre-enriched catalog does all
the work that has to be correct** (rules.py: hard-filter + weighted score + colour harmony);
the LLM (P2, §4.5) only does what it is good at — writing ONE natural rationale sentence per
item and picking 1-2 combos. The LLM may NOT add items or change colours: its output is merged
back **only** by matching the ``product_id`` / combo-id pairs we already scored, so a
misbehaving model can never inject a product or alter a price/colour.

Pipeline (spec §4.2 → §4.3 → §4.4 → §4.5):

    StyleProfile ──build_match_profile──▶ MatchProfile
    catalog ─score_product(feasible)─▶ drop hard_filtered ─sort─▶ top-n per category
    (combo) topK hats × topK tees ─harmony+quality+coherence─▶ best 1-2 OutfitCombo
    P2 (gpt-5.4-mini) ─rationales──▶ merged by id  (graceful template fallback)

Robustness: the rationale layer NEVER hard-fails ``recommend``. Every returned item/combo is
seeded with a deterministic templated rationale first; a successful P2 call only *overlays*
nicer prose. If P2 raises (no cassette / replay miss / OpenAIError) the templates stand.

Source of truth: ``stylist-engine-algorithm.md`` §4.2–§4.5, §6 (MVP: 2 hats + 2 tees).
"""

from __future__ import annotations

import json

from . import rules, schemas
from ._openai import OpenAIError, complete_json
from .catalog import load_catalog

_CATEGORIES = ("hat", "tshirt")
_TOPK = 3                       # combo pool: topK hats × topK tees
_MAX_COMBOS = 2                 # §4.4 "best 1-2 outfits"
_P2_MODEL = "gpt-5.4-mini"      # live + short → the fast tier (spec note)

# --------------------------------------------------------------------------- #
# P2 — Rationale + combo prompt (spec §4.5 SYSTEM, embedded VERBATIM).         #
# --------------------------------------------------------------------------- #
P2_SYSTEM = (
    "You are a personal stylist. You are given a person's profile and a SHORTLIST of "
    "products already scored and filtered by hard colour/face/body rules — every item is "
    "already valid. Do NOT add items or change colours. For each item write ONE sentence of "
    "rationale tied to a SPECIFIC profile attribute. If a combo is requested, choose the 1-2 "
    "best hat+tee pairs from the provided harmony-shortlist and give one \"why it works\" line "
    "each. Output JSON only."
)

# The exact output contract we parse back (added to the USER payload, not the verbatim SYSTEM):
# only product_id / hat_id+tshirt_id keys are honoured on merge; everything else is ignored.
_P2_OUTPUT_FORMAT = (
    '{ "items": [ {"product_id": "<id>", "rationale": "<one sentence>"} ], '
    '"combos": [ {"hat_id": "<id>", "tshirt_id": "<id>", "rationale": "<why it works>"} ] }'
)


# --------------------------------------------------------------------------- #
# Deterministic scoring → per-category ranked lists                            #
# --------------------------------------------------------------------------- #
def _score_category(match, products, *, feasible: bool):
    """Hard-filter + score every product of one category, sorted best-first.

    Returns a list of ``(product, score_result)`` tuples (survivors only). An
    infeasible category yields ``[]`` (the agent routes around it).
    """
    if not feasible:
        return []
    scored = []
    for p in products:
        res = rules.score_product(match, p, feasible=feasible)
        if res["hard_filtered"]:
            continue
        scored.append((p, res))
    # score desc, then product id asc → fully deterministic ordering.
    scored.sort(key=lambda pr: (-pr[1]["score"], pr[0].id))
    return scored


def _to_option(product, res) -> schemas.RecommendOption:
    """Wrap a scored CatalogProduct into a RecommendOption (rationale filled later)."""
    return schemas.RecommendOption(
        product_id=product.id,
        category=product.category,
        title=product.title,
        color_hex=product.color.hex,
        price=product.price,
        sizes=list(product.sizes),
        score=res["score"],
        breakdown=schemas.ScoreBreakdown.from_dict(res["breakdown"]),
        rationale="",
    )


# --------------------------------------------------------------------------- #
# §4.4 outfit combos                                                           #
# --------------------------------------------------------------------------- #
def _style_coherence(hat, tee) -> float:
    """Overlapping style_tags + formality within ±1 → [0,1] (spec §4.4)."""
    ht, tt = set(hat.style_tags), set(tee.style_tags)
    union = ht | tt
    jaccard = (len(ht & tt) / len(union)) if union else 0.0
    tag_signal = 0.4 + 0.6 * jaccard            # baseline 0.4, full overlap 1.0

    fdiff = abs(hat.formality - tee.formality)
    formality_signal = 1.0 if fdiff <= 1 else (0.6 if fdiff == 2 else 0.3)

    return round(0.5 * tag_signal + 0.5 * formality_signal, 4)


def _build_combos(match, hats_scored, tees_scored):
    """Score topK×topK hat/tee pairs → best 1-2 OutfitCombo (rationale filled later)."""
    if not hats_scored or not tees_scored:
        return []

    candidates = []
    for hat, h_res in hats_scored[:_TOPK]:
        for tee, t_res in tees_scored[:_TOPK]:
            harmony = round(
                rules.outfit_harmony(hat.color.hex, tee.color.hex, match.contrast_strategy), 4
            )
            individual = round((h_res["score"] + t_res["score"]) / 200.0, 4)
            coherence = _style_coherence(hat, tee)
            rank = 0.4 * individual + 0.4 * harmony + 0.2 * coherence
            candidates.append((rank, hat, tee, harmony, individual, coherence))

    # best-first; tiebreak on the id pair for determinism.
    candidates.sort(key=lambda c: (-c[0], c[1].id, c[2].id))

    combos = []
    for _rank, hat, tee, harmony, individual, coherence in candidates[:_MAX_COMBOS]:
        combos.append(
            schemas.OutfitCombo(
                hat_id=hat.id,
                tshirt_id=tee.id,
                harmony_score=harmony,
                individual_quality=individual,
                style_coherence=coherence,
                rationale="",
            )
        )
    return combos


# --------------------------------------------------------------------------- #
# Templated rationale (deterministic fallback — §4.3 "olive — sits in your…")  #
# --------------------------------------------------------------------------- #
def _palette_label(match) -> str:
    if match.palette_strategy == "safe-universal":
        return "versatile, undertone-safe"
    return match.palette_strategy.replace("-", " ")


def _item_clause(axis, product, profile, match):
    """One natural clause for a single scoring axis (or None to skip)."""
    if axis == "colour":
        return f"{product.color.name} sits in your {_palette_label(match)} palette"
    if axis == "shape":
        if product.category == "tshirt":
            return f"the {product.archetype} flatters your {profile.build.type} build"
        return f"the {product.archetype} suits your {profile.face.shape} face shape"
    if axis == "vibe":
        shared = [t for t in product.style_tags if t in match.vibe]
        tag = shared[0] if shared else (
            profile.current_style.detected_vibe[0]
            if profile.current_style.detected_vibe else None
        )
        return f"it matches your {tag} vibe" if tag else None
    if axis == "versatility":
        solid = product.pattern in ("solid", "none", "")
        return (f"a {'solid' if solid else 'patterned'}, easy-to-wear "
                f"formality-{product.formality} piece")
    return None


def _template_item_rationale(option, product, res, profile, match) -> str:
    """Build an attribute-tied sentence from the top-contributing axes (§4.3)."""
    axes = sorted(res["breakdown"].items(), key=lambda kv: kv[1], reverse=True)
    clauses = []
    for axis, _w in axes:
        clause = _item_clause(axis, product, profile, match)
        if clause:
            clauses.append(clause)
        if len(clauses) >= 2:
            break
    sentence = "; ".join(clauses) if clauses else (
        f"{product.color.name} works for your profile"
    )
    return sentence[0].upper() + sentence[1:] + "."


def _template_combo_rationale(hat, tee, combo, match) -> str:
    shared = sorted(set(hat.style_tags) & set(tee.style_tags))
    look = shared[0] if shared else "coherent"
    if match.contrast_strategy == "tonal":
        return (f"A tonal {hat.color.name}/{tee.color.name} pairing reads as a deliberate, "
                f"coherent {look} look without two colours competing.")
    return (f"{hat.color.name.capitalize()} and {tee.color.name} balance into a confident "
            f"{look} look that suits your higher-contrast colouring.")


# --------------------------------------------------------------------------- #
# P2 — LLM rationale overlay (id-locked merge; never adds items)              #
# --------------------------------------------------------------------------- #
def _p2_user_payload(profile, hats, tshirts, combos) -> str:
    """PROFILE + already-scored SHORTLIST + HARMONY_SHORTLIST (spec §4.5 USER)."""
    shortlist = {
        "hats": [{"product_id": o.product_id, "title": o.title, "color_hex": o.color_hex,
                  "score": o.score, "breakdown": o.breakdown.to_dict()} for o in hats],
        "tshirts": [{"product_id": o.product_id, "title": o.title, "color_hex": o.color_hex,
                     "score": o.score, "breakdown": o.breakdown.to_dict()} for o in tshirts],
    }
    harmony_shortlist = [
        {"hat_id": c.hat_id, "tshirt_id": c.tshirt_id, "harmony_score": c.harmony_score,
         "individual_quality": c.individual_quality, "style_coherence": c.style_coherence}
        for c in combos
    ]
    return (
        "PROFILE: " + json.dumps(profile.to_dict()) + "\n"
        "SHORTLIST: " + json.dumps(shortlist) + "\n"
        "HARMONY_SHORTLIST: " + json.dumps(harmony_shortlist) + "\n"
        "Write ONE rationale sentence per shortlist item (tied to a specific profile "
        "attribute) and a 'why it works' line for each combo. "
        "Output JSON ONLY in this exact shape: " + _P2_OUTPUT_FORMAT
    )


def _overlay_p2(data, all_options, combos) -> None:
    """Merge model rationales back IN PLACE, locked to ids we already scored.

    Anything the model adds (new products, new pairs, colour changes) is ignored — we only
    read ``rationale`` strings for ``product_id`` / (hat_id, tshirt_id) we already hold.
    """
    if not isinstance(data, dict):
        return

    item_map = {}
    for it in (data.get("items") or []):
        if not isinstance(it, dict):
            continue
        pid, rat = it.get("product_id"), it.get("rationale")
        if isinstance(pid, str) and isinstance(rat, str) and rat.strip():
            item_map[pid] = rat.strip()
    for opt in all_options:
        if opt.product_id in item_map:
            opt.rationale = item_map[opt.product_id]

    combo_map = {}
    for c in (data.get("combos") or []):
        if not isinstance(c, dict):
            continue
        hid, tid, rat = c.get("hat_id"), c.get("tshirt_id"), c.get("rationale")
        if isinstance(hid, str) and isinstance(tid, str) and isinstance(rat, str) and rat.strip():
            combo_map[(hid, tid)] = rat.strip()
    for combo in combos:
        key = (combo.hat_id, combo.tshirt_id)
        if key in combo_map:
            combo.rationale = combo_map[key]


# --------------------------------------------------------------------------- #
# Public API                                                                   #
# --------------------------------------------------------------------------- #
def recommend(profile: schemas.StyleProfile, n: int = 2, combo: bool = False,
              *, catalog=None, cassette: str | None = None) -> schemas.Options:
    """Recommend ``n`` hats + ``n`` tees (+ 1-2 combos) for a person (spec §4).

    Parameters
    ----------
    profile:
        The :class:`~stylist.schemas.StyleProfile` from ``analyze``.
    n:
        Top-N per category (MVP default 2 → 2 hats + 2 tees).
    combo:
        When ``True`` also return 1-2 curated hat+tee outfits (§4.4).
    catalog:
        Pre-enriched ``CatalogProduct[]``; defaults to :func:`stylist.catalog.load_catalog`.
    cassette:
        P2 rationale replay cassette name (tests). With ``STYLIST_LIVE`` unset and no
        cassette the deterministic templated rationale is used (no network).

    Returns
    -------
    Options
        ``{hats, tshirts, combos}`` — every item/combo carries a non-empty rationale. An
        infeasible category comes back empty. The deterministic core never hard-fails; only
        the (overlay-only) rationale layer is allowed to degrade to templates.
    """
    catalog = list(catalog) if catalog is not None else load_catalog()
    match = rules.build_match_profile(profile)
    feas = rules.feasible_categories(profile)

    by_cat = {c: [] for c in _CATEGORIES}
    for p in catalog:
        if p.category in by_cat:
            by_cat[p.category].append(p)

    scored = {
        c: _score_category(match, by_cat[c], feasible=(c in feas))
        for c in _CATEGORIES
    }

    hats = [_to_option(p, r) for p, r in scored["hat"][:n]]
    tshirts = [_to_option(p, r) for p, r in scored["tshirt"][:n]]
    combos = _build_combos(match, scored["hat"], scored["tshirt"]) if combo else []
    all_options = hats + tshirts

    # 1) Deterministic templated rationale on EVERY item/combo (the robust floor).
    prod_by_id = {p.id: p for p, _ in (scored["hat"] + scored["tshirt"])}
    res_by_id = {p.id: r for p, r in (scored["hat"] + scored["tshirt"])}
    for opt in all_options:
        opt.rationale = _template_item_rationale(
            opt, prod_by_id[opt.product_id], res_by_id[opt.product_id], profile, match
        )
    for cb in combos:
        cb.rationale = _template_combo_rationale(
            prod_by_id[cb.hat_id], prod_by_id[cb.tshirt_id], cb, match
        )

    # 2) P2 overlay (live or cassette). Anti-loop: any failure → keep templates, never raise.
    if all_options:
        try:
            data = complete_json(
                system=P2_SYSTEM,
                user_content=_p2_user_payload(profile, hats, tshirts, combos),
                model=_P2_MODEL,
                cassette=cassette,
            )
            _overlay_p2(data, all_options, combos)
        except OpenAIError:
            pass  # no cassette / replay miss / transport error → templated rationale stands.

    return schemas.Options(hats=hats, tshirts=tshirts, combos=combos)


__all__ = ["recommend", "P2_SYSTEM"]
