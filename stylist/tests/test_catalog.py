"""Offline/replay tests for stylist.catalog (Phase 4 — seed catalog + P-enrich).

All tests run green with NO network: the vision pass replays from the hand-authored
cassettes in fixtures/cassettes/catalog_<id>.json. The LIVE smoke is skipped unless
STYLIST_LIVE=1.

Run from the repo root:
    python3 -m unittest discover -s stylist/tests -v
"""

import os
import re
import sys
import unittest
from unittest import mock

# Make `import stylist...` work regardless of the current working directory.
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from stylist import catalog  # noqa: E402
from stylist import schemas  # noqa: E402

_HEX = re.compile(r"^#[0-9a-f]{6}$")
_LIVE = os.environ.get("STYLIST_LIVE") == "1"


def _assert_valid_product(tc: unittest.TestCase, p) -> None:
    tc.assertIsInstance(p, schemas.CatalogProduct)
    tc.assertIn(p.category, {"hat", "tshirt"})
    tc.assertTrue(_HEX.match(p.color.hex), f"bad hex: {p.color.hex!r}")
    tc.assertIn(p.color.family, {"warm", "cool", "neutral"})
    tc.assertIn(p.color.value, {"light", "mid", "dark"})
    tc.assertIn(p.color.saturation, {"muted", "mid", "bright"})
    tc.assertTrue(1 <= p.formality <= 5)
    tc.assertIn(p.presentation, {"masculine", "feminine", "unisex"})


class TestSeedCatalog(unittest.TestCase):
    """The raw seed + its synthetic images are well-formed."""

    def test_sample_is_balanced_hats_and_tees(self):
        raw = catalog.load_sample()
        self.assertGreaterEqual(len(raw), 12)
        self.assertLessEqual(len(raw), 16)
        cats = [r["category"] for r in raw]
        self.assertGreaterEqual(cats.count("hat"), 4)
        self.assertGreaterEqual(cats.count("tshirt"), 4)
        for r in raw:
            for k in ("id", "category", "title", "price", "sizes", "image_url"):
                self.assertIn(k, r)
            self.assertTrue(r["image_url"].startswith("catalog/images/"))

    def test_synthetic_images_exist(self):
        for r in catalog.load_sample():
            path = catalog._image_path(r["image_url"])
            self.assertTrue(path.exists(), f"missing image: {path}")
            self.assertGreater(path.stat().st_size, 0)


class TestEnrich(unittest.TestCase):
    """enrich() / enrich_catalog() over the cassettes yield valid CatalogProduct[]."""

    def test_enrich_single_product_merges_raw_and_enriched(self):
        raw = catalog.load_sample()[0]  # TEE-OLIVE-001
        cp = catalog.enrich(raw)  # replay from catalog_TEE-OLIVE-001.json
        _assert_valid_product(self, cp)
        # raw fields are preserved verbatim ...
        self.assertEqual(cp.id, raw["id"])
        self.assertEqual(cp.category, raw["category"])
        self.assertEqual(cp.title, raw["title"])
        self.assertEqual(cp.price, raw["price"])
        self.assertEqual(cp.sizes, raw["sizes"])
        self.assertEqual(cp.image_url, raw["image_url"])
        # ... and the colour was read from the (cassette-backed) pixels, not the title.
        self.assertEqual(cp.color.hex, "#556b2f")
        self.assertEqual(cp.color.family, "warm")

    def test_enrich_catalog_replay_yields_valid_products(self):
        prods = catalog.enrich_catalog(force=True)  # exercise the real enrich path
        self.assertEqual(len(prods), len(catalog.load_sample()))
        for p in prods:
            _assert_valid_product(self, p)
        cats = [p.category for p in prods]
        self.assertEqual(cats.count("tshirt"), 8)
        self.assertEqual(cats.count("hat"), 6)
        # ids are unique
        self.assertEqual(len({p.id for p in prods}), len(prods))

    def test_enriched_json_loads_via_load_catalog(self):
        catalog.enrich_catalog()  # ensure the cache exists
        loaded = catalog.load_catalog()
        self.assertEqual(len(loaded), len(catalog.load_sample()))
        for p in loaded:
            _assert_valid_product(self, p)
        # load_catalog -> to_dict -> from_dict round-trips (cache is schema-clean)
        for p in loaded:
            schemas.CatalogProduct.from_dict(p.to_dict())

    def test_idempotent_second_run_re_enriches_nothing(self):
        catalog.enrich_catalog()  # make sure enriched.json is present for every id
        # If a second (non-force) run tried to enrich anything, this patched enrich
        # would blow up — proving the cache short-circuits every id.
        with mock.patch.object(
            catalog, "enrich", side_effect=AssertionError("must not re-enrich")
        ):
            prods = catalog.enrich_catalog()  # force defaults to False
        self.assertEqual(len(prods), len(catalog.load_sample()))
        for p in prods:
            _assert_valid_product(self, p)

    @unittest.skipUnless(_LIVE, "live OpenAI call (set STYLIST_LIVE=1 + OPENAI_API_KEY)")
    def test_live_smoke_enrich_one_product(self):
        raw = catalog.load_sample()[0]
        cp = catalog.enrich(raw, model="gpt-5.5", cassette="catalog_live_smoke")
        _assert_valid_product(self, cp)
        self.assertEqual(cp.id, raw["id"])
        self.assertTrue(_HEX.match(cp.color.hex))


if __name__ == "__main__":
    unittest.main()
