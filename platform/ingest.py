"""platform.ingest — pluggable store ingestion (crawl/HTTP -> enriched products).

A store hands us messy products (``title / image_url / price / sizes``). This module
normalises each into a typed ``stylist.schemas.CatalogProduct`` and persists it through
``platform.db``. Enrichment happens HERE, at ingest time, so the live shopper path never
waits on a vision pass — it just reads the cached ``products`` table.

Two source adapters ship today:
  * ``BrowserMcpDump``    — a ``<store>.products.json`` array from a browser-MCP crawl
                            (the offline / teammate-handoff path).
  * ``HttpStoreAdapter``  — fetch a storefront URL and parse product cards out of the
                            HTML with the stdlib ``html.parser`` (the live path; ``fetch``
                            and ``parse`` are split so the parser is testable with no net).

The whole module is stdlib-only. ``httpx`` is imported LAZILY and only inside the live
network branches (``HttpStoreAdapter.fetch`` and the remote-image download), so importing
this module — and running every offline test — needs no third-party dependency and no key.

Design contract for a raw product dict (what an adapter's ``products()`` yields):
    {
      "title":     str,          # required
      "image_url":  str,         # required: an http(s) URL or a local filesystem path
      "price":      float | str, # numeric, or a string the ingester coerces ("$24.00")
      "sizes":      list[str],   # may be empty
      "id":         str,         # OPTIONAL — else derived deterministically (make_product_id)
      "category":   str,         # OPTIONAL — "hat"/"tshirt", else inferred (infer_category)
    }

Source of truth for the persisted shape: ``platform.db`` (products table) and
``stylist.schemas.CatalogProduct``.
"""

from __future__ import annotations

import hashlib
import re
import shutil
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from platform import db
from stylist import catalog as _catalog

# --------------------------------------------------------------------------- #
# Paths                                                                        #
# --------------------------------------------------------------------------- #
#: Default root for resolved/downloaded product images. Gitignored (``platform/data/``).
DATA_IMAGES_ROOT = Path(__file__).resolve().parent / "data" / "images"

#: Title keywords that mark a product as a ``hat`` (case-insensitive substring match).
_HAT_KEYWORDS = ("cap", "hat", "beanie", "bucket", "fedora", "snapback")

#: Void HTML elements — they never have an end tag, so they must not change card depth.
_VOID_TAGS = frozenset(
    {"img", "br", "hr", "input", "meta", "link", "source", "area",
     "base", "col", "embed", "param", "track", "wbr"}
)

_SLUG_RE = re.compile(r"[^a-z0-9]+")
_PRICE_RE = re.compile(r"[^0-9.]")


# --------------------------------------------------------------------------- #
# Pure helpers (deterministic — no random, no clock)                          #
# --------------------------------------------------------------------------- #
def _slug(text: str) -> str:
    """Lowercase ``text`` to a hyphen slug (``"Olive Crew Tee" -> "olive-crew-tee"``)."""
    s = _SLUG_RE.sub("-", str(text).lower()).strip("-")
    return s or "item"


def make_product_id(raw: dict) -> str:
    """Derive a STABLE product id from a raw product dict (used when it has no ``id``).

    ``"<title-slug>-<sha1(title|image_url)[:8]>"`` — pure and deterministic, so the same
    raw product always maps to the same id and re-ingesting upserts in place (idempotent).
    """
    title = str(raw.get("title", ""))
    image_url = str(raw.get("image_url", ""))
    digest = hashlib.sha1(f"{title}|{image_url}".encode("utf-8")).hexdigest()[:8]
    return f"{_slug(title)}-{digest}"


def infer_category(raw: dict) -> str:
    """Infer ``"hat"`` vs ``"tshirt"`` from the title (used when ``raw`` has no category).

    ``"hat"`` if the title contains any of cap/hat/beanie/bucket/fedora/snapback
    (case-insensitive); otherwise ``"tshirt"``.
    """
    title = str(raw.get("title", "")).lower()
    return "hat" if any(kw in title for kw in _HAT_KEYWORDS) else "tshirt"


def _is_url(value: str) -> bool:
    return isinstance(value, str) and value.lower().startswith(("http://", "https://"))


def _coerce_price(value) -> float:
    """Best-effort numeric price from a number or a messy string (``"$24.00" -> 24.0``)."""
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    cleaned = _PRICE_RE.sub("", str(value or ""))
    try:
        return float(cleaned) if cleaned else 0.0
    except ValueError:
        return 0.0


# --------------------------------------------------------------------------- #
# Store adapters                                                               #
# --------------------------------------------------------------------------- #
class StoreAdapter:
    """Abstract source of raw product dicts for a single store.

    Subclasses implement :meth:`products`, returning a list of raw product dicts
    following the module-level contract (``title``, ``image_url``, ``price``, ``sizes``;
    optional ``id`` and ``category``). Adapters are responsible for normalising their own
    ``image_url`` values so they are directly usable by the ingester: either an
    ``http(s)`` URL or an ABSOLUTE local path. The ingester does the rest (id/category
    resolution, image localisation, enrichment, persistence).
    """

    def products(self) -> list[dict]:
        """Return the store's raw product dicts. Must be implemented by a subclass."""
        raise NotImplementedError


class BrowserMcpDump(StoreAdapter):
    """Adapter over a ``<store>.products.json`` file produced by a browser-MCP crawl.

    The file is a JSON array of raw product dicts. Relative, non-URL ``image_url`` values
    are resolved to ABSOLUTE paths against ``image_base`` (default: the directory holding
    the dump file), so a relocatable crawl folder — its ``.products.json`` next to an
    ``images/`` directory — ingests with no extra wiring. Absolute paths and ``http(s)``
    URLs are passed through unchanged.
    """

    def __init__(self, path, *, image_base=None) -> None:
        self.path = Path(path)
        self.image_base = Path(image_base) if image_base is not None else self.path.resolve().parent

    def products(self) -> list[dict]:
        """Read the dump and return its raw product dicts (image paths absolutised)."""
        import json  # stdlib; local to keep the module surface tidy

        data = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise ValueError(
                f"{self.path} must contain a JSON array of products, got {type(data).__name__}"
            )
        out: list[dict] = []
        for item in data:
            raw = dict(item)
            img = raw.get("image_url")
            if isinstance(img, str) and img and not _is_url(img):
                p = Path(img)
                if not p.is_absolute():
                    raw["image_url"] = str((self.image_base / p).resolve())
            out.append(raw)
        return out


class HttpStoreAdapter(StoreAdapter):
    """Adapter that fetches a storefront URL and parses product cards out of its HTML.

    ``fetch`` (the only network call — lazy ``httpx``) and ``parse`` (pure, stdlib
    ``html.parser``) are deliberately split so the parser is unit-testable on a saved HTML
    string with no network. ``url`` is optional: it is required for :meth:`fetch`/
    :meth:`products`, and when present it is the base against which relative image ``src``
    values are resolved to absolute URLs in :meth:`parse`.
    """

    def __init__(self, url: str | None = None, *, timeout: float = 30.0) -> None:
        self.url = url
        self.timeout = timeout

    def fetch(self, url: str | None = None) -> str:
        """GET ``url`` (or ``self.url``) and return the response body text. LIVE network."""
        target = url or self.url
        if not target:
            raise ValueError("HttpStoreAdapter.fetch needs a url (none given and self.url is unset)")
        import httpx  # lazy: the only third-party import, only on the live path

        with httpx.Client(timeout=self.timeout, follow_redirects=True) as client:
            resp = client.get(target)
            resp.raise_for_status()
            return resp.text

    def parse(self, html) -> list[dict]:
        """Parse storefront HTML (a string or a readable) into raw product dicts.

        Heuristic (best-effort, documented): a product CARD opens at any element whose
        ``class`` contains ``product`` and closes at its matching end tag. Inside a card:
          * ``image_url`` <- the ``src`` of the first ``<img>`` (relative srcs are joined
            onto ``self.url`` when set, else left as-is);
          * ``title``     <- text of the first descendant whose class contains ``title``;
          * ``price``     <- numeric parsed from the first ``price``-classed descendant;
          * ``sizes``     <- the card's ``data-sizes`` attribute split on commas, else [].
        Cards yielding neither a title nor an image are dropped as noise.
        """
        if hasattr(html, "read"):
            html = html.read()
        parser = _ProductCardParser()
        parser.feed(html)
        parser.close()

        out: list[dict] = []
        for card in parser.cards:
            if not card["title"] and not card["image_url"]:
                continue
            img = card["image_url"]
            if img and self.url and not _is_url(img):
                img = urljoin(self.url, img)
            out.append(
                {
                    "title": card["title"],
                    "price": card["price"],
                    "image_url": img,
                    "sizes": list(card["sizes"]),
                }
            )
        return out

    def products(self) -> list[dict]:
        """Fetch ``self.url`` and parse it into raw product dicts (the live path)."""
        return self.parse(self.fetch(self.url))


class _ProductCardParser(HTMLParser):
    """Stdlib HTML parser that extracts product cards (see ``HttpStoreAdapter.parse``).

    Cards may nest arbitrary markup (an ``<a>`` wrapping the ``<img>``, etc.): a depth
    counter, incremented per non-void open tag and decremented per close, finds each
    card's matching end tag without assuming a flat structure.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.cards: list[dict] = []
        self._card: dict | None = None
        self._depth = 0
        self._capture: str | None = None  # "title" | "price" | None
        self._buf: list[str] = []

    @staticmethod
    def _classes(attrs: dict) -> str:
        return attrs.get("class") or ""

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        classes = self._classes(a)

        if self._card is None:
            if "product" in classes:
                self._card = {"title": None, "price": None, "image_url": None, "sizes": []}
                self._depth = 1
                data_sizes = a.get("data-sizes")
                if data_sizes:
                    self._card["sizes"] = [s.strip() for s in data_sizes.split(",") if s.strip()]
            return

        # Inside a card: grab the first image regardless of nesting.
        if tag == "img" and self._card["image_url"] is None:
            src = a.get("src")
            if src:
                self._card["image_url"] = src
        if tag in _VOID_TAGS:
            return  # void: no end tag, so it must not affect depth/capture

        self._depth += 1
        if "title" in classes and self._card["title"] is None:
            self._capture, self._buf = "title", []
        elif "price" in classes and self._card["price"] is None:
            self._capture, self._buf = "price", []

    def handle_startendtag(self, tag, attrs):
        # Self-closing form (``<img/>``): treat as a start only — never an end tag.
        self.handle_starttag(tag, attrs)

    def handle_data(self, data):
        if self._card is not None and self._capture is not None:
            self._buf.append(data)

    def handle_endtag(self, tag):
        if self._card is None:
            return
        if self._capture is not None:
            text = "".join(self._buf).strip()
            if text:
                if self._capture == "title":
                    self._card["title"] = text
                elif self._capture == "price":
                    self._card["price"] = _coerce_price(text)
            self._capture, self._buf = None, []
        self._depth -= 1
        if self._depth <= 0:
            self.cards.append(self._card)
            self._card = None
            self._depth = 0


# --------------------------------------------------------------------------- #
# Image localisation                                                           #
# --------------------------------------------------------------------------- #
def _url_suffix(url: str) -> str:
    return Path(urlsplit(url).path).suffix


def _download_image(url: str, dest: Path, *, timeout: float) -> str:
    """Download ``url`` to ``dest`` and return its absolute path. LIVE network (lazy httpx)."""
    import httpx  # lazy: only on the live path

    dest.parent.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        resp = client.get(url)
        resp.raise_for_status()
        dest.write_bytes(resp.content)
    return str(dest.resolve())


def _resolve_image(image_url: str, dest_dir: Path, product_id: str, *, live: bool, timeout: float) -> str:
    """Resolve a raw ``image_url`` to a usable image path under ``dest_dir``.

    * ``http(s)`` URL — downloaded into ``dest_dir`` only when ``live`` is True; offline it
      is returned unchanged (so tests never hit the network — such a product simply fails
      to enrich offline and is skipped by the anti-loop).
    * local path that exists — copied into ``dest_dir`` and the ABSOLUTE copy path returned.
    * anything else — returned unchanged.

    The copy/download is named ``<product-id-slug><ext>`` so re-ingesting overwrites in
    place (idempotent) and two products never collide on a shared source filename.
    """
    if _is_url(image_url):
        if not live:
            return image_url
        ext = _url_suffix(image_url) or ".png"
        return _download_image(image_url, dest_dir / f"{_slug(product_id)}{ext}", timeout=timeout)

    src = Path(image_url)
    if not src.exists():
        return image_url
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{_slug(product_id)}{src.suffix or '.png'}"
    shutil.copyfile(src, dest)
    return str(dest.resolve())


# --------------------------------------------------------------------------- #
# ingest_store — the orchestrator                                             #
# --------------------------------------------------------------------------- #
def _one_line(text: str) -> str:
    """Collapse whitespace/newlines so an exception text fits one reason line."""
    return " ".join(str(text).split())


def _image_preflight(image_url: str, *, live: bool) -> tuple[bool, str | None]:
    """Decide — before any enrichment — whether ``image_url`` can be localised.

    Returns ``(ok, problem)``; ``problem`` is a human-readable phrase when ``ok`` is
    False, suitable to drop straight into a ``"SKIP <id>: <problem>"`` reason line.
    The vision pass reads the image bytes even on the offline/replay path, so a product
    whose image cannot be obtained can never enrich — we say so explicitly instead of
    letting it fail opaquely deeper in.
    """
    if not image_url:
        return False, "no image_url given"
    if _is_url(image_url):
        if not live:
            return False, f"remote image needs live=True (offline): {image_url}"
        return True, None  # downloaded by _resolve_image on the live path
    if not Path(image_url).exists():
        return False, f"image not found at {image_url}"
    return True, None


def ingest_store(conn, store, source, *, store_url=None, image_dir=None, live=False, errors=None) -> dict:
    """Ingest every product from ``source`` into the db under ``store``; return a SUMMARY.

    Arguments:
      * ``conn``      — an open ``platform.db`` connection (FKs on, schema inited).
      * ``store``     — a mapping ``{"id", "name", "url"}`` identifying the store. ``url``
                        falls back to ``store_url`` when absent. The store row is upserted
                        first so product FKs resolve.
      * ``source``    — a :class:`StoreAdapter` (its ``products()`` yields raw dicts).
      * ``store_url`` — optional store URL, used when ``store`` carries none.
      * ``image_dir`` — where images are copied/downloaded; default
                        ``platform/data/images/<store_id>/``.
      * ``live``      — when True, remote (``http(s)``) images are downloaded and the
                        ``stylist`` enrichment may make real calls (``STYLIST_LIVE``);
                        offline (default) everything replays from cassettes / local files.
      * ``errors``    — OPTIONAL back-compat list. When given, each non-enriched product is
                        appended as ``(raw, exception)`` (a parallel detail view of the
                        ``reasons`` below). ``reasons`` is the primary, human-readable
                        surface; ``errors`` is just the raw objects for programmatic use.

    Returns a per-store summary dict::

        {"found": int, "enriched": int, "skipped": int, "reasons": [str, ...]}

    where ``found`` is the count of DISTINCT products (after de-duplication by resolved
    id), ``enriched`` the count successfully enriched + upserted, ``skipped`` is
    ``found - enriched``, and ``reasons`` carries one human-readable line per drop —
    NO silent drops. A ``"SKIP <id>: …"`` line explains every product that did not end up
    in the db; a ``"DEDUPE <id>: …"`` line notes each ignored duplicate occurrence (a
    deduped duplicate is NOT counted in ``found`` and so is NOT a ``skip`` — the line is
    there only for transparency).

    For each DISTINCT raw product: resolve ``id`` (raw or :func:`make_product_id`) and
    ``category`` (raw or :func:`infer_category`), pre-flight + localise its image, enrich
    it via ``stylist.catalog.enrich`` (cassette ``catalog_<id>`` — the seed ids replay
    offline), pin the enriched ``image_url`` to the resolved ABSOLUTE local path, then
    upsert the product row. Idempotent (upsert by id — re-ingest never duplicates).
    Anti-loop: a failing product is retried ONCE then skipped with a reason — never a
    third attempt, never aborting the whole ingest. Robust to missing/broken images,
    missing or oddly-typed price (coerced to ``0.0``), and missing sizes (``[]``).
    """
    if not isinstance(store, dict):
        raise TypeError("store must be a mapping with at least an 'id' key")
    store_id = store["id"]
    db.upsert_store(
        conn,
        id=store_id,
        name=store.get("name"),
        url=store.get("url") or store_url,
    )

    dest_dir = Path(image_dir) if image_dir is not None else (DATA_IMAGES_ROOT / store_id)
    timeout = 30.0

    found = 0
    enriched = 0
    reasons: list[str] = []
    seen: set[str] = set()

    def _flag(reason: str, raw: dict, exc: Exception) -> None:
        reasons.append(reason)
        if errors is not None:
            errors.append((raw, exc))

    for raw in source.products():
        pid = raw.get("id") or make_product_id(raw)

        # De-duplicate by resolved id: a repeat occurrence is NOT a new product. It does
        # not count toward ``found`` (and so is never a ``skip``) but is surfaced for
        # transparency so nothing vanishes silently.
        if pid in seen:
            _flag(
                f"DEDUPE {pid}: duplicate id, ignored repeat occurrence",
                raw,
                ValueError(f"duplicate id {pid!r}"),
            )
            continue
        seen.add(pid)
        found += 1

        category = raw.get("category") or infer_category(raw)
        image_url = str(raw.get("image_url", ""))

        # Pre-flight the image so a broken/missing one becomes a precise, early reason
        # rather than an opaque failure inside the vision pass.
        ok, problem = _image_preflight(image_url, live=live)
        if not ok:
            _flag(f"SKIP {pid}: {problem}", raw, FileNotFoundError(problem))
            continue

        # Anti-loop: at most two attempts to resolve + enrich + upsert, then skip.
        last_exc: Exception | None = None
        for _attempt in range(2):
            try:
                image_path = _resolve_image(
                    image_url, dest_dir, pid, live=live, timeout=timeout
                )
                enrich_input = {
                    "id": pid,
                    "category": category,
                    "title": raw.get("title", ""),
                    "price": _coerce_price(raw.get("price")),
                    "sizes": list(raw.get("sizes") or []),
                    "image_url": image_path,
                }
                cp = _catalog.enrich(enrich_input, cassette=f"catalog_{pid}")
                cp.image_url = image_path  # pin to the resolved ABSOLUTE local image
                db.upsert_product(
                    conn,
                    id=pid,
                    store_id=store_id,
                    title=cp.title,
                    price=cp.price,
                    sizes=list(cp.sizes),
                    image_path=image_path,
                    enriched=cp.to_dict(),
                )
                enriched += 1
                last_exc = None
                break
            except Exception as exc:  # noqa: BLE001 — anti-loop swallows, records, continues
                last_exc = exc
        if last_exc is not None:
            _flag(
                f"SKIP {pid}: {type(last_exc).__name__}: {_one_line(last_exc)}",
                raw,
                last_exc,
            )

    return {
        "found": found,
        "enriched": enriched,
        "skipped": found - enriched,
        "reasons": reasons,
    }


__all__ = [
    "StoreAdapter",
    "BrowserMcpDump",
    "HttpStoreAdapter",
    "make_product_id",
    "infer_category",
    "ingest_store",
    "DATA_IMAGES_ROOT",
]
