"""Offline behaviour tests for platform.ingest (stdlib unittest).

No network, no OPENAI_API_KEY. The stand-in store dump reuses the seed product ids, so
``catalog_<id>.json`` cassettes replay the enrichment vision pass entirely OFFLINE.

Run from the repo root::

    python3 -m unittest platform.tests.test_ingest -v
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

# Make ``import platform...`` resolve to this repo regardless of cwd (mirrors test_db).
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from platform import db, ingest  # noqa: E402
from platform.tests.support import temp_db  # noqa: E402
from stylist import schemas  # noqa: E402

_FIXTURES = os.path.join(_ROOT, "platform", "tests", "fixtures", "store")
_STANDIN = os.path.join(_FIXTURES, "standin.products.json")
_IMAGES = os.path.join(_FIXTURES, "images")
_SAMPLE_HTML = os.path.join(_FIXTURES, "sample_store.html")

_STORE = {"id": "standin", "name": "Stand-in Store", "url": "https://standin.test"}


def _img(name: str) -> str:
    return os.path.join(_IMAGES, name)


class _ListAdapter(ingest.StoreAdapter):
    """Trivial in-test adapter: yields a fixed list of raw product dicts."""

    def __init__(self, items):
        self._items = items

    def products(self):
        return [dict(i) for i in self._items]


# --------------------------------------------------------------------------- #
# pure helpers                                                                 #
# --------------------------------------------------------------------------- #
class TestPureHelpers(unittest.TestCase):
    def test_make_product_id_is_deterministic(self):
        raw = {"title": "Olive Crew Tee", "image_url": "images/x.png"}
        self.assertEqual(ingest.make_product_id(raw), ingest.make_product_id(dict(raw)))

    def test_make_product_id_varies_with_image(self):
        a = ingest.make_product_id({"title": "Olive Crew Tee", "image_url": "a.png"})
        b = ingest.make_product_id({"title": "Olive Crew Tee", "image_url": "b.png"})
        self.assertNotEqual(a, b)
        self.assertTrue(a.startswith("olive-crew-tee-"))

    def test_infer_category_hat_keywords(self):
        for title in ("Rust Cotton Bucket Hat", "Olive 6-Panel Cap", "Navy Ribbed Beanie",
                      "Charcoal Short-Brim Fedora", "Black Snapback"):
            self.assertEqual(ingest.infer_category({"title": title}), "hat")

    def test_infer_category_tshirt_default(self):
        self.assertEqual(ingest.infer_category({"title": "Classic Navy Crew Tee"}), "tshirt")
        self.assertEqual(ingest.infer_category({"title": ""}), "tshirt")


# --------------------------------------------------------------------------- #
# BrowserMcpDump adapter                                                       #
# --------------------------------------------------------------------------- #
class TestBrowserMcpDump(unittest.TestCase):
    def test_products_absolutise_images(self):
        raws = ingest.BrowserMcpDump(_STANDIN).products()
        self.assertGreaterEqual(len(raws), 6)
        self.assertEqual(len(raws), 14)
        for r in raws:
            self.assertTrue(os.path.isabs(r["image_url"]), r["image_url"])
            self.assertTrue(os.path.exists(r["image_url"]), r["image_url"])


# --------------------------------------------------------------------------- #
# ingest_store — full offline ingest via cassette replay                      #
# --------------------------------------------------------------------------- #
class TestIngestStore(unittest.TestCase):
    def test_full_ingest_offline(self):
        with temp_db() as conn, tempfile.TemporaryDirectory() as imgdir:
            summary = ingest.ingest_store(
                conn, _STORE, ingest.BrowserMcpDump(_STANDIN), image_dir=imgdir
            )
            # summary dict shape
            self.assertEqual(set(summary), {"found", "enriched", "skipped", "reasons"})
            self.assertEqual(summary["found"], 14)
            self.assertEqual(summary["enriched"], 14)
            self.assertEqual(summary["found"], summary["enriched"])
            self.assertEqual(summary["skipped"], 0)
            self.assertEqual(summary["reasons"], [])  # no SKIP, no DEDUPE on the clean dump

            rows = db.list_products(conn, "standin")
            self.assertEqual(len(rows), 14)

            for row in rows:
                got = db.get_product(conn, row["id"])
                self.assertIsInstance(got["enriched"], dict)
                # the opaque enriched dict rebuilds into a typed CatalogProduct
                cp = schemas.CatalogProduct.from_dict(got["enriched"])
                self.assertEqual(cp.id, row["id"])
                # image_path persisted, and the enriched image_url is absolute
                self.assertTrue(got["image_path"])
                self.assertTrue(os.path.isabs(got["enriched"]["image_url"]))

    def test_idempotent_reingest(self):
        with temp_db() as conn, tempfile.TemporaryDirectory() as imgdir:
            s1 = ingest.ingest_store(conn, _STORE, ingest.BrowserMcpDump(_STANDIN), image_dir=imgdir)
            n1 = len(db.list_products(conn, "standin"))
            s2 = ingest.ingest_store(conn, _STORE, ingest.BrowserMcpDump(_STANDIN), image_dir=imgdir)
            n2 = len(db.list_products(conn, "standin"))
            self.assertEqual(n1, 14)
            self.assertEqual(n2, 14)  # upsert, never duplicated
            self.assertEqual(s1, s2)  # summary stays consistent

    def test_dedupe_same_id_counts_once(self):
        olive = {
            "id": "TEE-OLIVE-001",
            "category": "tshirt",
            "title": "Heavyweight Olive Crew Tee",
            "price": 29.9,
            "sizes": ["S", "M", "L", "XL"],
            "image_url": _img("tee-olive-001.png"),
        }
        with temp_db() as conn, tempfile.TemporaryDirectory() as imgdir:
            summary = ingest.ingest_store(
                conn, _STORE, _ListAdapter([olive, dict(olive)]), image_dir=imgdir
            )
            self.assertEqual(summary["found"], 1)        # duplicate not counted in found
            self.assertEqual(summary["enriched"], 1)
            self.assertEqual(summary["skipped"], 0)      # dedupe is NOT a skip
            self.assertTrue(
                any(r.startswith("DEDUPE TEE-OLIVE-001") for r in summary["reasons"]),
                summary["reasons"],
            )
            self.assertEqual(len(db.list_products(conn, "standin")), 1)

    def test_skip_missing_image_with_reason(self):
        good = {
            "id": "TEE-OLIVE-001",
            "category": "tshirt",
            "title": "Heavyweight Olive Crew Tee",
            "price": 29.9,
            "sizes": ["S", "M", "L", "XL"],
            "image_url": _img("tee-olive-001.png"),
        }
        bad = {
            "id": "TEE-RUST-002",
            "category": "tshirt",
            "title": "Garment-Dyed Rust Pocket Tee",
            "price": 32.0,
            "sizes": ["S"],
            "image_url": "/no/such/dir/missing.png",
        }
        with temp_db() as conn, tempfile.TemporaryDirectory() as imgdir:
            summary = ingest.ingest_store(
                conn, _STORE, _ListAdapter([good, bad]), image_dir=imgdir
            )
            self.assertEqual(summary["found"], 2)
            self.assertEqual(summary["enriched"], 1)
            self.assertGreaterEqual(summary["skipped"], 1)
            # a precise reason line names the product and the missing image
            self.assertTrue(
                any("TEE-RUST-002" in r and "image not found" in r for r in summary["reasons"]),
                summary["reasons"],
            )
            # the OTHER good product still ingested (no abort)
            ids = [p["id"] for p in db.list_products(conn, "standin")]
            self.assertEqual(ids, ["TEE-OLIVE-001"])

    def test_tolerates_missing_price_and_sizes(self):
        # raw with NO price and NO sizes keys, reusing a cassette-backed id.
        raw = {
            "id": "TEE-NAVY-003",
            "category": "tshirt",
            "title": "Classic Navy Crew Tee",
            "image_url": _img("tee-navy-003.png"),
        }
        with temp_db() as conn, tempfile.TemporaryDirectory() as imgdir:
            summary = ingest.ingest_store(conn, _STORE, _ListAdapter([raw]), image_dir=imgdir)
            self.assertEqual(summary["enriched"], 1)
            self.assertEqual(summary["skipped"], 0)
            got = db.get_product(conn, "TEE-NAVY-003")
            self.assertEqual(got["price"], 0.0)   # coerced default
            self.assertEqual(got["sizes"], [])    # empty default

    def test_tolerates_oddly_typed_price(self):
        raw = {
            "id": "TEE-NAVY-003",
            "category": "tshirt",
            "title": "Classic Navy Crew Tee",
            "price": "$24.90",   # messy string price
            "sizes": ["M"],
            "image_url": _img("tee-navy-003.png"),
        }
        with temp_db() as conn, tempfile.TemporaryDirectory() as imgdir:
            ingest.ingest_store(conn, _STORE, _ListAdapter([raw]), image_dir=imgdir)
            self.assertEqual(db.get_product(conn, "TEE-NAVY-003")["price"], 24.9)

    def test_errors_back_compat_list(self):
        bad = {
            "id": "TEE-RUST-002",
            "category": "tshirt",
            "title": "Rust",
            "image_url": "/no/such/dir/missing.png",
        }
        errors = []
        with temp_db() as conn, tempfile.TemporaryDirectory() as imgdir:
            summary = ingest.ingest_store(
                conn, _STORE, _ListAdapter([bad]), image_dir=imgdir, errors=errors
            )
            self.assertEqual(summary["skipped"], 1)
            self.assertEqual(len(errors), 1)
            self.assertEqual(errors[0][0]["id"], "TEE-RUST-002")
            self.assertIsInstance(errors[0][1], Exception)


# --------------------------------------------------------------------------- #
# HttpStoreAdapter.parse — pure, no network                                   #
# --------------------------------------------------------------------------- #
class TestHttpParse(unittest.TestCase):
    def setUp(self):
        with open(_SAMPLE_HTML, encoding="utf-8") as fh:
            self.html = fh.read()

    def test_parse_extracts_only_products(self):
        raws = ingest.HttpStoreAdapter().parse(self.html)
        # promo banner + footer (both carry title/price classes) are NOT products
        self.assertEqual(len(raws), 3)
        by_title = {r["title"]: r for r in raws}
        self.assertEqual(
            set(by_title),
            {"Blue Crew Tee", "Black 5-Panel Cap", "Vintage Cream Boxy Tee"},
        )

        blue = by_title["Blue Crew Tee"]
        self.assertEqual(blue["price"], 24.0)
        self.assertEqual(blue["sizes"], ["S", "M", "L", "XL"])
        self.assertEqual(blue["image_url"], "/media/blue-crew-tee.png")  # relative, no base url

        cap = by_title["Black 5-Panel Cap"]
        self.assertEqual(cap["price"], 26.5)  # "€26.50" coerced
        self.assertEqual(cap["sizes"], ["OS"])

        cream = by_title["Vintage Cream Boxy Tee"]
        self.assertEqual(cream["price"], 34.9)  # "34.90 USD" coerced
        self.assertEqual(cream["image_url"], "https://cdn.example.com/cream-boxy-tee.png")

    def test_parse_joins_relative_images_against_base_url(self):
        raws = ingest.HttpStoreAdapter("https://shop.example.com").parse(self.html)
        blue = next(r for r in raws if r["title"] == "Blue Crew Tee")
        self.assertEqual(blue["image_url"], "https://shop.example.com/media/blue-crew-tee.png")
        # absolute cdn url is left untouched
        cream = next(r for r in raws if r["title"] == "Vintage Cream Boxy Tee")
        self.assertEqual(cream["image_url"], "https://cdn.example.com/cream-boxy-tee.png")


if __name__ == "__main__":
    unittest.main()
