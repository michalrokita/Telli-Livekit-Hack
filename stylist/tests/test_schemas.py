"""Round-trip + validation tests for stylist.schemas (stdlib unittest).

Run from the repo root:
    python3 -m unittest discover -s stylist/tests -v
"""

import json
import os
import sys
import unittest

# Make `import stylist...` work regardless of the current working directory.
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from stylist import schemas  # noqa: E402
from stylist import _openai  # noqa: E402

_EXAMPLES = os.path.join(_ROOT, "stylist", "examples")


def _load(name: str) -> dict:
    with open(os.path.join(_EXAMPLES, name), "r", encoding="utf-8") as fh:
        return json.load(fh)


class TestRoundTrip(unittest.TestCase):
    """example JSON -> from_dict -> to_dict re-validates and key fields survive."""

    def _roundtrip(self, model, filename):
        data = _load(filename)
        obj = model.from_dict(data)
        out = obj.to_dict()
        # to_dict() output must itself re-validate (round-trippable).
        model.from_dict(out)
        # And it must be value-equal to the source JSON.
        self.assertEqual(data, out)
        return obj, out

    def test_style_profile(self):
        obj, out = self._roundtrip(schemas.StyleProfile, "style_profile.json")
        self.assertTrue(obj.image_quality.usable)
        self.assertEqual(obj.coloring.skin_undertone, "warm")
        self.assertEqual(obj.face.shape, "round")
        self.assertEqual(obj.build.type, "athletic")
        self.assertTrue(obj.tryon_feasibility.hat and obj.tryon_feasibility.tshirt)
        self.assertEqual(out["coloring"]["season"], "autumn")

    def test_catalog_product(self):
        obj, out = self._roundtrip(schemas.CatalogProduct, "catalog_product.json")
        self.assertEqual(obj.category, "tshirt")
        self.assertEqual(obj.color.hex, "#566b2e")
        self.assertEqual(obj.formality, 2)
        self.assertEqual(obj.presentation, "unisex")

    def test_match_profile(self):
        obj, out = self._roundtrip(schemas.MatchProfile, "match_profile.json")
        self.assertEqual(len(obj.palette), 3)
        self.assertEqual(obj.palette[0].name, "olive")
        self.assertEqual(obj.contrast_strategy, "bold")
        self.assertAlmostEqual(obj.vibe["streetwear"], 0.6)
        self.assertIn("crew", obj.tshirt.necklines_ok)

    def test_options(self):
        obj, out = self._roundtrip(schemas.Options, "options.json")
        self.assertEqual(len(obj.hats), 1)
        self.assertEqual(len(obj.tshirts), 1)
        self.assertEqual(len(obj.combos), 1)
        self.assertEqual(obj.tshirts[0].product_id, "TEE-OLIVE-001")
        self.assertEqual(obj.hats[0].breakdown.colour, 0.36)
        self.assertEqual(obj.combos[0].hat_id, "HAT-CAP-002")

    def test_tryon_result(self):
        obj, out = self._roundtrip(schemas.TryOnResult, "tryon_result.json")
        self.assertEqual(obj.status, "pass")
        self.assertEqual(obj.rendered_option_ids, ["HAT-CAP-002", "TEE-OLIVE-001"])
        self.assertIsNotNone(obj.critic_report)
        self.assertTrue(obj.critic_report.tshirt_correct)
        self.assertEqual(obj.critic_report.verdict, "pass")

    def test_tryon_result_null_critic(self):
        data = _load("tryon_result.json")
        data["critic_report"] = None
        data["status"] = "pending"
        obj = schemas.TryOnResult.from_dict(data)
        self.assertIsNone(obj.critic_report)
        # round-trips with critic_report = None
        self.assertIsNone(obj.to_dict()["critic_report"])
        schemas.TryOnResult.from_dict(obj.to_dict())


class TestValidation(unittest.TestCase):
    """Strict from_dict: bad enums / out-of-range / bad hex / missing fields raise ValueError."""

    def test_bad_enum_category(self):
        d = _load("catalog_product.json")
        d["category"] = "shoes"
        with self.assertRaises(ValueError):
            schemas.CatalogProduct.from_dict(d)

    def test_bad_enum_undertone(self):
        d = _load("style_profile.json")
        d["coloring"]["skin_undertone"] = "magenta"
        with self.assertRaises(ValueError):
            schemas.StyleProfile.from_dict(d)

    def test_confidence_over_one(self):
        d = _load("style_profile.json")
        d["image_quality"]["wb_confidence"] = 1.5
        with self.assertRaises(ValueError):
            schemas.StyleProfile.from_dict(d)

    def test_score_breakdown_over_one(self):
        d = _load("options.json")
        d["tshirts"][0]["breakdown"]["colour"] = 1.2
        with self.assertRaises(ValueError):
            schemas.Options.from_dict(d)

    def test_score_over_100(self):
        d = _load("options.json")
        d["hats"][0]["score"] = 150
        with self.assertRaises(ValueError):
            schemas.Options.from_dict(d)

    def test_bad_hex(self):
        d = _load("catalog_product.json")
        d["color"]["hex"] = "123456"
        with self.assertRaises(ValueError):
            schemas.CatalogProduct.from_dict(d)

    def test_formality_out_of_range(self):
        d = _load("catalog_product.json")
        d["formality"] = 9
        with self.assertRaises(ValueError):
            schemas.CatalogProduct.from_dict(d)

    def test_missing_required_field(self):
        d = _load("match_profile.json")
        del d["palette_strategy"]
        with self.assertRaises(ValueError):
            schemas.MatchProfile.from_dict(d)

    def test_negative_retry_count(self):
        d = _load("tryon_result.json")
        d["retry_count"] = -1
        with self.assertRaises(ValueError):
            schemas.TryOnResult.from_dict(d)


class TestOpenAIReplay(unittest.TestCase):
    """_openai imports cleanly (no httpx needed) and replay/encode work offline."""

    def test_missing_cassette_raises_replay_error(self):
        # STYLIST_LIVE is unset in the test env -> replay path.
        with self.assertRaises(_openai.OpenAIReplayError):
            _openai.complete_json(
                system="s", user_content="u", cassette="does_not_exist_xyz"
            )

    def test_no_cassette_name_raises_replay_error(self):
        with self.assertRaises(_openai.OpenAIReplayError):
            _openai.complete_json(system="s", user_content="u", cassette=None)

    def test_encode_image_b64_from_bytes(self):
        b64 = _openai.encode_image_b64(b"\x89PNG\r\n")
        self.assertIsInstance(b64, str)
        self.assertFalse(b64.startswith("data:"))

    def test_load_image_bytes_rejects_bad_type(self):
        with self.assertRaises(_openai.OpenAIError):
            _openai.load_image_bytes(1234)


if __name__ == "__main__":
    unittest.main()
