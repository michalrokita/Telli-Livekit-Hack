# CORRECTION PROMPT — cut accounts/identity; keep crawl + DB
> Paste into the RUNNING platform build session. It amends the earlier platform spec mid-flight
> (agents may be partway — handles "remove if built, skip if not started").

```
SCOPE CHANGE — adjust now. We are CUTTING user accounts and identity entirely. Keep only
the crawl + the product database, and make those excellent.

DROP (delete if already built, skip if not started):
- platform/auth.py            (login / users / sessions)
- platform/identity.py        (taste profiles, liked uploads, compute_taste)
- platform/feedback.py        (feedback persistence)
- SQLite tables: users, sessions, identities, liked_items, feedback
- BRAIN HOOK: REVERT any `taste=` change in stylist/recommend.py and stylist/rules.py.
  The brain must stay EXACTLY as shipped — no stylist/ changes, all 124 tests green, no new
  taste tests, recommend() has NO taste param.
Also delete any tests you wrote for the dropped modules.

KEEP and PERFECT — this is the WHOLE platform now:

1) platform/db.py — SQLite (stdlib sqlite3), ONLY two tables:
     stores(id TEXT PK, name, url, ingested_at)
     products(id TEXT PK, store_id, title, price, sizes_json, image_path, enriched_json, created_at)
       # enriched_json = a CatalogProduct dict so recommend can rebuild CatalogProduct objects

2) platform/ingest.py — the crawl + ingestion pipeline (the part to make excellent):
     - StoreAdapter (abstract), two adapters:
         • BrowserMcpDump  — reads platform/data/<store>.products.json produced by crawling the
           store with our browser MCP (mcp__browser__*). Fields: title, image_url, price, sizes.
         • HttpStoreAdapter — httpx GET + stdlib html.parser (the swappable runtime path).
     - ingest_store(store, source): per product → download image → stylist.catalog.enrich(image)
       AT INGESTION → upsert into products. Idempotent by id (re-ingest updates, never dupes).
     - Robust: dedupe, skip broken/missing images, tolerate missing price/sizes, and return a
       per-store summary {found, enriched, skipped, reasons[]}. NO silent drops — log what dropped.

3) platform/catalog.py — load_store_catalog(store_id) -> list[CatalogProduct] rebuilt from
     products.enriched_json. The live recommend reads from the DB and NEVER re-enriches.

4) platform/serve.py — FastAPI (lazy import), fully STATELESS (no auth, no user state):
     POST /stores/ingest  {store_id,name,url|dump} -> {found,enriched,skipped}
     POST /analyze        {image} -> StyleProfile                      (proxy stylist.analyze)
     POST /recommend      {profile, store_id, n, combo} -> Options
                            (stylist.recommend(profile, catalog=load_store_catalog(store_id)))
     POST /tryon          {base_image, option_ids, store_id} -> TryOnResult (proxy stylist.tryon)

Everything else from the earlier platform spec is CANCELLED. Stay on branch `platform`.
Tests: offline-deterministic (temp SQLite + cassette replay); brain's 124 stay green.

New end-to-end test: ingest the stand-in store (use stylist/catalog/sample_catalog.json + its
images if the Vercel store URL isn't ready) → load_store_catalog → analyze a fixture selfie →
recommend over the store catalog → tryon. Then rewrite PLATFORM-SEAM.md to this reduced surface.

First report what you REMOVED vs KEPT and the brain-revert status, then continue to green.
```

*ArtificialArtz · platform scope cut → crawl + DB only · brain stays untouched (124 green).*
