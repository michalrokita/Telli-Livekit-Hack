"""Tests for stylist.rules — deterministic match-profile + scoring + harmony.

Run from anywhere:
    python3 -m unittest discover -s stylist/tests -v
"""

import copy
import os
import sys
import unittest

# Make `import stylist...` work regardless of the current working directory.
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from stylist import rules, schemas  # noqa: E402


# --------------------------------------------------------------------------- #
# inline fixtures (no files needed)                                           #
# --------------------------------------------------------------------------- #
_WARM_AUTUMN_PROFILE = {
    "image_quality": {"usable": True, "issues": [], "framing": "head_and_torso",
                      "white_balance_cast": "neutral", "wb_confidence": 0.7},
    "person": {"apparent_age_range": "25-34", "presentation": "masculine",
               "presentation_confidence": 0.8},
    "coloring": {"skin_undertone": "warm", "undertone_cues": ["golden cast", "warm hair"],
                 "undertone_confidence": 0.6, "skin_depth": "medium",
                 "hair_color": "dark_brown", "eye_color": "hazel",
                 "contrast_level": "high", "season": "autumn", "season_confidence": 0.6},
    "face": {"shape": "round", "shape_confidence": 0.6, "neck_length": "short",
             "notable_features": ["strong jaw"]},
    "build": {"type": "athletic", "shoulder_width": "broad", "build_confidence": 0.6},
    "current_style": {"detected_vibe": ["streetwear", "casual"],
                      "currently_wearing": "black crewneck tee", "accessories": []},
    "tryon_feasibility": {"hat": True, "tshirt": True},
}


def _tee(pid, name, hex_, family, value, saturation, *, archetype="crew regular",
         pattern="solid", pattern_scale="none", tags=("streetwear", "minimal"),
         formality=2, presentation="unisex", sizes=("S", "M", "L")):
    return schemas.CatalogProduct.from_dict({
        "id": pid, "category": "tshirt", "title": name, "price": 29.9,
        "sizes": list(sizes), "image_url": "x.png", "archetype": archetype,
        "color": {"name": name, "hex": hex_, "family": family,
                  "value": value, "saturation": saturation},
        "pattern": pattern, "pattern_scale": pattern_scale, "style_tags": list(tags),
        "formality": formality, "presentation": presentation,
    })


def _hat(pid, name, hex_, family, value, saturation, *, archetype="6-panel cap",
         tags=("streetwear", "minimal"), presentation="unisex", sizes=("OS",)):
    return schemas.CatalogProduct.from_dict({
        "id": pid, "category": "hat", "title": name, "price": 24.0,
        "sizes": list(sizes), "image_url": "x.png", "archetype": archetype,
        "color": {"name": name, "hex": hex_, "family": family,
                  "value": value, "saturation": saturation},
        "pattern": "solid", "pattern_scale": "none", "style_tags": list(tags),
        "formality": 2, "presentation": presentation,
    })


class TestBuildMatchProfile(unittest.TestCase):
    def test_warm_autumn_strategy(self):
        prof = schemas.StyleProfile.from_dict(_WARM_AUTUMN_PROFILE)
        match = rules.build_match_profile(prof)
        self.assertEqual(match.palette_strategy, "warm-autumn")
        self.assertEqual(match.contrast_strategy, "bold")          # high contrast
        self.assertEqual(match.presentation_filter, "masculine")
        self.assertEqual(match.skin_depth, "medium")
        self.assertTrue(all(pc.family == "warm" for pc in match.palette))
        # round face -> V neckline present; short neck -> scoop present.
        self.assertIn("v", match.tshirt.necklines_ok)
        self.assertIn("scoop", match.tshirt.necklines_ok)
        # round face -> avoid low round beanie.
        self.assertIn("round beanie low", match.hat.archetypes_avoid)
        # vibe normalised, first item heaviest, sums to 1.
        self.assertAlmostEqual(sum(match.vibe.values()), 1.0, places=6)
        self.assertGreater(match.vibe["streetwear"], match.vibe["casual"])

    def test_low_confidence_safe_universal(self):
        d = copy.deepcopy(_WARM_AUTUMN_PROFILE)
        d["coloring"]["undertone_confidence"] = 0.3
        match = rules.build_match_profile(schemas.StyleProfile.from_dict(d))
        self.assertEqual(match.palette_strategy, "safe-universal")
        names = {pc.name for pc in match.palette}
        self.assertIn("navy", names)
        self.assertIn("charcoal", names)

    def test_cool_summer_strategy(self):
        d = copy.deepcopy(_WARM_AUTUMN_PROFILE)
        d["coloring"].update(skin_undertone="cool", season="summer",
                             undertone_confidence=0.8, contrast_level="low")
        match = rules.build_match_profile(schemas.StyleProfile.from_dict(d))
        self.assertEqual(match.palette_strategy, "cool-summer")
        self.assertEqual(match.contrast_strategy, "tonal")         # low contrast

    def test_match_profile_round_trips(self):
        match = rules.build_match_profile(schemas.StyleProfile.from_dict(_WARM_AUTUMN_PROFILE))
        # to_dict() must re-validate against the contract.
        schemas.MatchProfile.from_dict(match.to_dict())


class TestFeasibility(unittest.TestCase):
    def test_feasible_categories(self):
        prof = schemas.StyleProfile.from_dict(_WARM_AUTUMN_PROFILE)
        self.assertEqual(rules.feasible_categories(prof), {"hat", "tshirt"})

    def test_drops_infeasible_hat(self):
        d = copy.deepcopy(_WARM_AUTUMN_PROFILE)
        d["tryon_feasibility"]["hat"] = False
        prof = schemas.StyleProfile.from_dict(d)
        self.assertEqual(rules.feasible_categories(prof), {"tshirt"})


class TestScoring(unittest.TestCase):
    def setUp(self):
        self.match = rules.build_match_profile(
            schemas.StyleProfile.from_dict(_WARM_AUTUMN_PROFILE))

    def test_olive_outranks_icy_blue(self):
        olive = _tee("TEE-OLIVE", "olive", "#566b2e", "warm", "mid", "muted")
        icy = _tee("TEE-ICY", "icy blue", "#cfe8ff", "cool", "light", "muted")
        s_olive = rules.score_product(self.match, olive)
        s_icy = rules.score_product(self.match, icy)
        self.assertFalse(s_olive["hard_filtered"])
        self.assertFalse(s_icy["hard_filtered"])
        self.assertGreater(s_olive["score"], s_icy["score"])
        # colour axis specifically drives the gap.
        self.assertGreater(s_olive["breakdown"]["colour"], s_icy["breakdown"]["colour"])

    def test_rust_also_beats_icy(self):
        rust = _tee("TEE-RUST", "rust", "#b7410e", "warm", "mid", "mid")
        icy = _tee("TEE-ICY", "icy blue", "#cfe8ff", "cool", "light", "muted")
        self.assertGreater(rules.score_product(self.match, rust)["score"],
                           rules.score_product(self.match, icy)["score"])

    def test_breakdown_sums_to_score(self):
        olive = _tee("TEE-OLIVE", "olive", "#566b2e", "warm", "mid", "muted")
        res = rules.score_product(self.match, olive)
        self.assertAlmostEqual(sum(res["breakdown"].values()), res["score"] / 100.0, places=2)
        # explainable: non-empty reasons, score in range, breakdown axes in [0,1].
        self.assertTrue(res["reasons"])
        self.assertTrue(0.0 <= res["score"] <= 100.0)
        for v in res["breakdown"].values():
            self.assertTrue(0.0 <= v <= 1.0)

    def test_breakdown_axes_within_weight(self):
        olive = _tee("TEE-OLIVE", "olive", "#566b2e", "warm", "mid", "muted")
        b = rules.score_product(self.match, olive)["breakdown"]
        self.assertLessEqual(b["colour"], rules.WEIGHTS["colour"] + 1e-9)
        self.assertLessEqual(b["shape"], rules.WEIGHTS["shape"] + 1e-9)
        self.assertLessEqual(b["vibe"], rules.WEIGHTS["vibe"] + 1e-9)
        self.assertLessEqual(b["versatility"], rules.WEIGHTS["versatility"] + 1e-9)

    def test_hard_filter_wrong_presentation(self):
        fem = _tee("TEE-FEM", "rose", "#c08081", "cool", "mid", "muted",
                   presentation="feminine")
        res = rules.score_product(self.match, fem)  # filter is masculine
        self.assertTrue(res["hard_filtered"])
        self.assertEqual(res["score"], 0.0)
        self.assertTrue(any("presentation" in r for r in res["reasons"]))

    def test_unisex_not_filtered_on_presentation(self):
        uni = _tee("TEE-UNI", "olive", "#566b2e", "warm", "mid", "muted",
                   presentation="unisex")
        self.assertFalse(rules.score_product(self.match, uni)["hard_filtered"])

    def test_hard_filter_hat_archetype_in_avoid(self):
        # round face avoids "round beanie low".
        bad = _hat("HAT-BEANIE", "olive", "#556b2f", "warm", "mid", "muted",
                   archetype="round beanie")
        res = rules.score_product(self.match, bad)
        self.assertTrue(res["hard_filtered"])
        self.assertTrue(any("avoid" in r for r in res["reasons"]))

    def test_hard_filter_tee_attribute_in_avoid(self):
        # athletic build avoids "clingy".
        bad = _tee("TEE-CLINGY", "olive", "#556b2f", "warm", "mid", "muted",
                   archetype="clingy fitted", tags=("clingy",))
        res = rules.score_product(self.match, bad)
        self.assertTrue(res["hard_filtered"])

    def test_hard_filter_no_size(self):
        nosize = _tee("TEE-NOSIZE", "olive", "#566b2e", "warm", "mid", "muted", sizes=())
        self.assertTrue(rules.score_product(self.match, nosize)["hard_filtered"])

    def test_hard_filter_infeasible(self):
        olive = _tee("TEE-OLIVE", "olive", "#566b2e", "warm", "mid", "muted")
        res = rules.score_product(self.match, olive, feasible=False)
        self.assertTrue(res["hard_filtered"])
        self.assertTrue(any("infeasible" in r for r in res["reasons"]))

    def test_recommended_hat_scores_well(self):
        cap = _hat("HAT-CAP", "olive", "#556b2f", "warm", "mid", "muted",
                   archetype="6-panel cap")
        res = rules.score_product(self.match, cap)
        self.assertFalse(res["hard_filtered"])
        self.assertGreater(res["breakdown"]["shape"], 0.2)


class TestHarmony(unittest.TestCase):
    def test_tonal_beats_clash_for_tonal_person(self):
        # tonal person: two olives (tonal) should beat a saturated red/green clash.
        tonal = rules.outfit_harmony("#556b2f", "#566b2e", "tonal")
        clash = rules.outfit_harmony("#cc0000", "#00aa00", "tonal")
        self.assertGreater(tonal, clash)
        self.assertGreater(tonal, 0.85)

    def test_neutral_anchor_is_safe(self):
        # a charcoal hat with any tee reads safe.
        h = rules.outfit_harmony("#36454f", "#b7410e", "tonal")
        self.assertGreater(h, 0.6)

    def test_bold_tolerates_complementary(self):
        # red/cyan complementary scores higher under bold than under tonal.
        bold = rules.outfit_harmony("#cc0000", "#00cccc", "bold")
        tonal = rules.outfit_harmony("#cc0000", "#00cccc", "tonal")
        self.assertGreater(bold, tonal)

    def test_returns_unit_interval(self):
        for a, b, cs in [("#000000", "#ffffff", "tonal"),
                         ("#ff0000", "#00ff00", "bold"),
                         ("#556b2f", "#556b2f", "tonal")]:
            v = rules.outfit_harmony(a, b, cs)
            self.assertTrue(0.0 <= v <= 1.0)


if __name__ == "__main__":
    unittest.main()
