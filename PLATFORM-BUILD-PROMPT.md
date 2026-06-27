# MASTER PROMPT — Platform layer (SQLite) on top of the `/stylist` brain
> Paste into a build session opened in the repo that holds the `stylist/` brain (your local
> working copy). Autonomous, end-to-end, opus-for-coding, parallel waves. You just watch.
> Precondition: `stylist/` (the brain, 124 offline tests green) is present; `OPENAI_API_KEY`
> is in the environment; our self-hosted browser MCP (`mcp__browser__*`) is available.

```
You are the lead engineer + orchestrator. The `/stylist` BRAIN is done (pure, LiveKit-free,
analyze/recommend/tryon, 124 offline tests). Now build the PLATFORM layer on top of it,
end-to-end and AUTONOMOUSLY — I only watch. Do NOT stop for per-phase approval; report a short
status per wave and keep going.

HARD BOUNDARIES (do not cross):
- Work on a new branch `platform`. Add a NEW `platform/` Python package. Do NOT modify
  `apps/web` or `apps/agent` (the partner's code — we integrate at the very end).
- The brain stays pure. The ONLY change allowed in `stylist/` is one additive, backward-
  compatible hook: `recommend(..., taste=None)`. All 124 existing brain tests MUST stay green.
- Persistence = SQLite via stdlib `sqlite3` (no ORM, no Postgres yet). Stdlib-first, matching
  the brain's style (no pydantic/numpy). FastAPI is lazy-imported only (like stylist/serve.py).

OPERATING RULES:
- Anti-loop: max 2 attempts at any one thing → then flag it and move on. Never a 3rd try.
- Tests required per module; offline-deterministic (SQLite temp file + cassette replay for any
  OpenAI call). No network needed to run the suite.
- Secrets: OPENAI_API_KEY from env only; never hardcode/print/commit. Step 1: verify it's present.
- Commits: NO "Claude"/"Co-Authored-By"/AI attribution, ever.
- Models: vision/enrich = OpenAI gpt-4o/gpt-4o-mini (reuse stylist/_openai.py wrapper + cassettes).
  The MiMo-only rule is RevSignal's, not this project.
- Privacy: user selfies/identities are sensitive. Store the DERIVED StyleProfile JSON; keep raw
  photos out of git; no PII beyond email. Leave a GDPR note for production.

MODEL / PARALLELISM POLICY:
- For ANY real coding/test task → spawn a subagent with model: opus.
- model: sonnet ONLY for trivial mechanical work (sample JSON, fixtures, formatting, one-line docs).
- Run independent modules in PARALLEL (spawn concurrent agents in one message). Each agent owns
  its own files — the waves below are file-disjoint.

═══════════ PLATFORM SPEC (build exactly this) ═══════════

PURPOSE: the platform wraps the brain with state so the demo becomes a real product —
ingest a store's catalog once (pre-enriched), keep per-user identities/taste, capture the
voice agent's feedback, and serve personalized recommendations + try-on. Business model PoC:
a store is onboarded once ("snippet → we ingest it"); shoppers use it free.

SQLite schema (single db `platform/data/app.db`, `CREATE TABLE IF NOT EXISTS`):
- stores(id TEXT PK, name, url, ingested_at)
- products(id TEXT PK, store_id, title, price, sizes_json, image_path, enriched_json, created_at)
      # enriched_json = a CatalogProduct dict (so recommend can rebuild CatalogProduct objects)
- users(id PK, email UNIQUE, created_at)
- sessions(token PK, user_id, created_at)
- identities(user_id PK, style_profile_json, taste_json, updated_at)
      # taste_json = {preferred_colors[], preferred_families[], preferred_styles[],
      #               preferred_archetypes[], disliked[]}
- liked_items(id PK, user_id, source('product'|'upload'), product_id NULL, image_path NULL,
              analyzed_json, created_at)
- feedback(id PK, user_id, product_id, reaction('like'|'dislike'|'meh'), context_json, created_at)

MODULES (all under platform/):
- db.py        — sqlite3 connection, schema init, small CRUD helpers. No ORM.
- ingest.py    — StoreAdapter (abstract). Two adapters:
                   • BrowserMcpDump: reads platform/data/<store>.products.json (the product list
                     the crawl produced) — fields: title, image_url, price, sizes.
                   • HttpStoreAdapter: httpx GET + stdlib html.parser to extract product cards
                     (the swappable "real" runtime path).
                 ingest_store(store, source): for each product → download image →
                 stylist.catalog.enrich(image) AT INGESTION → upsert into products (pre-enriched
                 so the live path never enriches → less shopper wait). Idempotent by product id.
- auth.py      — signup/login(email) -> session token; user_from_token(token). Minimal.
- identity.py  — get_or_create_identity(user_id); set_style_profile(user_id, StyleProfile);
                 add_liked_product(user_id, product_id); add_liked_upload(user_id, image)
                 [analyze the uploaded liked garment via a vision pass → store its attributes];
                 record_feedback(user_id, product_id, reaction); compute_taste(user_id) →
                 aggregates liked_items + feedback into the taste_json prior.
- recommend.py — recommend_for_user(user_id, n=2, combo=False): load identity.style_profile +
                 compute_taste → stylist.recommend(profile, catalog=<products from db>, taste=taste).
- feedback.py  — capture endpoint logic → identity.record_feedback → recompute taste.
- serve.py     — FastAPI (lazy import) for the web (TS) + agent (Python) to call:
                   POST /auth/login            {email} -> {token}
                   POST /stores/ingest         {store_id,name,url|dump} -> {count}
                   POST /me/profile            {token, image} -> StyleProfile (calls brain.analyze)
                   POST /me/liked              {token, product_id | image} -> ok (updates taste)
                   POST /recommend             {token, n, combo} -> Options (personalized)
                   POST /feedback              {token, product_id, reaction} -> ok
                   POST /tryon                 {token, base_image, option_ids} -> TryOnResult (proxy brain)

BRAIN HOOK (the only stylist/ change): in stylist/recommend.py + stylist/rules.py add
`taste=None`. When taste is given, apply a BOUNDED additive re-rank (e.g. ±15 pts cap) that
boosts products matching preferred colours/families/archetypes/styles and demotes disliked —
WITHOUT overriding the core colour/fit correctness. taste=None ⇒ byte-identical to today
(all 124 tests stay green). Add new tests for the taste path.

CROSS-STORE CRAWL (browser MCP, temporary): to ingest the teammate's Vercel fashion store, use
our self-hosted browser MCP (mcp__browser__*) to crawl the store URL and write the product list
to platform/data/<store>.products.json, then ingest via BrowserMcpDump. If the store URL isn't
ready yet, build + test ingestion against stylist/catalog/sample_catalog.json + its images as a
stand-in store. Keep the adapter pluggable so a real product feed/API replaces the crawl later.

═══════════ EXECUTION PLAN ═══════════
Wave A — BARRIER: platform/db.py (schema + CRUD) + a temp-db test fixture. One opus agent.
         Nothing proceeds until schema inits clean and CRUD round-trips.
Wave B — PARALLEL (4 opus agents, file-disjoint):
         • platform/ingest.py (+ both adapters; test against the stand-in store)
         • platform/auth.py
         • platform/identity.py (incl. uploaded-liked-garment analysis + compute_taste)
         • stylist/recommend.py + stylist/rules.py taste hook (keep 124 green + new taste tests)
Wave C — platform/recommend.py + platform/feedback.py + platform/serve.py + an end-to-end test:
         ingest stand-in store → login → set profile from a fixture selfie → upload a liked
         garment → personalized recommend → tryon → record feedback → taste updates → recommend
         reflects it. Then write PLATFORM-SEAM.md (how to swap apps/web's /api/mock/* routes and
         apps/agent's mock_services.py for these endpoints — for the final integration).

After each wave: run its tests, integrate, give me a one-screen status (pass/fail per module +
flags), then proceed automatically.

FINAL OUTPUT: (1) file tree, (2) test summary (brain 124 + new platform tests), (3) demo-ready
vs flagged, (4) PLATFORM-SEAM.md path.

Begin: confirm OPENAI_API_KEY present, create branch `platform`, then execute Wave A.
```

*ArtificialArtz · platform wave (SQLite) · builds on `stylist/` + pairs with `stylist-engine-algorithm.md`. After it passes, push `platform/` additively to the partner branch — do not touch `apps/`.*
