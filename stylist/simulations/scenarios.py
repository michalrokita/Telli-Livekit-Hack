"""stylist.simulations.scenarios — scripted voice-agent FLOWS over the brain (Phase 8).

The brain (`stylist`) is LiveKit-free: it returns data, it never speaks. These scenarios
are the missing half written as plain, fully-offline Python — they mirror exactly what the
partner's LiveKit voice agent (see ``SEAM.md`` §2) would *do* turn by turn: grab a frame,
``analyze`` it, decide whether the shot is usable/feasible, ``recommend``, and ``tryon`` —
turning each brain result into the short spoken line the agent would say.

Every scenario returns a :class:`ScenarioResult` (a transcript of ``(speaker, line)`` turns +
the underlying brain objects) and touches **no network** (cassette replay only). They are the
runnable rehearsal of the three demo moments:

* :func:`scenario_happy`     — good photo, full loop, render passes.
* :func:`scenario_bad_photo` — unusable shot → spoken fix request, try-on is GATED (§3.2).
* :func:`scenario_combo`     — outfit (hat+tee) request → one combined render.

Source of truth: ``stylist-engine-algorithm.md`` §3.2 (feasibility routing), §6 (MVP),
§9.4 (simulations); spoken-line shapes mirror ``SEAM.md`` §2.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

import stylist
from stylist.catalog import load_catalog

_FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, "tests", "fixtures")
GOOD_PHOTO = os.path.abspath(os.path.join(_FIX, "analyze_good.png"))
BAD_PHOTO = os.path.abspath(os.path.join(_FIX, "analyze_bad.png"))

# Critic cassette that always passes — keeps the rehearsal deterministic + offline.
_CRITIC_PASS = "tryon_critic_pass"


# --------------------------------------------------------------------------- #
# Transcript container (plain stdlib; LiveKit-free).                           #
# --------------------------------------------------------------------------- #
@dataclass
class ScenarioResult:
    """The outcome of one scripted flow: a spoken transcript + the brain objects."""

    name: str
    turns: list = field(default_factory=list)  # list[(speaker, line)]
    profile: object = None                      # StyleProfile (or None)
    options: object = None                      # Options (or None)
    tryon: object = None                        # TryOnResult (or None — gated/skipped)
    tried_on: bool = False
    fix_request: "str | None" = None            # spoken correction, when the shot is gated

    @property
    def transcript(self) -> str:
        """Just the AGENT's spoken lines, joined — what a listener would hear."""
        return " ".join(line for who, line in self.turns if who == "agent")


# --------------------------------------------------------------------------- #
# Spoken-line helpers — mirror SEAM.md §2 (_summarize_profile / _summarize_options). #
# These are the agent's mouth; the brain stays silent and just hands back data.       #
# --------------------------------------------------------------------------- #
def summarize_profile(p) -> str:
    """One short spoken line from a StyleProfile (no numbers, no jargon)."""
    if not p.image_quality.usable:
        return "I can't read your photo well yet — could you face the camera in better light?"
    c = p.coloring
    vibe = ", ".join(p.current_style.detected_vibe) or "clean"
    return (f"You read as {c.skin_undertone}-toned with a {p.build.type} build and a "
            f"{vibe} vibe — let's work with that.")


def summarize_options(opts) -> str:
    """One short spoken line naming the top tee + hat (and a combo if present)."""
    hat = opts.hats[0].title if opts.hats else None
    tee = opts.tshirts[0].title if opts.tshirts else None
    parts = []
    if tee:
        parts.append(f"a {tee}")
    if hat:
        parts.append(f"a {hat}")
    line = " and ".join(parts) if parts else "a couple of options"
    if opts.combos:
        line += " — and they pair into one outfit"
    return f"I'd go with {line}. Want to see it on you?"


def fix_request(p) -> str:
    """Spoken correction for an unusable / infeasible shot (§3.2 routing).

    Builds the concrete ask from the issues + feasibility flags, in priority order:
    light → face into frame → torso for a tee → uncover the head for a hat.
    """
    issues = set(p.image_quality.issues)
    feas = p.tryon_feasibility
    asks = []
    if "low_light" in issues:
        asks.append("find a bit more light")
    if "face_occluded" in issues:
        asks.append("turn to face me")
    if (not feas.tshirt) or "torso_not_visible" in issues:
        asks.append("step back so I can see your top")
    if not feas.hat:
        asks.append("take your cap off")
    if not asks:  # usable but a category is simply infeasible
        asks.append("turn to face me")
    # De-dup while preserving order.
    seen, ordered = set(), []
    for a in asks:
        if a not in seen:
            seen.add(a)
            ordered.append(a)
    return "Let's fix the shot first — could you " + " and ".join(ordered) + "?"


# --------------------------------------------------------------------------- #
# Scenario 1 — HAPPY PATH                                                       #
# --------------------------------------------------------------------------- #
def scenario_happy() -> ScenarioResult:
    """Good photo → analyze (usable) → recommend → try-on → render passes.

    Invariant: the spoken options line NAMES A REAL catalog item, and the try-on
    renders + the critic settles to "pass".
    """
    r = ScenarioResult(name="happy")
    r.turns.append(("user", "Hey — can you style me?"))
    r.turns.append(("agent", "Sure — hold still, let me take a look."))

    profile = stylist.analyze(GOOD_PHOTO, cassette="analyze_good")
    r.profile = profile
    r.turns.append(("agent", summarize_profile(profile)))

    catalog = load_catalog()
    opts = stylist.recommend(profile, n=2, combo=False, catalog=catalog)
    r.options = opts
    r.turns.append(("agent", summarize_options(opts)))

    r.turns.append(("user", "Yeah, show me that tee on me."))
    tee_id = opts.tshirts[0].product_id
    res = stylist.tryon(
        GOOD_PHOTO, [tee_id], catalog=catalog,
        cassette="tryon_tee", critic_cassette=_CRITIC_PASS,
    )
    # The voice agent narrates a filler while the (already-rendered) image shows; we then
    # let the background critic settle so the rehearsal returns a finished result.
    if hasattr(res, "_critic_thread"):
        res._critic_thread.join(timeout=15)
    r.tryon = res
    r.tried_on = True
    r.turns.append(("agent", "Putting that on you now — here's how it looks."))
    return r


# --------------------------------------------------------------------------- #
# Scenario 2 — BAD PHOTO (feasibility routing, §3.2)                            #
# --------------------------------------------------------------------------- #
def scenario_bad_photo() -> ScenarioResult:
    """Unusable shot → analyze flags it → the flow ROUTES to a spoken fix request and
    never calls try-on on an infeasible category (§3.2 feasibility gate).

    Invariant: ``image_quality.usable`` is False and/or both feasibility flags are False;
    a concrete fix request is spoken; ``tryon`` is NOT called (``tried_on`` stays False).
    """
    r = ScenarioResult(name="bad_photo")
    r.turns.append(("user", "Style me!"))
    r.turns.append(("agent", "On it — let me take a look."))

    profile = stylist.analyze(BAD_PHOTO, cassette="analyze_bad")
    r.profile = profile

    usable = profile.image_quality.usable
    feas = profile.tryon_feasibility
    # GATE: an unusable photo, or no feasible try-on category, must not proceed to tryon.
    if (not usable) or not (feas.hat or feas.tshirt):
        ask = fix_request(profile)
        r.fix_request = ask
        r.turns.append(("agent", ask))
        # Explicitly DO NOT call stylist.tryon — there is no feasible category to render.
        return r

    # (Unreached for analyze_bad; kept so the flow is a faithful agent script.)
    catalog = load_catalog()
    r.options = stylist.recommend(profile, catalog=catalog)
    r.turns.append(("agent", summarize_options(r.options)))
    return r


# --------------------------------------------------------------------------- #
# Scenario 3 — COMBO / OUTFIT request                                          #
# --------------------------------------------------------------------------- #
def scenario_combo() -> ScenarioResult:
    """recommend(combo=True) → a hat+tee outfit is returned → one combined try-on render.

    Invariant: 1–2 combos come back and a single render is produced + passes.
    """
    r = ScenarioResult(name="combo")
    r.turns.append(("user", "Put together a whole outfit for me."))
    r.turns.append(("agent", "Love it — reading your colouring and build now."))

    profile = stylist.analyze(GOOD_PHOTO, cassette="analyze_good")
    r.profile = profile

    catalog = load_catalog()
    opts = stylist.recommend(profile, n=2, combo=True, catalog=catalog)
    r.options = opts
    r.turns.append(("agent", summarize_options(opts)))

    combo = opts.combos[0]
    r.turns.append(("user", "Perfect, show me the full look."))
    res = stylist.tryon(
        GOOD_PHOTO, [combo.hat_id, combo.tshirt_id], combo=True, catalog=catalog,
        cassette="tryon_combo", critic_cassette=_CRITIC_PASS,
    )
    if hasattr(res, "_critic_thread"):
        res._critic_thread.join(timeout=15)
    r.tryon = res
    r.tried_on = True
    r.turns.append(("agent", "Here's the full outfit on you — hat and tee together."))
    return r


# --------------------------------------------------------------------------- #
# run_all                                                                       #
# --------------------------------------------------------------------------- #
def run_all() -> dict:
    """Run all three scenarios offline and return ``{name: ScenarioResult}``."""
    return {
        "happy": scenario_happy(),
        "bad_photo": scenario_bad_photo(),
        "combo": scenario_combo(),
    }


__all__ = [
    "ScenarioResult",
    "summarize_profile",
    "summarize_options",
    "fix_request",
    "scenario_happy",
    "scenario_bad_photo",
    "scenario_combo",
    "run_all",
]


if __name__ == "__main__":  # pragma: no cover - manual rehearsal
    for name, res in run_all().items():
        print(f"\n=== scenario: {name} (tried_on={res.tried_on}) ===")
        for who, line in res.turns:
            print(f"  {who:>5}: {line}")
        if res.tryon is not None:
            print(f"  -> render: {res.tryon.status}  {res.tryon.image_url}")
        if res.fix_request:
            print(f"  -> fix:    {res.fix_request}")
