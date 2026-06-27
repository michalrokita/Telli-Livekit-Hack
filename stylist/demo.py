"""stylist.demo — the rigged, always-clean on-stage safety net (Phase 8).

A live demo cannot depend on model variance, the network, or a key. :func:`run_demo` is the
deterministic fallback: a KNOWN-GOOD fixed photo + a curated catalog subset + fixed cassettes
that ALWAYS produce one clean, critic-passed try-on. Same inputs every call, zero network, no
model in the loop — the thing you run on stage when the live path is flaky.

    from stylist.demo import run_demo
    out = run_demo()                 # -> dict; out["tryon"].status == "pass" every time
    print(out["spoken"])             # the line the agent would say
    print(out["image_url"])          # the rendered PNG on disk

Everything replays from cassettes (`analyze_good`, `demo_combo`, `tryon_critic_pass`); the
recommendation rationales come from the deterministic TEMPLATED path (no cassette). Nothing
here imports LiveKit.
"""

from __future__ import annotations

import os

import stylist
from stylist.catalog import load_catalog
from stylist.simulations.scenarios import summarize_options, summarize_profile

# KNOWN-GOOD fixed photo — the same usable, well-framed frame every run.
_FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tests", "fixtures")
DEMO_PHOTO = os.path.abspath(os.path.join(_FIX, "analyze_good.png"))

# Curated catalog subset: the items we KNOW score well + render cleanly for this photo, so the
# top combo is fixed. (Olive cap + olive tee = a high-harmony tonal pairing for the warm-autumn
# profile in analyze_good.) Pinning the subset removes any chance of an off pick on stage.
DEMO_CATALOG_IDS = ("TEE-OLIVE-001", "TEE-RUST-002", "HAT-CAP-009", "HAT-CAP-013")

_DEMO_CASSETTE = "analyze_good"        # analyze replay
_DEMO_RENDER_CASSETTE = "demo_combo"   # rigged combined-render PNG (a composite of the base)
_DEMO_CRITIC_CASSETTE = "tryon_critic_pass"  # always-pass critic


def _curated_catalog():
    """The fixed demo subset, in a stable order (drives a deterministic top combo)."""
    keep = set(DEMO_CATALOG_IDS)
    chosen = [p for p in load_catalog() if p.id in keep]
    chosen.sort(key=lambda p: DEMO_CATALOG_IDS.index(p.id))
    return chosen


def run_demo(out_dir=None) -> dict:
    """Run the rigged happy path → a clean, critic-passed combined try-on. Deterministic.

    Parameters
    ----------
    out_dir:
        Where to write the rendered PNG (defaults to a fresh temp dir, like ``tryon``).

    Returns
    -------
    dict
        ``{profile, options, combo, tryon, image_url, status, rationale, spoken, item_titles}``.
        ``status`` is always ``"pass"`` and ``rationale`` is always non-empty — guaranteed by
        the fixed photo + curated catalog + always-pass critic cassette. Never hits the network.
    """
    catalog = _curated_catalog()

    profile = stylist.analyze(DEMO_PHOTO, cassette=_DEMO_CASSETTE)
    options = stylist.recommend(profile, n=2, combo=True, catalog=catalog)

    # Deterministic top combo from the curated subset (olive cap + olive tee).
    combo = options.combos[0]

    result = stylist.tryon(
        DEMO_PHOTO,
        [combo.hat_id, combo.tshirt_id],
        combo=True,
        catalog=catalog,
        out_dir=out_dir,
        cassette=_DEMO_RENDER_CASSETTE,
        critic_cassette=_DEMO_CRITIC_CASSETTE,
    )
    # Settle the always-pass critic so the returned result is final (status == "pass").
    if hasattr(result, "_critic_thread"):
        result._critic_thread.join(timeout=15)

    spoken = f"{summarize_profile(profile)} {summarize_options(options)}"
    return {
        "profile": profile,
        "options": options,
        "combo": combo,
        "tryon": result,
        "image_url": result.image_url,
        "status": result.status,
        "rationale": combo.rationale,
        "spoken": spoken,
        "item_titles": [o.title for o in (options.hats + options.tshirts)],
    }


__all__ = ["run_demo", "DEMO_PHOTO", "DEMO_CATALOG_IDS"]


if __name__ == "__main__":  # pragma: no cover - manual stage check
    out = run_demo()
    print("status   :", out["status"])
    print("image_url:", out["image_url"])
    print("spoken   :", out["spoken"])
    print("rationale:", out["rationale"])
