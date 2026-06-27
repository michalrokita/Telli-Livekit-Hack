"""platform.db — the persistence layer (schema + connection + CRUD).

Pure stdlib ``sqlite3``. No ORM, no Postgres, no third-party deps. The styling
brain (``stylist``) stays stateless; everything stateful lives here in one sqlite
file: just two tables — stores and the pre-enriched products crawled from them.

Design contract (downstream code codes against this):
  * JSON columns accept and return PYTHON objects — the helpers encode on write
    and decode on read. ``None`` stays ``None`` (the literal string ``"null"`` is
    never written).
  * Row reads return a plain ``dict`` (never a ``sqlite3.Row``) with JSON columns
    already decoded, or ``None`` when the row is absent.
  * Every CRUD helper takes the open ``conn`` first, takes the rest as keyword
    args, and commits after a write.
  * All SQL is parameterised (``?`` placeholders) — values are never formatted
    into the SQL string.

Opaque JSON payloads:
  * ``products.enriched_json`` holds a ``stylist.schemas.CatalogProduct`` dict.

A later module rebuilds a typed object via ``CatalogProduct.from_dict(...)`` from the
decoded dict — this layer stores it opaquely.
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

# --------------------------------------------------------------------------- #
# Constants                                                                    #
# --------------------------------------------------------------------------- #
#: Default on-disk database. The ``data/`` dir is gitignored except ``.gitkeep``.
DEFAULT_DB_PATH = Path(__file__).resolve().parent / "data" / "app.db"

#: Schema — 2 tables, each created idempotently. Source of truth for column order.
_SCHEMA = """
CREATE TABLE IF NOT EXISTS stores (
    id          TEXT PRIMARY KEY,
    name        TEXT,
    url         TEXT,
    ingested_at TEXT
);

CREATE TABLE IF NOT EXISTS products (
    id            TEXT PRIMARY KEY,
    store_id      TEXT,
    title         TEXT,
    price         REAL,
    sizes_json    TEXT,
    image_path    TEXT,
    enriched_json TEXT,
    created_at    TEXT,
    FOREIGN KEY(store_id) REFERENCES stores(id)
);
"""


# --------------------------------------------------------------------------- #
# Internal helpers — JSON (TEXT) encode/decode, timestamp, row -> dict.        #
# --------------------------------------------------------------------------- #
def _dumps(obj) -> str | None:
    """Encode a Python object to TEXT; ``None`` stays ``None`` (no ``"null"``)."""
    if obj is None:
        return None
    return json.dumps(obj, ensure_ascii=False)


def _loads(text: str | None):
    """Decode TEXT to a Python object; ``None`` stays ``None``."""
    if text is None:
        return None
    return json.loads(text)


def _now() -> str:
    """Current UTC timestamp as an ISO-8601 string (the default for ``*_at`` columns)."""
    return datetime.now(timezone.utc).isoformat()


def _row_to_dict(row: sqlite3.Row | None, json_columns: tuple = ()) -> dict | None:
    """Convert a ``sqlite3.Row`` to a plain ``dict``, decoding JSON columns.

    ``json_columns`` is a tuple of ``(column, output_key)`` pairs. Each raw
    ``*_json`` column is removed and replaced by ``output_key`` holding the
    decoded Python object. Returns ``None`` when ``row`` is ``None``.
    """
    if row is None:
        return None
    d = dict(row)
    for col, out_key in json_columns:
        d[out_key] = _loads(d.pop(col))
    return d


# --------------------------------------------------------------------------- #
# Connection / schema                                                          #
# --------------------------------------------------------------------------- #
def connect(db_path=None) -> sqlite3.Connection:
    """Open (and initialise) the database, returning a ready connection.

    ``db_path`` accepts a ``str``, an ``os.PathLike``, or the literal
    ``":memory:"``. When ``db_path is None`` the env var ``PLATFORM_DB`` wins if
    set, otherwise ``DEFAULT_DB_PATH``. For a file path the parent directory is
    created if missing. The connection has ``row_factory = sqlite3.Row``,
    ``PRAGMA foreign_keys = ON``, and the full schema applied.
    """
    if db_path is None:
        db_path = os.environ.get("PLATFORM_DB") or DEFAULT_DB_PATH

    if str(db_path) == ":memory:":
        target = ":memory:"
    else:
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        target = str(path)

    conn = sqlite3.connect(target)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    init_schema(conn)
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    """Create both tables with ``CREATE TABLE IF NOT EXISTS`` (idempotent)."""
    conn.executescript(_SCHEMA)
    conn.commit()


# --------------------------------------------------------------------------- #
# stores                                                                       #
# --------------------------------------------------------------------------- #
def upsert_store(conn: sqlite3.Connection, *, id, name, url, ingested_at=None) -> None:
    """Insert or update a store by ``id`` (``ingested_at`` defaults to now)."""
    if ingested_at is None:
        ingested_at = _now()
    conn.execute(
        "INSERT INTO stores (id, name, url, ingested_at) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(id) DO UPDATE SET "
        "name = excluded.name, url = excluded.url, ingested_at = excluded.ingested_at",
        (id, name, url, ingested_at),
    )
    conn.commit()


def get_store(conn: sqlite3.Connection, store_id) -> dict | None:
    """Return the store row as a dict, or ``None``."""
    row = conn.execute("SELECT * FROM stores WHERE id = ?", (store_id,)).fetchone()
    return _row_to_dict(row)


def list_stores(conn: sqlite3.Connection) -> list[dict]:
    """Return all stores ordered by ``ingested_at`` then ``id``."""
    rows = conn.execute("SELECT * FROM stores ORDER BY ingested_at, id").fetchall()
    return [_row_to_dict(r) for r in rows]


# --------------------------------------------------------------------------- #
# products                                                                     #
# --------------------------------------------------------------------------- #
def upsert_product(
    conn: sqlite3.Connection,
    *,
    id,
    store_id,
    title,
    price,
    sizes,
    image_path,
    enriched,
    created_at=None,
) -> None:
    """Insert or update a product by ``id``.

    ``sizes`` (a list) is stored as ``sizes_json``; ``enriched`` (a
    ``CatalogProduct`` dict) is stored as ``enriched_json``.
    """
    if created_at is None:
        created_at = _now()
    conn.execute(
        "INSERT INTO products "
        "(id, store_id, title, price, sizes_json, image_path, enriched_json, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(id) DO UPDATE SET "
        "store_id = excluded.store_id, title = excluded.title, price = excluded.price, "
        "sizes_json = excluded.sizes_json, image_path = excluded.image_path, "
        "enriched_json = excluded.enriched_json, created_at = excluded.created_at",
        (id, store_id, title, price, _dumps(sizes), image_path, _dumps(enriched), created_at),
    )
    conn.commit()


def get_product(conn: sqlite3.Connection, product_id) -> dict | None:
    """Return the product row as a dict (``sizes`` -> list, ``enriched`` -> dict), or ``None``."""
    row = conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
    return _row_to_dict(row, (("sizes_json", "sizes"), ("enriched_json", "enriched")))


def list_products(conn: sqlite3.Connection, store_id=None) -> list[dict]:
    """Return products (optionally filtered by ``store_id``) ordered by ``created_at`` then ``id``."""
    if store_id is None:
        rows = conn.execute(
            "SELECT * FROM products ORDER BY created_at, id"
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM products WHERE store_id = ? ORDER BY created_at, id", (store_id,)
        ).fetchall()
    decode = (("sizes_json", "sizes"), ("enriched_json", "enriched"))
    return [_row_to_dict(r, decode) for r in rows]


__all__ = [
    # connection / schema
    "DEFAULT_DB_PATH",
    "connect",
    "init_schema",
    # stores
    "upsert_store",
    "get_store",
    "list_stores",
    # products
    "upsert_product",
    "get_product",
    "list_products",
]
