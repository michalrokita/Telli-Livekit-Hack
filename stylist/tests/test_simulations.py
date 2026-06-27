"""Tests for the scripted voice rehearsals (Phase 8) — stdlib unittest, fully offline.

Asserts each scenario's KEY INVARIANT:
  * happy     — renders + critic passes, and the spoken summary names a real catalog item.
  * bad_photo — gates on an unusable/infeasible shot and NEVER calls try-on (§3.2).
  * combo     — yields 1–2 outfits and exactly one combined render.

Run from the repo root:
    python3 -m unittest discover -s stylist/tests -v
"""

import os
import sys
import unittest

# Make `import stylist...` work regardless of the current working directory.
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from stylist.schemas import Options, TryOnResult  # noqa: E402
from stylist.simulations import scenarios  # noqa: E402


class TestScenarioHappy(unittest.TestCase):
    def test_renders_and_names_a_real_item(self):
        r = scenarios.scenario_happy()
        # Usable read + a real recommendation.
        self.assertTrue(r.profile.image_quality.usable)
        self.assertIsInstance(r.options, Options)
        self.assertTrue(r.options.tshirts)

        # The spoken transcript names a REAL catalog item (not an invented one).
        real_titles = [o.title for o in (r.options.hats + r.options.tshirts)]
        self.assertTrue(
            any(t and t in r.transcript for t in real_titles),
            f"no real item named in transcript: {r.transcript!r}",
        )

        # The try-on rendered and the critic settled to a pass.
        self.assertTrue(r.tried_on)
        self.assertIsInstance(r.tryon, TryOnResult)
        self.assertTrue(os.path.exists(r.tryon.image_url))
        self.assertEqual(r.tryon.status, "pass")


class TestScenarioBadPhoto(unittest.TestCase):
    def test_gates_and_never_tries_on(self):
        r = scenarios.scenario_bad_photo()
        # The shot is unusable AND no feasible category.
        self.assertFalse(r.profile.image_quality.usable)
        self.assertFalse(r.profile.tryon_feasibility.hat)
        self.assertFalse(r.profile.tryon_feasibility.tshirt)

        # The flow routed to a spoken fix request...
        self.assertIsNotNone(r.fix_request)
        self.assertIn(r.fix_request, r.transcript)
        # ...with concrete §3.2 routing language.
        low = r.fix_request.lower()
        self.assertTrue(
            ("face me" in low) or ("cap off" in low) or ("see your top" in low),
            f"fix request not actionable: {r.fix_request!r}",
        )

        # CRITICAL: try-on was never attempted on an infeasible category.
        self.assertFalse(r.tried_on)
        self.assertIsNone(r.tryon)


class TestScenarioCombo(unittest.TestCase):
    def test_yields_outfit_and_one_render(self):
        r = scenarios.scenario_combo()
        self.assertIsInstance(r.options, Options)
        # 1–2 outfits (spec §4.4 "best 1-2 outfits").
        self.assertGreaterEqual(len(r.options.combos), 1)
        self.assertLessEqual(len(r.options.combos), 2)

        # Exactly one combined render, and it passed.
        self.assertTrue(r.tried_on)
        self.assertIsInstance(r.tryon, TryOnResult)
        self.assertEqual(len(r.tryon.rendered_option_ids), 2)
        self.assertTrue(os.path.exists(r.tryon.image_url))
        self.assertEqual(r.tryon.status, "pass")


class TestRunAll(unittest.TestCase):
    def test_run_all_returns_three(self):
        results = scenarios.run_all()
        self.assertEqual(set(results), {"happy", "bad_photo", "combo"})
        # happy + combo render; bad_photo gates.
        self.assertTrue(results["happy"].tried_on)
        self.assertTrue(results["combo"].tried_on)
        self.assertFalse(results["bad_photo"].tried_on)


if __name__ == "__main__":
    unittest.main()
