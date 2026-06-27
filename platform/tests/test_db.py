"""Round-trip + behaviour tests for platform.db (stdlib unittest).

No network, no OPENAI_API_KEY required. Run from the repo root::

    python3 -m unittest discover -s platform/tests -v
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import unittest

# Make ``import platform...`` work regardless of cwd (mirrors the stylist tests).
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from platform import db  # noqa: E402
from platform.tests.support import temp_db  # noqa: E402

# A real CatalogProduct dict — the first item of the enriched catalog — used as
# an opaque JSON payload to prove byte-for-byte round-tripping.
_ENRICHED_PATH = os.path.join(_ROOT, "stylist", "catalog", "enriched.json")
with open(_ENRICHED_PATH, "r", encoding="utf-8") as _fh:
    _ENRICHED_PRODUCT = json.load(_fh)[0]

# The reduced schema: exactly two tables.
_ALL_TABLES = {"stores", "products"}


# --------------------------------------------------------------------------- #
# connect / schema                                                             #
# --------------------------------------------------------------------------- #
class TestSchema(unittest.TestCase):
    def _table_names(self, conn) -> set:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
        return {r["name"] for r in rows}

    def test_both_tables_created(self):
        with temp_db() as conn:
            self.assertEqual(_ALL_TABLES, self._table_names(conn) & _ALL_TABLES)
            self.assertIn("stores", self._table_names(conn))
            self.assertIn("products", self._table_names(conn))

    def test_no_dropped_tables_remain(self):
        # The user/session/identity/feedback tables were cut from scope.
        with temp_db() as conn:
            names = self._table_names(conn)
            for gone in ("users", "sessions", "identities", "liked_items", "feedback"):
                self.assertNotIn(gone, names)

    def test_init_schema_is_idempotent(self):
        with temp_db() as conn:
            # connect() already ran it once; a second + third call must not error.
            db.init_schema(conn)
            db.init_schema(conn)
            self.assertTrue(_ALL_TABLES.issubset(self._table_names(conn)))

    def test_foreign_keys_pragma_active(self):
        with temp_db() as conn:
            (flag,) = conn.execute("PRAGMA foreign_keys").fetchone()
            self.assertEqual(flag, 1)

    def test_row_factory_is_row(self):
        with temp_db() as conn:
            self.assertIs(conn.row_factory, sqlite3.Row)

    def test_memory_and_tempfile_both_work(self):
        # in-memory
        mem = db.connect(":memory:")
        try:
            self.assertTrue(_ALL_TABLES.issubset(self._table_names(mem)))
            db.upsert_store(mem, id="s1", name="Mem", url="https://mem.test")
            self.assertEqual(db.get_store(mem, "s1")["name"], "Mem")
        finally:
            mem.close()
        # temp file
        with temp_db() as conn:
            db.upsert_store(conn, id="s1", name="File", url="https://file.test")
            self.assertEqual(db.get_store(conn, "s1")["name"], "File")

    def test_env_var_selects_db_path(self):
        prev = os.environ.get("PLATFORM_DB")
        os.environ["PLATFORM_DB"] = ":memory:"
        try:
            conn = db.connect()  # db_path is None -> PLATFORM_DB wins
            try:
                self.assertTrue(_ALL_TABLES.issubset(self._table_names(conn)))
            finally:
                conn.close()
        finally:
            if prev is None:
                os.environ.pop("PLATFORM_DB", None)
            else:
                os.environ["PLATFORM_DB"] = prev


# --------------------------------------------------------------------------- #
# stores                                                                       #
# --------------------------------------------------------------------------- #
class TestStores(unittest.TestCase):
    def test_round_trip(self):
        with temp_db() as conn:
            db.upsert_store(
                conn, id="s1", name="Acme", url="https://acme.test", ingested_at="2026-01-01T00:00:00+00:00"
            )
            got = db.get_store(conn, "s1")
            self.assertEqual(
                got,
                {
                    "id": "s1",
                    "name": "Acme",
                    "url": "https://acme.test",
                    "ingested_at": "2026-01-01T00:00:00+00:00",
                },
            )

    def test_get_missing_returns_none(self):
        with temp_db() as conn:
            self.assertIsNone(db.get_store(conn, "nope"))

    def test_upsert_updates_on_conflict(self):
        with temp_db() as conn:
            db.upsert_store(conn, id="s1", name="Old", url="https://old.test")
            db.upsert_store(conn, id="s1", name="New", url="https://new.test")
            got = db.get_store(conn, "s1")
            self.assertEqual(got["name"], "New")
            self.assertEqual(got["url"], "https://new.test")
            self.assertEqual(len(db.list_stores(conn)), 1)  # still one row

    def test_list_stores(self):
        with temp_db() as conn:
            db.upsert_store(conn, id="a", name="A", url="u", ingested_at="2026-01-01T00:00:00+00:00")
            db.upsert_store(conn, id="b", name="B", url="u", ingested_at="2026-01-02T00:00:00+00:00")
            ids = [s["id"] for s in db.list_stores(conn)]
            self.assertEqual(ids, ["a", "b"])

    def test_ingested_at_defaults_to_now(self):
        with temp_db() as conn:
            db.upsert_store(conn, id="s1", name="A", url="u")
            self.assertIsNotNone(db.get_store(conn, "s1")["ingested_at"])


# --------------------------------------------------------------------------- #
# products                                                                     #
# --------------------------------------------------------------------------- #
class TestProducts(unittest.TestCase):
    def _store(self, conn):
        db.upsert_store(conn, id="s1", name="Acme", url="https://acme.test")

    def test_round_trip_with_real_catalog_product(self):
        with temp_db() as conn:
            self._store(conn)
            db.upsert_product(
                conn,
                id="TEE-OLIVE-001",
                store_id="s1",
                title="Heavyweight Olive Crew Tee",
                price=29.9,
                sizes=["S", "M", "L", "XL"],
                image_path="catalog/images/tee-olive-001.png",
                enriched=_ENRICHED_PRODUCT,
                created_at="2026-01-01T00:00:00+00:00",
            )
            got = db.get_product(conn, "TEE-OLIVE-001")
            # JSON columns decode back to the original Python objects.
            self.assertEqual(got["sizes"], ["S", "M", "L", "XL"])
            self.assertEqual(got["enriched"], _ENRICHED_PRODUCT)
            # enriched must be a dict (rebuildable via CatalogProduct.from_dict).
            self.assertIsInstance(got["enriched"], dict)
            # scalar columns survive.
            self.assertEqual(got["id"], "TEE-OLIVE-001")
            self.assertEqual(got["store_id"], "s1")
            self.assertEqual(got["title"], "Heavyweight Olive Crew Tee")
            self.assertEqual(got["price"], 29.9)
            self.assertEqual(got["image_path"], "catalog/images/tee-olive-001.png")
            self.assertEqual(got["created_at"], "2026-01-01T00:00:00+00:00")
            # the raw *_json columns are not surfaced.
            self.assertNotIn("sizes_json", got)
            self.assertNotIn("enriched_json", got)

    def test_enriched_can_rebuild_catalog_product(self):
        # A downstream module rebuilds the typed object from the decoded dict.
        from stylist import schemas  # local import; no network on import

        with temp_db() as conn:
            self._store(conn)
            db.upsert_product(
                conn,
                id="TEE-OLIVE-001",
                store_id="s1",
                title="t",
                price=29.9,
                sizes=["S"],
                image_path="p.png",
                enriched=_ENRICHED_PRODUCT,
            )
            got = db.get_product(conn, "TEE-OLIVE-001")
            rebuilt = schemas.CatalogProduct.from_dict(got["enriched"])
            self.assertEqual(rebuilt.to_dict(), _ENRICHED_PRODUCT)

    def test_upsert_updates_on_conflict(self):
        with temp_db() as conn:
            self._store(conn)
            db.upsert_product(
                conn, id="p1", store_id="s1", title="Old", price=10.0,
                sizes=["S"], image_path="old.png", enriched={"v": 1},
            )
            db.upsert_product(
                conn, id="p1", store_id="s1", title="New", price=20.0,
                sizes=["M", "L"], image_path="new.png", enriched={"v": 2},
            )
            got = db.get_product(conn, "p1")
            self.assertEqual(got["title"], "New")
            self.assertEqual(got["price"], 20.0)
            self.assertEqual(got["sizes"], ["M", "L"])
            self.assertEqual(got["enriched"], {"v": 2})
            self.assertEqual(len(db.list_products(conn)), 1)

    def test_list_products_filter_by_store(self):
        with temp_db() as conn:
            self._store(conn)
            db.upsert_store(conn, id="s2", name="Other", url="u")
            db.upsert_product(
                conn, id="p1", store_id="s1", title="t", price=1.0,
                sizes=[], image_path=None, enriched=None, created_at="2026-01-01T00:00:00+00:00",
            )
            db.upsert_product(
                conn, id="p2", store_id="s2", title="t", price=1.0,
                sizes=[], image_path=None, enriched=None, created_at="2026-01-02T00:00:00+00:00",
            )
            self.assertEqual([p["id"] for p in db.list_products(conn)], ["p1", "p2"])
            self.assertEqual([p["id"] for p in db.list_products(conn, store_id="s1")], ["p1"])
            self.assertEqual([p["id"] for p in db.list_products(conn, store_id="s2")], ["p2"])

    def test_none_json_stays_none(self):
        with temp_db() as conn:
            self._store(conn)
            db.upsert_product(
                conn, id="p1", store_id="s1", title="t", price=1.0,
                sizes=None, image_path=None, enriched=None,
            )
            got = db.get_product(conn, "p1")
            self.assertIsNone(got["sizes"])
            self.assertIsNone(got["enriched"])
            # the literal string "null" must never be written.
            raw = conn.execute(
                "SELECT enriched_json FROM products WHERE id = ?", ("p1",)
            ).fetchone()[0]
            self.assertIsNone(raw)

    def test_foreign_key_rejects_unknown_store(self):
        with temp_db() as conn:
            with self.assertRaises(sqlite3.IntegrityError):
                db.upsert_product(
                    conn, id="p1", store_id="ghost", title="t", price=1.0,
                    sizes=[], image_path=None, enriched=None,
                )

    def test_get_missing_returns_none(self):
        with temp_db() as conn:
            self.assertIsNone(db.get_product(conn, "nope"))


if __name__ == "__main__":
    unittest.main()
