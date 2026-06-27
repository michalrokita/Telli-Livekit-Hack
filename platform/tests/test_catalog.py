"""Offline tests for platform.catalog — the catalog read-side (stdlib unittest).

No network, no key: the stand-in store is ingested via cassette replay, then read back
as typed ``CatalogProduct`` objects. The read path NEVER re-enriches.

Run from the repo root::

    python3 -m unittest platform.tests.test_catalog -v
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from platform import catalog, ingest  # noqa: E402
from platform.tests.support import temp_db  # noqa: E402
from stylist import schemas  # noqa: E402

_STANDIN = os.path.join(_ROOT, "platform", "tests", "fixtures", "store", "standin.products.json")
_STORE = {"id": "standin", "name": "Stand-in Store", "url": "https://standin.test"}


class TestLoadStoreCatalog(unittest.TestCase):
    def _ingest(self, conn, imgdir):
        return ingest.ingest_store(conn, _STORE, ingest.BrowserMcpDump(_STANDIN), image_dir=imgdir)

    def test_load_returns_typed_catalog_products(self):
        with temp_db() as conn, tempfile.TemporaryDirectory() as imgdir:
            self._ingest(conn, imgdir)
            cat = catalog.load_store_catalog(conn, "standin")
            self.assertEqual(len(cat), 14)
            for cp in cat:
                self.assertIsInstance(cp, schemas.CatalogProduct)
                self.assertTrue(os.path.isabs(cp.image_url), cp.image_url)
                self.assertIn(cp.category, ("hat", "tshirt"))

    def test_wrong_store_id_is_empty(self):
        with temp_db() as conn, tempfile.TemporaryDirectory() as imgdir:
            self._ingest(conn, imgdir)
            self.assertEqual(catalog.load_store_catalog(conn, "does-not-exist"), [])

    def test_load_dicts_convenience(self):
        with temp_db() as conn, tempfile.TemporaryDirectory() as imgdir:
            self._ingest(conn, imgdir)
            dicts = catalog.load_store_catalog_dicts(conn, "standin")
            self.assertEqual(len(dicts), 14)
            self.assertTrue(all(isinstance(d, dict) for d in dicts))
            # each dict rebuilds into a CatalogProduct (round-trips through schemas)
            schemas.CatalogProduct.from_dict(dicts[0])

    def test_skips_non_dict_enriched_rows(self):
        # defensive: a row whose enriched is None must be skipped, never crash.
        from platform import db

        with temp_db() as conn, tempfile.TemporaryDirectory() as imgdir:
            self._ingest(conn, imgdir)
            db.upsert_store(conn, id="empty", name="Empty", url="u")
            db.upsert_product(
                conn, id="ghost", store_id="empty", title="t", price=1.0,
                sizes=[], image_path=None, enriched=None,
            )
            self.assertEqual(catalog.load_store_catalog(conn, "empty"), [])
            # the real store is unaffected
            self.assertEqual(len(catalog.load_store_catalog(conn, "standin")), 14)


if __name__ == "__main__":
    unittest.main()
