"""stylist.simulations — offline, scripted voice-agent rehearsals over the brain.

The brain is LiveKit-free, so these are plain-Python FLOWS that mirror what the partner's
LiveKit agent (``SEAM.md`` §2) would do turn-by-turn — analyze → recommend → tryon — turning
each brain result into the short line the agent would speak. Every scenario runs entirely from
cassettes (no network, no key) and returns a :class:`~stylist.simulations.scenarios.ScenarioResult`.

    from stylist.simulations import run_all
    results = run_all()              # {"happy": ..., "bad_photo": ..., "combo": ...}
    print(results["happy"].transcript)

See ``stylist/simulations/README.md`` for the three demo moments and their invariants.
"""

from __future__ import annotations

from .scenarios import (
    ScenarioResult,
    fix_request,
    run_all,
    scenario_bad_photo,
    scenario_combo,
    scenario_happy,
    summarize_options,
    summarize_profile,
)

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
