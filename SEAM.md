# SEAM.md — wiring the LiveKit voice agent to the `stylist` brain

> **Audience:** the partner building `/agent` (the LiveKit voice layer).
> **What this is:** the brain (`/stylist`) is a pure, **LiveKit-free** Python package. It exposes
> exactly **3 callables** + a data-contract module. Your agent `import stylist` and calls them as
> plain functions; the brain never imports LiveKit and never speaks — it returns data, your agent
> talks. This file shows the LiveKit code **you** add on your side. None of the code in §2–§3 lives
> in `/stylist`; it's reference for `/agent`.

## Table of contents
1. [The data contract — schemas + the 3 signatures](#1-the-data-contract)
2. [The 3 LiveKit `@function_tool` wrappers](#2-the-3-livekit-function_tool-wrappers)
3. [Video frame-grab (PARTNER side)](#3-video-frame-grab-partner-side)
4. [Latency contract (§9.3)](#4-latency-contract)
5. [The async-critic delivery seam](#5-the-async-critic-delivery-seam)
6. [Running it](#6-running-it)

---

## 1. The data contract

Everything you receive back is a plain stdlib `@dataclass` from **`stylist/schemas.py`** (no
pydantic, no numpy, no network). Each model has `.from_dict(d)` (strict validation) and
`.to_dict()` (round-trippable). One valid JSON instance of every model lives in
**`stylist/examples/*.json`** — wire your UI against those without running a model:

| Example file | Model |
|---|---|
| `stylist/examples/style_profile.json` | `StyleProfile` (output of `analyze`) |
| `stylist/examples/options.json` | `Options` (output of `recommend`) |
| `stylist/examples/tryon_result.json` | `TryOnResult` (output of `tryon`) |
| `stylist/examples/catalog_product.json` | `CatalogProduct` (catalog item) |
| `stylist/examples/match_profile.json` | `MatchProfile` (internal query object) |

### The 3 callables (real, verified signatures)

```python
# 1) PHOTO -> profile
analyze(image, *, model="gpt-5.5", cassette=None) -> StyleProfile
#    image = filesystem path OR raw image bytes. You call analyze(frame_bytes).

# 2) profile -> ranked options (+ optional outfit combos)
recommend(profile, n=2, combo=False, *, catalog=None, cassette=None) -> Options
#    recommend(profile)              -> 2 hats + 2 tees, each with a rationale
#    recommend(profile, combo=True)  -> also returns 1-2 full hat+tee OUTFITS

# 3) base photo + chosen ids -> try-on image (returns IMMEDIATELY, status="pending")
tryon(base_photo, option_ids, *, catalog=None, combo=False, on_critic=None,
      out_dir=None, cassette=None, critic_cassette=None) -> TryOnResult
#    Returns at once with the rendered image already on disk. A background critic
#    hot-swaps the image file in place if needed and fires on_critic(updated_result).
```

### What each returns (key fields you'll read)

**`StyleProfile`** (`analyze`) — what to *say* and what's *feasible*:
- `coloring.skin_undertone` (`warm|cool|neutral|olive`), `coloring.season`, `coloring.contrast_level`
- `face.shape`, `face.neck_length` · `build.type` (`slim|athletic|average|broad|fuller`)
- `current_style.detected_vibe` (e.g. `["streetwear","casual"]`)
- `image_quality.usable` (+ `image_quality.issues`) — **gate**: if `usable` is false, ask the user
  to fix the shot before recommending.
- `tryon_feasibility.hat` / `tryon_feasibility.tshirt` (bool) — **gate**: don't offer a category the
  photo can't support (e.g. torso not visible ⇒ no t-shirt try-on).

**`Options`** (`recommend`):
- `options.hats` / `options.tshirts` — lists of `RecommendOption`: `product_id`, `title`,
  `color_hex`, `price`, `sizes`, `score` (0–100), `breakdown{colour,shape,vibe,versatility}`,
  `rationale` (one human sentence — speak this).
- `options.combos` — list of `OutfitCombo`: `hat_id`, `tshirt_id`, `harmony_score`,
  `individual_quality`, `style_coherence`, `rationale`.

**`TryOnResult`** (`tryon`):
- `image_url` — path to the rendered PNG (push to UI; see §4/§5).
- `status` — `"pending"` on the synchronous return, then the critic settles it to
  `"pass"` / `"low_confidence"` (or `"error"`).
- `rendered_option_ids`, `retry_count`, `critic_report` (`None` until the critic runs).
- `result._critic_thread` — the daemon thread you can `.join()` if you'd rather wait than use the
  `on_critic` callback.

> **Hand-off tip:** give your front-end engineer `stylist/schemas.py` + `stylist/examples/*.json`
> first — that's the whole contract; both halves can then build in parallel.

---

## 2. The 3 LiveKit `@function_tool` wrappers

Each wrapper is **thin**: it calls the brain and returns a **short string** for the LLM to speak.
The styling logic lives in `/stylist`, not in your prompt. **Verified against the current LiveKit
Agents API** (imports + shapes below are confirmed; the video frame-grab in §3 is the only
`# UNVERIFIED` piece).

```python
# /agent/stylist_agent.py  — THIS FILE IS YOURS (partner side). It imports the brain.
from livekit.agents.llm import function_tool
from livekit.agents import Agent, AgentSession, RunContext, inference, room_io

import stylist  # the LiveKit-free brain — analyze / recommend / tryon


def _summarize_profile(p) -> str:
    """One short spoken line from a StyleProfile (no numbers, no jargon)."""
    if not p.image_quality.usable:
        return ("I can't read your photo well yet — could you face the camera in better light?")
    c = p.coloring
    return (f"You read as {c.skin_undertone}-toned with {p.build.type} build and a "
            f"{', '.join(p.current_style.detected_vibe) or 'clean'} vibe — let's work with that.")


def _summarize_options(opts) -> str:
    """One short spoken line naming the top hat + tee (and a combo if present)."""
    hat = opts.hats[0].title if opts.hats else None
    tee = opts.tshirts[0].title if opts.tshirts else None
    parts = []
    if tee:
        parts.append(f"a {tee}")
    if hat:
        parts.append(f"a {hat}")
    line = " and ".join(parts) if parts else "a couple of options"
    if opts.combos:
        line += " — and they pair into one outfit"
    return f"I'd go with {line}. Want to see it on you?"


class StylistAgent(Agent):
    def __init__(self):
        super().__init__(
            instructions=(
                "You are a friendly personal stylist on a video call. Keep turns short. "
                "Call analyze_user_photo once the user is clearly on camera, then "
                "recommend_items, then try_on when they pick something. Speak the strings the "
                "tools return; never invent product names, colours, or prices yourself."
            ),
            # @function_tool methods on this class auto-register as tools; you may also pass
            # standalone function_tool callables here via tools=[...].
        )
        self.profile = None        # last StyleProfile
        self.last_frame = None      # last frame bytes (base photo for try-on)
        self.options = None         # last Options
        # self.catalog / self.ui are wired in your entrypoint (see §3 / §4).

    # --- TOOL 1: photo -> spoken profile ----------------------------------------
    @function_tool
    async def analyze_user_photo(self, context: RunContext) -> str:
        """Look at the user on camera and read their colouring, build and current style.
        Call this once when the user is clearly framed."""
        frame_bytes = await self._grab_frame_png()      # PARTNER side — see §3
        self.last_frame = frame_bytes                    # reuse as the try-on base photo
        self.profile = stylist.analyze(frame_bytes)      # -> StyleProfile (a few seconds)
        return _summarize_profile(self.profile)

    # --- TOOL 2: profile -> spoken options --------------------------------------
    @function_tool
    async def recommend_items(self, context: RunContext,
                              category: str, combo: bool = False) -> str:
        """Recommend a hat and/or t-shirt for the user. Set combo=True to also pair them
        into a full outfit. `category` is 'hat', 'tshirt', or 'both'."""
        if self.profile is None:
            return "Let me take a look at you first — say 'analyze me'."
        # Sub-second: deterministic scoring over the pre-enriched catalog (§4).
        self.options = stylist.recommend(self.profile, n=2, combo=combo,
                                         catalog=self.catalog)
        return _summarize_options(self.options)

    # --- TOOL 3: ids -> try-on render (narrate while it renders) -----------------
    @function_tool
    async def try_on(self, context: RunContext, option_ids: list[str]) -> str:
        """Render the chosen items on the user's photo and show it. Pass the product_id(s)
        the user picked (one hat and/or one t-shirt)."""
        result = stylist.tryon(
            self.last_frame, option_ids,
            catalog=self.catalog,
            combo=len(option_ids) > 1,
            on_critic=self._on_critic,   # async hot-swap callback — see §5
        )
        self.ui.show(result.image_url)   # push the image OUT-OF-BAND to the UI (§4)
        # tryon returns instantly with status="pending"; speak a filler so there's no silence:
        return "Putting that on you now — here's how it looks."

    # --- async-critic callback (fires when the critic settles) ------------------
    def _on_critic(self, updated):
        # The file at updated.image_url was overwritten in place if the critic re-rendered.
        # Just refresh the UI; optionally lower confidence in the voice if it didn't pass.
        if updated.status in ("pass", "low_confidence"):
            self.ui.refresh(updated.image_url)
```

**Wrapper signatures (the three you add):**
- `async def analyze_user_photo(self, context: RunContext) -> str`
- `async def recommend_items(self, context: RunContext, category: str, combo: bool = False) -> str`
- `async def try_on(self, context: RunContext, option_ids: list[str]) -> str`

### The voice loop (LiveKit Inference) — verified shapes

```python
# /agent/main.py
from livekit.agents import AgentSession, inference, room_io
from stylist_agent import StylistAgent

async def entrypoint(ctx):  # ctx: JobContext from your worker
    session = AgentSession(
        stt=inference.STT("assemblyai/universal-streaming:en"),  # pick any LiveKit Inference STT
        llm=inference.LLM("openai/gpt-4.1-mini"),                 # verbatim — small/fast tool-caller
        tts=inference.TTS("cartesia/sonic-2:<voice-id>"),        # pick any LiveKit Inference TTS
    )
    agent = StylistAgent()
    agent.catalog = load_catalog()   # your enriched catalog handle (passed into the brain)
    agent.ui = your_ui_publisher     # your data-channel/RPC image push (see §4)
    await session.start(
        agent=agent,
        room=ctx.room,
        room_options=room_io.RoomOptions(
            # video must be enabled here so §3 can sample frames — see the note below.
        ),
    )
```

---

## 3. Video frame-grab (PARTNER side)

The brain takes **PNG/JPEG bytes or a path** — it does not know LiveKit. Capturing a frame from the
participant's video track is entirely on your side. The exact frame API is **not pinned here**:

```python
# >>> UNVERIFIED — confirm against https://docs.livekit.io/agents/quickstarts/vision/ <<<
# Sketch only; do NOT trust these method names without checking the live docs.
async def _grab_frame_png(self) -> bytes:
    # 1) Enable video on the session (room_options=room_io.RoomOptions(video_enabled=True))
    #    so a remote video track is subscribed.
    # 2) Read the latest rtc.VideoFrame from the participant's camera track
    #    (LiveKit gives you a video stream/iterator over rtc.VideoFrame).
    # 3) Convert that rtc.VideoFrame to PNG/JPEG bytes (e.g. via its RGBA/argb buffer + PIL),
    #    and return the bytes. Pass those bytes straight into stylist.analyze / as the
    #    try-on base photo.
    raise NotImplementedError("wire to LiveKit video per the vision quickstart")
```

Sampling cadence: grab a frame roughly **every 0.5–1.5 s** while a face is on camera (don't sample
per-frame — it's wasteful and adds latency). Pre-warm `analyze` (§4) the moment a clear face
appears so the profile is ready before the user even asks.

---

## 4. Latency contract

> The hackathon's #1 rule is "latency is critical." Keep every tool turn snappy:

- **Tiny synchronous returns.** Each tool returns **IDs + one short sentence**, never image data.
  **Push images to the UI out-of-band** (`self.ui.show(image_url)` over your data channel / RPC).
  **Never** base64 an image into the conversation — it bloats context and kills latency.
- **`tryon` is the only slow call** (a few seconds of image edit). It returns **instantly** with the
  rendered image, but you must still **pair it with a verbal filler turn** ("putting that on you
  now…"). **Never a silent gap.** The async critic (§5) overlaps your narration.
- **`recommend` is sub-second** because the catalog is **pre-enriched offline** — keep it that way;
  don't enrich on the live path.
- **Pre-warm `analyze`** the instant a clear face is framed (§3), so the `StyleProfile` is ready
  before the user asks for advice.
- **Don't bloat the agent's system prompt.** Styling logic lives in `/stylist`; your prompt just
  tells the LLM *when* to call which tool and to speak the returned string. A fat prompt = slow
  turns.

---

## 5. The async-critic delivery seam

`tryon` is **fast on the wire and self-correcting in the background** — that's the deferred contract,
now concrete:

1. `tryon(...)` renders the image, writes it to `image_url`, and **returns immediately** with
   `status="pending"`, `critic_report=None`, `retry_count=0`. Your `try_on` tool shows that image
   and speaks a filler line — the user sees a result with zero perceived wait.
2. A background thread then runs the critic. If the render fails verification it does **one** silent
   re-render and **overwrites the file at `image_url` in place** (the URL/path stays valid — your UI
   just needs to **refresh** the same src).
3. When it settles, `status` becomes `"pass"` or `"low_confidence"` (or `"error"`), `critic_report`
   is filled, and **your `on_critic=callback` fires with the updated `TryOnResult`.** Use it to
   refresh the image and, if you like, soften the voice on `low_confidence`.
4. If you'd rather block than use the callback, `result._critic_thread.join()` waits for the critic.

```python
def _on_critic(self, updated):      # passed as on_critic= into stylist.tryon
    self.ui.refresh(updated.image_url)          # same path, new pixels — just reload
    if updated.status == "low_confidence":
        ...  # optional: "that's my best take — want me to try a different one?"
```

> The critic only runs when it *can* (a critic cassette offline, or `STYLIST_LIVE=1` with a key);
> otherwise the result simply stays `pending` and your filler line stands. It is never on the
> critical path.

---

## 6. Running it

- **Keys:** the brain reads `OPENAI_API_KEY` from the environment (only inside live calls; never
  printed or logged). Your LiveKit side reads `LIVEKIT_URL` / `LIVEKIT_API_KEY` / `LIVEKIT_API_SECRET`.
- **Offline / CI (default):** every brain call **replays from a cassette** — no network, no key
  needed. Run the brain's tests with:
  ```bash
  python3 -m unittest discover -s stylist/tests
  ```
- **Live calls:** set `STYLIST_LIVE=1` (plus `OPENAI_API_KEY`) to hit the real models;
  add `STYLIST_RECORD=1` to persist new cassettes.
- **Optional HTTP wrapper:** if your agent runs in a different process/runtime, `stylist/serve.py`
  exposes the 3 callables as `POST /analyze`, `/recommend`, `/tryon` (FastAPI is **lazy-imported** —
  `pip install fastapi uvicorn`, then `uvicorn` the app from `stylist.serve.create_app()`). Importing
  the brain never requires fastapi.
- **Models the brain uses** (your LiveKit voice loop is separate, via LiveKit Inference):
  - vision (`analyze`): **`gpt-5.5`**
  - fast rationale + try-on critic (`recommend` / `tryon`): **`gpt-5.4-mini`**
  - image edit (`tryon`): **`gpt-image-2`**

---

*Hand the partner `stylist/schemas.py` + `stylist/examples/*.json` (the contract) and this file;
both halves build in parallel. The brain has zero LiveKit imports — this doc is the only place
LiveKit code appears, and it's all on your `/agent` side.*
