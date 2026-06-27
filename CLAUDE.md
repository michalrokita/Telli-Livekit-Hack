# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A **LiveKit voice-shopping demo** ("Style Concierge" / "Loma") for the telli × LiveKit hackathon: the user talks to a personal-stylist voice agent, shows themselves on camera, and the agent analyzes their look, recommends hats/t-shirts, and renders try-on images — speaking the rationale while the storefront UI updates. **Latency is the #1 design constraint** (see `SEAM.md` §4): tool turns return tiny strings/IDs and push images out-of-band; nothing slow sits on the conversational path.

## Three components + one seam

This is a pnpm + uv monorepo with **three independently-testable parts** glued by a documented data contract. Understanding the split is the key to navigating the repo:

| Path | What | Runtime | Tests |
|---|---|---|---|
| `apps/web` (`@telli/style-web`) | Next.js storefront UI + LiveKit browser client + `/api/token` route | Node / Next 15 (turbopack) | `vitest` (node env) |
| `apps/agent` (`style-concierge-agent`) | Python LiveKit **realtime voice worker**; drives the browser UI over LiveKit RPC | Python ≥3.10, `uv`, `livekit-agents[openai]` | `pytest` (asyncio auto) |
| `stylist/` (root package) | The **LiveKit-free inference "brain"**: `analyze` / `recommend` / `tryon` | Python stdlib + lazy `httpx`/`Pillow` | stdlib **`unittest`** (not pytest) |

**The seam** (`SEAM.md`, source-of-truth `stylist-engine-algorithm.md`): `stylist/` is a pure package exposing exactly 3 callables + a dataclass contract (`stylist/schemas.py`, with one valid JSON instance per model in `stylist/examples/*.json`). It never imports LiveKit and never speaks — it returns data, the agent talks.

```python
analyze(image) -> StyleProfile                 # photo bytes/path -> validated profile (vision)
recommend(profile, n=2, combo=False) -> Options # deterministic scoring + LLM rationale prose
tryon(base_photo, option_ids) -> TryOnResult    # returns IMMEDIATELY status="pending"; async critic
```

### Important: there are two parallel "brains"
- `apps/agent/src/style_concierge/mock_services.py` — **deterministic mocks** wired into the *live* LiveKit worker today (`agent.py` imports these, not `stylist/`). Stable payloads, no network, no credentials.
- `stylist/` — the **real** cassette-backed inference engine. The web app reaches it via `apps/web/lib/stylist-service.ts`, which shells out to `python3 -c "import stylist..."` (see `STYLIST_*` env vars below). The agent integration described in `SEAM.md` §2 is the intended wiring, not yet the code path in `agent.py`.

When changing shopping behavior, check **which** brain you're editing.

## Commands

```sh
pnpm install                  # JS deps (root)
cd apps/agent && uv sync      # Python agent deps

pnpm dev:web                  # Next.js storefront (turbopack)
cd apps/agent && uv run src/agent.py dev   # LiveKit voice worker (separate terminal)
bash scripts/dev.sh           # prints both run commands with resolved paths; --check verifies env files

pnpm build                    # web production build (next build)
pnpm lint                     # web typecheck only — "lint" === `tsc --noEmit` (no ESLint, no Python linter)
```

### Tests — three runners, know which one
```sh
pnpm test                     # = test:web + test:agent  (does NOT run the stylist/ brain tests)
pnpm test:web                 # vitest run, in apps/web
pnpm test:agent               # cd apps/agent && uv run pytest

# stylist/ brain — stdlib unittest, run from repo root, NO pytest:
python3 -m unittest discover -s stylist/tests
```

Single test:
```sh
pnpm --filter @telli/style-web test -- test/shopper-flow.test.ts      # one vitest file (script already runs `vitest run`)
cd apps/agent && uv run pytest tests/test_mock_services.py::<name>     # one pytest
python3 -m unittest stylist.tests.test_recommend                      # one unittest module
```

## Offline-first model calls (the cassette system)

Both Python halves run **fully offline by default** — no API key needed for tests or local dev:
- `stylist/` replays recorded HTTP responses from `stylist/tests/fixtures/cassettes/` (`*.json` for chat/vision, `*.png` for image edits) via `stylist/_openai.py`.
- Set `STYLIST_LIVE=1` (+ `OPENAI_API_KEY`) to hit real models; add `STYLIST_RECORD=1` to persist new cassettes. The key is read only inside the live branch and never logged.
- `stylist/demo.py` (`run_demo()`) is the **rigged on-stage fallback**: fixed photo + curated catalog + fixed cassettes that always produce one critic-passed try-on.
- Brain model names referenced in code/spec: vision `gpt-5.5`, rationale/critic `gpt-5.4-mini`, image edit `gpt-image-2`. The agent's realtime voice loop is separate: `gpt-realtime-2` / voice `marin`.

## How the pieces talk at runtime

- **Browser ↔ token route:** `apps/web/app/api/token/route.ts` signs a short-lived LiveKit room token server-side (`livekit-server-sdk`), passing `room_config` so LiveKit dispatches the configured agent (`LIVEKIT_AGENT_NAME` / default `style-concierge`). Secrets stay server-side; only `NEXT_PUBLIC_*` reach the browser.
- **Graceful degradation:** if LiveKit env vars are absent, the web app shows a "Demo fallback" instead of a live room (`apps/web/lib/livekit-session.ts`, `getLiveKitReadiness`). Much of the storefront is scripted via `apps/web/lib/demo-script.ts` so it demos without any backend.
- **Agent → UI is RPC, not shared state:** the Python worker mutates the storefront by calling browser-registered RPC methods through `room.local_participant.perform_rpc` (`_browser_rpc` in `agent.py`): `prepareCustomerCamera`, `captureCustomerImage`, `showProductRecommendations`, `generateTryOns`, `addToCart`, `fillCheckoutDelivery`. The browser participant is found by attribute `demo == "loma-mira"`. The agent's `@function_tool` methods stay thin: call a service, fire RPC, return a short string for the LLM to speak. Cart/product/camera state lives in the browser, not the Python process.
- **`tryon` async-critic seam (`SEAM.md` §5):** `tryon()` writes the rendered PNG and returns at once with `status="pending"`; a background thread runs a verification critic that may do ONE silent re-render, overwrites the file *in place* (same path), settles status to `pass`/`low_confidence`, and fires an `on_critic` callback. The UI just refreshes the same src. Never on the critical path.

## Web lib layout (the front-end logic, separate from React)

Business logic lives in `apps/web/lib/*` (unit-tested) and stays out of components:
- `shopper-flow.ts` — core types + the demo flow primitives (`analyzeCustomerImage`, `createTryOnJobs`, cart math).
- `demo-script.ts` — the scripted "Loma" storefront content (products, categories, voice states) for backend-free demoing.
- `mira-live-flow.ts` — normalizes the agent's RPC payloads (loose product selectors → ids/names) into UI actions.
- `design-adapter.ts` — bridges the demo flow to the design in `design/` (`Voice Commerce.dc.html`).
- `stylist-service.ts` — Node→Python bridge that invokes the `stylist/` brain (`STYLIST_PYTHON`, `STYLIST_REPO_ROOT` env overrides).
- `livekit-session.ts` — client wrapper around the `/api/token` endpoint.

## Conventions / gotchas

- **`stylist/` is hard stdlib-only at import time.** `httpx`, `Pillow`, and `fastapi` (`stylist/serve.py`) are all lazy-imported inside the functions that need them, so `import stylist` succeeds with no third-party deps. Keep it that way — it's load-bearing for the offline contract.
- **`recommend` correctness is deterministic, not LLM.** Hard-filter + weighted scoring + colour harmony live in `stylist/rules.py` (rule tables encoded as data). The LLM (P2) only writes one rationale sentence per item and is merged back **only by matching pre-scored `product_id`s** — it cannot inject products or change prices/colours. `recommend` never hard-fails on a bad LLM response; templated rationales stand.
- **`StyleProfile` has two gates** the agent must honor: `image_quality.usable` (ask for a better shot if false) and `tryon_feasibility.{hat,tshirt}` (don't offer a category the photo can't support).
- Env files are app-local: copy root `.env.example` to `apps/web/.env.local` **and** `apps/agent/.env.local`. The agent loads repo-root then app-local `.env.local`/`.env`.
- Agent flow + turn-handling (interruption/endpointing tuning) is configured at the top of `apps/agent/src/agent.py` via `MIRA_*` env vars; the conversation script is the `AGENT_INSTRUCTIONS` prompt.
- Vendored Claude skills under `.agents/skills/` (`livekit-agents`, `livekit-simulations`) are LiveKit's own guidance — useful when extending the agent or writing simulation scenarios.
