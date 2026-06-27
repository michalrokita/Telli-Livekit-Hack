"""platform.catalog — the catalog READ-SIDE over the persisted product DB.

Ingestion (``platform.ingest``) runs the one-time vision enrichment at crawl time and
stores each product's typed ``stylist.schemas.CatalogProduct`` opaquely in the
``products`` table (``enriched_json``). This module is the cheap counterpart: it reads a
store's already-enriched products back out and rebuilds them into typed objects.

The live recommend path reads the catalog from THIS module and NEVER re-enriches — there
is no vision call, no network, no key here; enrichment is a crawl-time concern only.
``load_store_catalog`` rebuilds via ``CatalogProduct.from_dict(row["enriched"])``; the
stored ``image_url`` is already the resolved ABSOLUTE local path pinned at ingest time.

Stdlib + ``stylist`` only.
"""

from __future__ import annotations

from platform import db
from stylist import schemas


def load_store_catalog(conn, store_id) -> list[schemas.CatalogProduct]:
    """Return a store's products as typed ``CatalogProduct`` objects (READ-ONLY, no enrich).

    Reads ``db.list_products(conn, store_id)`` and rebuilds each row's opaque
    ``enriched`` dict via :meth:`CatalogProduct.from_dict`. A real ingested catalog always
    carries an ``enriched`` dict per row, but this is defensive: any row whose ``enriched``
    is ``None`` or not a ``dict`` is skipped (never a crash). Order follows ``list_products``
    (``created_at`` then ``id``). Filtering by an unknown ``store_id`` yields ``[]``.
    """
    out: list[schemas.CatalogProduct] = []
    for row in db.list_products(conn, store_id):
        enriched = row.get("enriched")
        if not isinstance(enriched, dict):
            continue  # defensive: a catalog row should always be enriched
        out.append(schemas.CatalogProduct.from_dict(enriched))
    return out


def load_store_catalog_dicts(conn, store_id) -> list[dict]:
    """Like :func:`load_store_catalog` but return the raw enriched dicts (no typing).

    Convenience for callers that just want the persisted JSON payloads. Same skip rule:
    rows without a dict ``enriched`` are omitted.
    """
    return [
        row["enriched"]
        for row in db.list_products(conn, store_id)
        if isinstance(row.get("enriched"), dict)
    ]


__all__ = ["load_store_catalog", "load_store_catalog_dicts"]
