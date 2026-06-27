# `stylist.simulations` — scripted voice rehearsals (offline)

The brain (`stylist`) is **LiveKit-free**: it returns data, it never speaks. These simulations
are the missing half, written as plain Python — each one is a scripted **flow** that mirrors what
the partner's LiveKit voice agent (see `SEAM.md` §2) does turn by turn:

> grab a frame → `analyze` → decide if the shot is usable/feasible → `recommend` → `tryon`,
> turning every brain result into the short line the agent would *say*.

They run **fully offline** (cassette replay — no network, no `OPENAI_API_KEY`) and each returns a
`ScenarioResult` carrying the spoken `turns` (`(speaker, line)` pairs) **and** the underlying brain
objects (`profile`, `options`, `tryon`).

```python
from stylist.simulations import run_all
results = run_all()                      # {"happy", "bad_photo", "combo"}
print(results["happy"].transcript)       # just the agent's spoken lines
```

## The three demo moments

| Scenario | Flow | Invariant (asserted in `tests/test_simulations.py`) |
|---|---|---|
| `scenario_happy()` | good photo → `analyze` (usable) → `recommend` → `tryon` → critic **pass** | the spoken options line **names a real catalog item**; the render exists and settles to `pass`. |
| `scenario_bad_photo()` | unusable shot → `analyze` flags it → **route to a spoken fix request** | `image_quality.usable` is False / both feasibility flags False; a fix request is spoken (e.g. *"turn to face me / take your cap off"*, §3.2); **`tryon` is never called** (`tried_on == False`). |
| `scenario_combo()` | `recommend(combo=True)` → hat+tee outfit → **one** combined `tryon` render | 1–2 combos returned; a single render is produced + passes. |

## Why this shape

* **§3.2 feasibility routing.** A side-profile / occluded shot has `tryon_feasibility.tshirt`/`hat`
  = False. The agent must *route around it* ("turn to face me") rather than render a tee on a
  profile. `scenario_bad_photo` proves the brain surfaces that and the flow gates on it.
* **Latency contract (`SEAM.md` §4).** `tryon` returns instantly with the rendered image; the
  critic runs in the background. The rehearsals narrate the filler line and `join()` the critic
  thread only so the returned `ScenarioResult` is finished for inspection.
* **Determinism.** `analyze`/`tryon` replay from cassettes; `recommend` uses its deterministic
  **templated** rationale (no cassette needed). Same inputs → same transcript, every run.

Run the rehearsal directly to print all three transcripts:

```bash
python3 -m stylist.simulations.scenarios
```
