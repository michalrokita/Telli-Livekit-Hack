"""Offline (replay) + guarded-live tests for stylist.analyze (stdlib unittest).

Run from the repo root:
    python3 -m unittest discover -s stylist/tests -v

All assertions here are structural/sanity — never exact colours — and run with NO network
(cassette replay). The single live smoke test is skipped unless ``STYLIST_LIVE=1``.
"""

import os
import sys
import unittest
from unittest import mock

# Make `import stylist...` work regardless of the current working directory.
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import importlib  # noqa: E402

# `stylist.analyze` (the attribute) is the PUBLIC callable since Phase 7 exported it on
# the package; grab the real submodule object (for mock.patch.object of vision_json).
analyze_mod = importlib.import_module("stylist.analyze")  # noqa: E402
from stylist._openai import OpenAIError  # noqa: E402
from stylist.analyze import analyze  # noqa: E402
from stylist.schemas import (  # noqa: E402
    _CONTRAST_LEVEL,
    _FACE_SHAPE,
    _FRAMING,
    _ISSUES,
    _NECK_LENGTH,
    _PERSON_PRESENTATION,
    _SEASON,
    _SHOULDER,
    _SKIN_DEPTH,
    _UNDERTONE,
    _WB_CAST,
    _BUILD_TYPE,
    StyleProfile,
)

_FIXTURES = os.path.join(_ROOT, "stylist", "tests", "fixtures")
_GOOD_PNG = os.path.join(_FIXTURES, "analyze_good.png")
_BAD_PNG = os.path.join(_FIXTURES, "analyze_bad.png")


def _all_confidences(p: StyleProfile):
    """Every confidence / 0..1 score in a StyleProfile, flattened."""
    return [
        p.image_quality.wb_confidence,
        p.person.presentation_confidence,
        p.coloring.undertone_confidence,
        p.coloring.season_confidence,
        p.face.shape_confidence,
        p.build.build_confidence,
    ]


class TestAnalyzeGood(unittest.TestCase):
    """A clean fixture replays into a structurally-valid StyleProfile."""

    def setUp(self):
        self.profile = analyze(_GOOD_PNG, cassette="analyze_good")

    def test_returns_styleprofile(self):
        self.assertIsInstance(self.profile, StyleProfile)

    def test_all_enums_legal(self):
        p = self.profile
        self.assertIn(p.image_quality.framing, _FRAMING)
        self.assertIn(p.image_quality.white_balance_cast, _WB_CAST)
        for issue in p.image_quality.issues:
            self.assertIn(issue, _ISSUES)
        self.assertIn(p.person.presentation, _PERSON_PRESENTATION)
        self.assertIn(p.coloring.skin_undertone, _UNDERTONE)
        self.assertIn(p.coloring.skin_depth, _SKIN_DEPTH)
        self.assertIn(p.coloring.contrast_level, _CONTRAST_LEVEL)
        self.assertIn(p.coloring.season, _SEASON)
        self.assertIn(p.face.shape, _FACE_SHAPE)
        self.assertIn(p.face.neck_length, _NECK_LENGTH)
        self.assertIn(p.build.type, _BUILD_TYPE)
        self.assertIn(p.build.shoulder_width, _SHOULDER)

    def test_every_confidence_in_unit_range(self):
        for c in _all_confidences(self.profile):
            self.assertIsInstance(c, float)
            self.assertGreaterEqual(c, 0.0)
            self.assertLessEqual(c, 1.0)

    def test_feasibility_present_and_bool(self):
        feas = self.profile.tryon_feasibility
        self.assertIsNotNone(feas)
        self.assertIsInstance(feas.hat, bool)
        self.assertIsInstance(feas.tshirt, bool)

    def test_round_trips_through_schema(self):
        # to_dict -> from_dict re-validates (the strict contract).
        StyleProfile.from_dict(self.profile.to_dict())

    def test_accepts_bytes_input(self):
        with open(_GOOD_PNG, "rb") as fh:
            raw = fh.read()
        p = analyze(raw, cassette="analyze_good")
        self.assertIsInstance(p, StyleProfile)


class TestAnalyzeBad(unittest.TestCase):
    """A degraded fixture is flagged unusable with non-empty issues."""

    def test_unusable_with_issues(self):
        p = analyze(_BAD_PNG, cassette="analyze_bad")
        self.assertIsInstance(p, StyleProfile)
        self.assertFalse(p.image_quality.usable)
        self.assertTrue(p.image_quality.issues, "expected non-empty image_quality.issues")
        for issue in p.image_quality.issues:
            self.assertIn(issue, _ISSUES)
        # Feasibility gate should route the orchestrator away from a try-on on garbage input.
        self.assertFalse(p.tryon_feasibility.hat)
        self.assertFalse(p.tryon_feasibility.tshirt)

    def test_graceful_degradation_low_undertone_confidence_allowed(self):
        # undertone_confidence < 0.5 must NOT be rejected (handled downstream).
        p = analyze(_BAD_PNG, cassette="analyze_bad")
        self.assertLess(p.coloring.undertone_confidence, 0.5)
        self.assertGreaterEqual(p.coloring.undertone_confidence, 0.0)


class TestAnalyzeRetryThenRaise(unittest.TestCase):
    """Schema-invalid model output → exactly one retry, then OpenAIError (anti-loop)."""

    def test_one_retry_then_raise(self):
        # Stub the transport to return a valid-JSON but schema-INVALID dict every time
        # (bad enum + out-of-range confidence). analyze() must try twice, never thrice.
        bad_result = {
            "image_quality": {
                "usable": True,
                "issues": ["not_a_real_issue"],  # illegal enum -> from_dict ValueError
                "framing": "head_and_torso",
                "white_balance_cast": "neutral",
                "wb_confidence": 1.7,  # out of [0,1] too
            }
        }
        with mock.patch.object(
            analyze_mod, "vision_json", return_value=bad_result
        ) as m:
            with self.assertRaises(OpenAIError):
                analyze(_GOOD_PNG, cassette="analyze_good")
        self.assertEqual(m.call_count, 2, "must be exactly 2 attempts (one retry), never 3")


@unittest.skipUnless(os.environ.get("STYLIST_LIVE") == "1", "live")
class TestAnalyzeLiveSmoke(unittest.TestCase):
    """Real vision call (only with STYLIST_LIVE=1) — must validate against the schema."""

    def test_live_good_photo_validates(self):
        p = analyze(_GOOD_PNG, model="gpt-5.5")
        self.assertIsInstance(p, StyleProfile)
        self.assertIsNotNone(p.tryon_feasibility)
        for c in _all_confidences(p):
            self.assertGreaterEqual(c, 0.0)
            self.assertLessEqual(c, 1.0)


if __name__ == "__main__":
    unittest.main()
