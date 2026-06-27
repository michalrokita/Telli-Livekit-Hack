"""Offline (deterministic + replay) + guarded-live tests for stylist.recommend.

Run from the repo root:
    python3 -m unittest discover -s stylist/tests -v

The deterministic core (scoring/ordering/hard-filters/combos) needs NO network. The P2
rationale layer is exercised two ways with no network: via a hand-authored cassette
(``recommend_p2_warm``) and via the templated fallback (cassette=None → replay miss → template).
The single live smoke test is skipped unless ``STYLIST_LIVE=1``.
"""

import copy
import os
import sys
import unittest

# Make `import stylist...` work regardless of the current working directory.
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from stylist import schemas  # noqa: E402
from stylist.catalog import load_catalog  # noqa: E402
from stylist.recommend import recommend  # noqa: E402
from stylist import rules  # noqa: E402

# --------------------------------------------------------------------------- #
# fixtures                                                                     #
# --------------------------------------------------------------------------- #
# warm undertone · autumn · athletic build · streetwear vibe · high contrast (bold)
_WARM_ATHLETIC = {
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

# a low-contrast (tonal) variant, oval/average so nothing extra gets hard-filtered.
_WARM_TONAL = copy.deepcopy(_WARM_ATHLETIC)
_WARM_TONAL["person"]["presentation"] = "androgynous"
_WARM_TONAL["coloring"]["contrast_level"] = "low"
_WARM_TONAL["face"] = {"shape": "oval", "shape_confidence": 0.6, "neck_length": "average",
                       "notable_features": []}
_WARM_TONAL["build"]["shoulder_width"] = "average"


def _profile(d):
    return schemas.StyleProfile.from_dict(d)


def _catalog_hex():
    return {p.id: p.color.hex for p in load_catalog()}


class TestRecommendOrdering(unittest.TestCase):
    """Deterministic core: palette-correct + build-correct ranking, hard-filtered absent."""

    def setUp(self):
        self.opt = recommend(_profile(_WARM_ATHLETIC), n=2)

    def test_validates_as_options(self):
        # output is a real Options that survives the strict round-trip contract.
        self.assertIsInstance(self.opt, schemas.Options)
        schemas.Options.from_dict(self.opt.to_dict())

    def test_mvp_shape_two_each(self):
        self.assertEqual(len(self.opt.hats), 2)
        self.assertEqual(len(self.opt.tshirts), 2)

    def test_top_picks_are_warm_palette(self):
        # olive (warm) tops both categories for a warm-autumn profile.
        self.assertEqual(self.opt.tshirts[0].product_id, "TEE-OLIVE-001")
        self.assertEqual(self.opt.hats[0].product_id, "HAT-CAP-009")
        # the top-2 tees are the warm olive + rust.
        self.assertEqual({o.product_id for o in self.opt.tshirts},
                         {"TEE-OLIVE-001", "TEE-RUST-002"})

    def test_warm_outranks_cool(self):
        # full ranking (large n): warm items sit above their cool counterparts.
        full = recommend(_profile(_WARM_ATHLETIC), n=99)
        tee_ids = [o.product_id for o in full.tshirts]
        hat_ids = [o.product_id for o in full.hats]
        self.assertLess(tee_ids.index("TEE-OLIVE-001"), tee_ids.index("TEE-NAVY-003"))
        self.assertLess(tee_ids.index("TEE-RUST-002"), tee_ids.index("TEE-TEAL-006"))
        self.assertLess(hat_ids.index("HAT-CAP-009"), hat_ids.index("HAT-BEANIE-011"))
        # scores are sorted strictly non-increasing.
        self.assertEqual([o.score for o in full.tshirts],
                         sorted((o.score for o in full.tshirts), reverse=True))

    def test_hard_filtered_items_absent(self):
        full = recommend(_profile(_WARM_ATHLETIC), n=99)
        ids = {o.product_id for o in full.hats + full.tshirts}
        # feminine tee/beanie dropped by the masculine presentation filter;
        # the rust bucket dropped by the round-face "snug bucket" avoid rule.
        self.assertNotIn("TEE-CREAM-005", ids)
        self.assertNotIn("HAT-BEANIE-014", ids)
        self.assertNotIn("HAT-BUCKET-012", ids)

    def test_every_item_has_rationale(self):
        for o in self.opt.hats + self.opt.tshirts:
            self.assertTrue(o.rationale.strip(), f"empty rationale on {o.product_id}")


class TestCombos(unittest.TestCase):
    """combo=True → 1-2 OutfitCombo; tonal person → tonal pairing wins, harmony in [0,1]."""

    def test_combo_off_by_default(self):
        self.assertEqual(recommend(_profile(_WARM_ATHLETIC)).combos, [])
        self.assertEqual(recommend(_profile(_WARM_ATHLETIC), combo=False).combos, [])

    def test_tonal_person_gets_tonal_harmony(self):
        opt = recommend(_profile(_WARM_TONAL), combo=True)
        self.assertTrue(1 <= len(opt.combos) <= 2)
        for c in opt.combos:
            self.assertTrue(0.0 <= c.harmony_score <= 1.0)
            self.assertTrue(0.0 <= c.individual_quality <= 1.0)
            self.assertTrue(0.0 <= c.style_coherence <= 1.0)
            self.assertTrue(c.rationale.strip())
        best = opt.combos[0]
        # the winning pair is the tonal olive-on-olive look, scored high.
        self.assertEqual(best.tshirt_id, "TEE-OLIVE-001")
        self.assertGreaterEqual(best.harmony_score, 0.9)

    def test_harmony_respects_contrast_strategy(self):
        # the chosen pair's hexes score higher harmony under tonal than under bold
        # (low-contrast person is nudged toward tonal looks).
        hexes = _catalog_hex()
        opt = recommend(_profile(_WARM_TONAL), combo=True)
        h, t = opt.combos[0].hat_id, opt.combos[0].tshirt_id
        tonal = rules.outfit_harmony(hexes[h], hexes[t], "tonal")
        bold = rules.outfit_harmony(hexes[h], hexes[t], "bold")
        self.assertGreater(tonal, bold)

    def test_combo_ids_reference_returned_categories(self):
        opt = recommend(_profile(_WARM_TONAL), combo=True)
        cat = {p.id: p.category for p in load_catalog()}
        for c in opt.combos:
            self.assertEqual(cat[c.hat_id], "hat")
            self.assertEqual(cat[c.tshirt_id], "tshirt")


class TestRationaleViaCassette(unittest.TestCase):
    """P2 rationales overlaid from a hand-authored cassette; LLM cannot add/alter items."""

    def setUp(self):
        self.opt = recommend(_profile(_WARM_ATHLETIC), n=2, combo=True,
                             cassette="recommend_p2_warm")

    def test_overlay_applied_to_every_item(self):
        for o in self.opt.hats + self.opt.tshirts:
            self.assertTrue(o.rationale.startswith("[P2]"),
                            f"cassette rationale not merged onto {o.product_id}: {o.rationale!r}")

    def test_combo_rationale_overlaid(self):
        # the CAP-009 / OLIVE pair is the engine's #1 combo and is in the cassette.
        top = self.opt.combos[0]
        self.assertEqual((top.hat_id, top.tshirt_id), ("HAT-CAP-009", "TEE-OLIVE-001"))
        self.assertTrue(top.rationale.startswith("[P2]"))

    def test_phantom_item_ignored(self):
        ids = {o.product_id for o in self.opt.hats + self.opt.tshirts}
        self.assertNotIn("TEE-FAKE-999", ids)  # model may NOT inject products

    def test_colours_unchanged(self):
        # the LLM may not change colours — every returned hex equals the catalog's.
        cat = _catalog_hex()
        for o in self.opt.hats + self.opt.tshirts:
            self.assertEqual(o.color_hex, cat[o.product_id])


class TestRationaleTemplatedFallback(unittest.TestCase):
    """No cassette + offline → templated, attribute-tied rationales, no network, no crash."""

    def setUp(self):
        self.opt = recommend(_profile(_WARM_ATHLETIC), n=2, combo=True)  # cassette=None

    def test_rationales_non_empty_and_not_p2(self):
        for o in self.opt.hats + self.opt.tshirts:
            self.assertTrue(o.rationale.strip())
            self.assertFalse(o.rationale.startswith("[P2]"))  # came from the template, not P2
        for c in self.opt.combos:
            self.assertTrue(c.rationale.strip())

    def test_rationales_are_attribute_tied(self):
        tee = next(o for o in self.opt.tshirts if o.product_id == "TEE-OLIVE-001")
        # tied to a specific profile attribute: athletic build + warm-autumn palette.
        self.assertIn("athletic", tee.rationale)
        self.assertIn("warm autumn", tee.rationale)
        hat = next(o for o in self.opt.hats if o.product_id == "HAT-CAP-009")
        self.assertTrue("round" in hat.rationale or "warm autumn" in hat.rationale)


class TestInfeasibleCategory(unittest.TestCase):
    """Infeasible category comes back empty; the other still returns; no combos possible."""

    def test_infeasible_hat_empty_tees_present(self):
        d = copy.deepcopy(_WARM_ATHLETIC)
        d["tryon_feasibility"]["hat"] = False
        opt = recommend(_profile(d), n=2, combo=True)
        self.assertEqual(opt.hats, [])
        self.assertTrue(opt.tshirts)               # tshirts still recommended
        self.assertEqual(opt.combos, [])           # a combo needs both categories
        schemas.Options.from_dict(opt.to_dict())   # still a valid Options


@unittest.skipUnless(os.environ.get("STYLIST_LIVE") == "1", "live")
class TestRecommendLiveSmoke(unittest.TestCase):
    """Real P2 (gpt-5.4-mini) over a real shortlist — Options validates, no added items."""

    def test_live_rationales(self):
        opt = recommend(_profile(_WARM_ATHLETIC), n=2, combo=True)  # live: real P2 call
        self.assertIsInstance(opt, schemas.Options)
        schemas.Options.from_dict(opt.to_dict())
        catalog_ids = {p.id for p in load_catalog()}
        for o in opt.hats + opt.tshirts:
            self.assertTrue(o.rationale.strip())
            self.assertIn(o.product_id, catalog_ids)   # no invented products
        for c in opt.combos:
            self.assertIn(c.hat_id, catalog_ids)
            self.assertIn(c.tshirt_id, catalog_ids)


if __name__ == "__main__":
    unittest.main()
