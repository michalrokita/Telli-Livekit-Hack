# AI Stylist — End-to-End Engine (v0.2, longshot draft to iterate on)
### telli × LiveKit Voice AI Hack · the inference/brain half (Alper) — partner owns capture + orchestration

> One line: **photo of a person in → structured "Style Profile" → rule-constrained hat + t-shirt options with stylist rationale → garments dressed onto the SAME photo, identity-preserved, verified by a critic.**
> This doc is the **brain**. It is three clean tools the partner's orchestrator (and a LiveKit voice agent) can call. v0.1 — built to be torn apart and improved.

---

## 0. Division of labor (the thing that was unclear)

The split is clean if we draw the line at a **data contract**, not at vague "you do AI, I do the rest."

| Owner | Owns | Deliverable |
|---|---|---|
| **Partner (front + orchestration)** | photo capture/upload **or LiveKit video frame-grab**, the **conversational/voice stylist agent** (the thing that talks to the user), UI to show results, session state. "The agent that uses your agent" = the orchestrator that **calls Alper's 3 tools as functions.** | A LiveKit voice/video agent + UI |
| **Alper (inference / brain — this doc)** | the **3 tools** below + their prompts, JSON schemas, the rule engine, the try-on critic loop. The styling intelligence. | `analyze`, `recommend`, `tryon` — stateless, JSON in/out, independently testable |

**The contract = the schemas in this doc.** Hand the partner the schemas; he codes his orchestrator against them; you both build in parallel without stepping on each other. This maps exactly to "ben inference, o orchestration."

**⚠️ On-theme guard (non-negotiable for this hackathon).** A photo→try-on image tool alone has **no voice** and weak LiveKit fit — same risk we flagged before. The fix is baked into the split: **the partner's orchestrator must be a LiveKit voice agent.** User *talks* to a stylist, *shows* themselves on camera (LiveKit video track → frame), the agent calls `analyze → recommend → tryon` and **speaks the rationale while showing the try-on**. Voice + video + agent-calling-tools = full LiveKit stack = valid entry + the wow. If the partner's layer is "just an upload form," the project is off-theme. Make sure his half is the voice agent.

---

## 1. Architecture & dataflow

```
                          ┌─────────────────  PARTNER  ─────────────────┐
   user (voice) ──speaks──▶  LiveKit voice agent (STT→LLM→TTS)          │
   user (camera)─video────▶  grabs 1 frame from the video track ─┐      │
                          └──────────────────────────────────────┼──────┘
                                                                 │ base_photo
                                  ┌──────────────  ALPER (brain)  ▼──────────────┐
                                  │ TOOL 1  analyze(base_photo) → StyleProfile    │
                                  │   ├─ P0 image-quality + white-balance gate    │
                                  │   ├─ P1 vision analysis (coloring/face/build) │
                                  │   └─ (opt) deterministic color module         │
                                  │ TOOL 2  recommend(profile,mode,n) → Options   │
                                  │   ├─ rule engine → CONSTRAINTS (palette/fit…)  │
                                  │   └─ P2 stylist LLM, locked inside constraints │
                                  │ TOOL 3  tryon(base_photo, option_ids) → render │
                                  │   ├─ P3 identity-preserving image-edit/VTON    │
                                  │   └─ P4 critic loop (verify → retry ≤2)        │
                                  └───────────────────────────────────────────────┘
                                                                 │ profile + options + rendered image(s)
   agent speaks rationale + UI shows the try-on  ◀──────────────┘
```

Each tool is a pure function. The orchestrator decides *when* to call them and what to say.

---

## 2. The 3-tool interface (what the partner codes against)

```
analyze(base_photo: image)            -> StyleProfile        # §3
recommend(profile, mode, n)           -> Options             # §4   mode ∈ {generative, catalog}
tryon(base_photo, option_ids[])       -> { image_url, critic_report }   # §5
```
Stateless, JSON, independently testable. The partner can call `analyze` the moment a face is on camera, narrate the profile by voice, call `recommend`, read the options aloud, then call `tryon` on the user's pick.

---

## 3. TOOL 1 — `analyze` → StyleProfile

### 3.1 The contract (StyleProfile schema)
Tight, every field actionable, **confidence on every inference**, a feasibility gate so we never recommend on a garbage photo.

```json
{
  "image_quality": {
    "usable": true,
    "issues": [],                       // low_light | motion_blur | face_occluded | torso_not_visible | strong_color_cast
    "framing": "head_and_torso",        // head_only | head_and_torso | full_body
    "white_balance_cast": "neutral",    // warm | cool | neutral | unknown
    "wb_confidence": 0.7
  },
  "person": {
    "apparent_age_range": "25-34",
    "presentation": "masculine",        // catalog-filter only, NOT an identity claim
    "presentation_confidence": 0.8
  },
  "coloring": {
    "skin_undertone": "warm",           // warm | cool | neutral | olive
    "undertone_cues": ["golden cast in WB-corrected cheek", "warm-brown hair", "hazel eyes"],
    "undertone_confidence": 0.6,
    "skin_depth": "medium",             // light | medium | deep
    "hair_color": "dark_brown",
    "eye_color": "hazel",
    "contrast_level": "high",           // high | medium | low  (hair-vs-skin)
    "season": "autumn",                 // simplified 4-season, or "unknown"
    "season_confidence": 0.5
  },
  "face": {
    "shape": "round",                   // oval|round|square|heart|oblong|diamond
    "shape_confidence": 0.6,
    "neck_length": "short",             // short|average|long
    "notable_features": ["strong jaw"]
  },
  "build": {
    "type": "athletic",                 // slim|athletic|average|broad|fuller (visible-only)
    "shoulder_width": "broad",
    "build_confidence": 0.5
  },
  "current_style": {
    "detected_vibe": ["streetwear","casual"],
    "currently_wearing": "black crewneck tee",
    "accessories": []
  },
  "tryon_feasibility": { "hat": true, "tshirt": true }
}
```

### 3.2 The robustness trick (this is the depth, not a generic vision call)
The #1 failure of AI stylists is **wrong color reads from uncontrolled selfies** (white balance varies wildly → undertone garbage → bad palette → whole product looks dumb). Defenses, in order:

1. **White-balance gate first.** Estimate lighting cast using near-neutral references already in the frame — **eye sclera (whites), teeth, neutral background/clothing.** State the cast; the model mentally corrects skin before reading undertone. (v2: deterministic — sample these as gray-point, correct skin pixels in Lab space.)
2. **Relational undertone, never absolute.** Decide warm/cool/neutral/olive by reasoning *across* skin + hair + eyes together; if they conflict or WB is `unknown`, **lower confidence and lean `neutral`.**
3. **Graceful degradation.** Low `undertone_confidence` (<0.5) → recommend the **safe-universal palette** (navy, teal, true red, charcoal, jewel tones) instead of a risky narrow one. A robust "good" beats a confident "wrong."
4. **Feasibility gate.** Torso not front-facing → `tshirt:false` (don't try-on a tee on a side profile). Big hair/existing hat blocking the crown → `hat:false`. The orchestrator routes around it ("turn to face me / take your cap off").

### 3.2b White balance, in plain words (point 1)
The photo carries a colour tint from the lighting — a yellow bulb makes everything warmer/yellower, shade makes it bluer. If we read skin colour raw, a yellow-tinted photo makes a **cool**-toned person look **warm** → we hand them the wrong palette → the whole stylist looks dumb. Fix: find something we KNOW is neutral/white in the frame — **eye whites, teeth** — see how tinted THEY look, and subtract that tint before judging skin. Like taking off tinted sunglasses before judging someone's colour. No neutral reference in frame → we say so and play safe (universal palette). That's the whole trick.

### 3.3 P1 — Vision Analysis prompt (paste-ready)

```
SYSTEM:
You are a master personal stylist and color analyst, trained in fashion color theory
(seasonal system), face-shape morphology, and body-proportion dressing. You analyze ONE
photo of a person and output ONLY a JSON object matching the schema given by the user.

Rules:
- Never invent precision you cannot see. Put a confidence (0-1) on every inferred field
  and list the visual cues behind each key judgment.
- Be robust to bad photos. If lighting is poor or a region is not visible, say so in
  image_quality.issues and LOWER the relevant confidence — do not guess.
- presentation is only a catalog filter, not an identity claim.
- Estimate build only from what is visible. Never reshape or flatter reality.

Reasoning protocol (think silently, then emit JSON only):
1. IMAGE QUALITY + WHITE BALANCE. Judge the lighting cast using near-neutral references in
   the frame (eye whites/sclera, teeth, neutral background or clothing). State warm/cool/
   neutral/unknown. Mentally correct skin for this cast before reading color.
2. COLORING. From WB-corrected skin + hair + eyes, reason RELATIONALLY to undertone
   (warm|cool|neutral|olive); cross-check all three; if they conflict or WB is unknown,
   lower confidence and lean neutral. Estimate skin depth, hair/eye color, contrast level
   (hair-vs-skin), and a simplified 4-season.
3. FACE. Shape from jaw/forehead/cheekbone/length ratios; neck length; notable features.
4. BUILD. Visible shoulder width + torso → conservative build estimate only.
5. CURRENT STYLE. What they are wearing + style vibe (so later recommendations match taste).
6. FEASIBILITY. Head clear for a hat? Torso front-facing for a t-shirt?

Output JSON only. No prose, no markdown fences.

USER:
[image attached]
Return a StyleProfile JSON exactly matching this schema: {<<paste §3.1 schema>>}
```

### 3.4 (Optional v2) deterministic color module
Before P1, run a small CV pass: face-mesh → sample cheek+forehead skin pixels and sclera/teeth as gray-point → WB-correct → convert skin to CIE-Lab → classify undertone by a*/b* signature. Feed the result into P1 as a prior ("CV undertone estimate: warm, 0.7"). This is the "perfect" version: color science for color, LLM for semantics. **Defer past MVP** — P1's WB trick is enough for the demo.

---

## 4. TOOL 2 — `recommend` → Options

**Hybrid by design, now over a real B2B store catalog.** A deterministic engine does the matching/scoring (so the LLM can't give bad advice); the LLM only enriches the catalog, writes the human rationale, and taste-checks combos. **Correctness from rules + colour science; naturalness from the LLM.** The person's photo and the store's products meet in one scoring schema — §4.2.

### 4.1 Rule tables (MVP — encoded stylist heuristics)

**Face shape → hat:**
| Shape | Recommend | Avoid |
|---|---|---|
| oval | most styles; balanced brim | — |
| round | structured/angular, taller crown, straight brim | round beanie worn low, snug bucket |
| square | rounded crown, soft fedora, medium brim | hard flat structured brim (echoes jaw) |
| oblong/long | wide–medium brim, **low** crown, fuller beanie | tall crown, brimless |
| heart | medium brim, slight downward tilt | wide tall crown (exaggerates forehead) |
| diamond | medium brim, fuller crown | narrow brims that sharpen cheekbones |
+ head scale → cap/hat proportion (small head → smaller silhouette).

**Undertone/season → palette (hat + tee color):**
| Profile | Wear | Avoid |
|---|---|---|
| warm / autumn | olive, rust, mustard, terracotta, cream, forest, warm brown | icy pastels, pure white (use cream) |
| warm / spring | coral, peach, warm turquoise, golden yellow, camel, ivory | heavy black base, muted grey |
| cool / winter | true white, black, navy, royal, emerald, magenta, cool red | orange, mustard, camel |
| cool / summer | soft navy, slate, lavender, rose, soft teal, grey | bright orange, warm gold |
| **olive / neutral / unknown** | **SAFE-UNIVERSAL: navy, teal, true red, charcoal, jewel tones** | very warm OR very cool extremes |

**Contrast:** high-contrast person → can wear bold color-blocking / high-contrast combos; low-contrast → tonal/monochrome, avoid stark black↔white.

**Build + neck → t-shirt fit + neckline:**
| Build | Fit | Neckline notes |
|---|---|---|
| slim | slim/regular | crew or Henley; avoid oversized boxy |
| athletic | fitted/regular | crew; structured shoulder fine |
| average | regular | crew or V |
| broad/muscular | regular (not skin-tight) | crew or slight V; mid-weight; avoid clingy |
| fuller | regular drape | V-neck / vertical interest to elongate; avoid clingy + big horizontal stripes |
Neck: long → crew/high; short → V/scoop (elongates). Round face → V-neck; angular face → crew.

### 4.2 The merge: where the person and the catalog meet (point 4)
The person's `StyleProfile` and the store's `Catalog` join at exactly one place — a **deterministic scoring function.** This is the "perfectly organized schema where the two meet" you asked for.

```
StyleProfile ──(deterministic, §4.1 rules)──▶ MatchProfile   (the query)
                                                   │  score every product
Store Catalog ──(offline vision enrich)──────▶ CatalogProduct[]   (the documents)
                                                   ▼
                          ranked per-item Options  ──▶  Outfit combos (1–2)
```

**MatchProfile** — derived from StyleProfile by the §4.1 rule tables, no LLM:
```json
{
  "palette": [{"name":"olive","hex":"#556B2F","family":"warm"}, ...],
  "palette_strategy": "warm-autumn",            // or "safe-universal" if undertone_confidence < 0.5
  "contrast_strategy": "bold",                   // bold | tonal
  "hat":    {"archetypes_ok":["6-panel cap","short-brim fedora"], "archetypes_avoid":["round beanie low"], "scale":"regular"},
  "tshirt": {"fits_ok":["regular","fitted"], "necklines_ok":["crew","slight V"], "avoid":["clingy","big horizontal stripe"]},
  "vibe":   {"streetwear":0.6, "casual":0.4},
  "presentation_filter": "masculine",
  "skin_depth": "medium"
}
```

**CatalogProduct** — the store gives `title/price/sizes/image`; **we enrich the rest offline** (a one-time vision pass per product image, cached, never on the live path):
```json
{
  "id":"SKU123","category":"tshirt","title":"...","price":29.9,"sizes":["M","L"],"image_url":"...",
  "archetype":"crew regular",                    // hat archetype OR tee fit+neckline   (enriched)
  "color":{"name":"olive","hex":"#566B2E","family":"warm","value":"mid","saturation":"muted"},  // enriched
  "pattern":"solid","pattern_scale":"none",      // enriched
  "style_tags":["streetwear","minimal"],         // enriched
  "formality":2,                                 // 1–5 enriched
  "presentation":"unisex"                          // enriched
}
```
> Real store catalogs are messy / missing attributes — that's why enrichment exists. It runs once per product and is cached, so live recommendation is just a fast scored lookup. **Nothing here slows the user flow.**

### 4.3 Scoring (deterministic — correctness lives here, not in the LLM)
For each candidate: **hard-filter, then weighted-score 0–100.**

**Hard filters (drop the product):** wrong presentation (and not unisex) · archetype ∈ `archetypes_avoid` · attribute ∈ `tshirt.avoid` · no size available · category infeasible (`tryon_feasibility`).

**Weighted score** (colour is the highest-impact axis → highest weight):
| Axis | Weight | How |
|---|---|---|
| **Colour fit** | 0.40 | ΔE (Lab) from product hex to nearest `palette` colour + undertone-family match + value suits `skin_depth` + obeys `contrast_strategy` |
| **Shape fit** | 0.30 | hat archetype ∈ `archetypes_ok` / tee fit+neckline ∈ ok-sets (partial credit for near matches) |
| **Vibe match** | 0.20 | cosine(product `style_tags`, person `vibe` weights) — keeps it to THEIR taste |
| **Versatility** | 0.10 | formality fits context · solid > busy for a first pick · tiebreaker |

Return **top-N per category** with the score breakdown. The **rationale** (the wow) is written from the top-contributing factors: *"olive — sits in your warm palette; crew regular — flatters your athletic build; streetwear — matches what you already wear."*

### 4.4 Outfit combinations (point 5 — "toplu arama")
Default = each item searched/rendered separately. When hat **and** tee are searched together, also return **1–2 full looks.** From topK hats × topK tees, score each pair:
- **Individual quality** — the two item scores.
- **Colour harmony between the two** — computed from the two hexes: reward tonal/monochrome, analogous (≤30° hue), or balanced complementary; penalise two competing saturated hues; **respect `contrast_strategy`** (low-contrast person → tonal looks; high-contrast → a contrast pairing is fine).
- **Style coherence** — overlapping `style_tags` + formality within ±1.

Return the best **1–2 outfits** with a "why these work together" line. `tryon` can render a combo in one pass (§5).

### 4.5 The LLM's job shrinks (and that's the point)
Scoring is deterministic → **no hallucinated bad advice.** The LLM does only what it's good at:
1. **Catalog enrichment (offline)** — P-enrich.
2. **Rationale writing** — turn a score breakdown into one natural stylist sentence.
3. **Final combo taste-check** — pick 1–2 from the harmony-shortlist.

**P-enrich — catalog enrichment (offline, once per product, cached):**
```
SYSTEM: You tag a clothing product for a styling engine. From the product image + title,
output ONLY JSON: { category, archetype, color:{name,hex,family(warm|cool|neutral),value(light|mid|dark),saturation},
pattern, pattern_scale, style_tags[], formality(1-5), presentation(masculine|feminine|unisex) }.
Read colour from the garment pixels, not the title. No prose.
USER: [product image]  title: "<<title>>"
```

**P2 — Rationale + combo (live, runs on the already-scored shortlist):**
```
SYSTEM: You are a personal stylist. You are given a person's profile and a SHORTLIST of
products already scored and filtered by hard colour/face/body rules — every item is already
valid. Do NOT add items or change colours. For each item write ONE sentence of rationale tied
to a SPECIFIC profile attribute. If a combo is requested, choose the 1-2 best hat+tee pairs
from the provided harmony-shortlist and give one "why it works" line each. Output JSON only.
USER:
PROFILE: {<<StyleProfile>>}
SHORTLIST: {<<top-N scored hats + tees, with score breakdowns>>}
HARMONY_SHORTLIST: {<<top pairs with harmony scores>>}
```

---

## 5. TOOL 3 — `tryon` → rendered image + critic

### 5.1 Model = OpenAI **gpt-image-1** (image edit) — all on our $100 OpenAI credit
- One model does both: pass the **base person photo + the catalog product image(s)** as inputs and edit. ~$0.02–0.19 per render → $100 = hundreds of renders.
- **Identity drift is gpt-image-1's known weakness** (it tends to redraw faces). Two mitigations, in order:
  1. **Mask the edit region.** Pass an edit mask exposing ONLY the torso (for the tee) and the head-top area (for the hat) and **locking the face + background.** Biggest fidelity win. (Mask = torso polygon + head-top; a cheap segmentation step, cached per session, off the critical path.)
  2. **The async critic** (§5.3) catches any face/colour drift that slips through and silently re-renders.
- **Hat + tee:** default = **two sequential masked edits** (lock more each pass = more reliable). For a combo (point 5), render both in one pass.
- Product fidelity matters (B2B — it's a real SKU): the catalog product image is the reference, and the critic checks the rendered garment matches it.

### 5.2 P3 — Try-On / image-edit prompt (paste-ready)

```
Edit the provided BASE photo so the person is wearing the specified garments.

PRESERVE EXACTLY (do not change): the person's face and identity, skin tone, hairstyle,
body pose, hands, the background, the camera angle, and the scene's lighting and shadows.

CHANGE ONLY the clothing:
- Replace their current top with: {tshirt: color + style}, matching this reference image
  [TSHIRT_REF attached].
- Add: {hat: style + color}, matching this reference [HAT_REF attached], fitted naturally to
  the head with correct perspective and a soft contact shadow.

Match the garments' shading and highlights to the existing light direction in the photo.
Do NOT reshape the body, do NOT beautify or alter the face, do NOT change proportions or
background. Photorealistic and seamless.

Negative: warped or different face, extra fingers/limbs, garment color drifting from the
reference, floating/clipping hat, text or logo artifacts, plastic skin.
```
(If the model supports masks: pass a torso mask for the tee and a head-top mask for the hat to lock everything else.)

### 5.3 Try-On Critic — **async, never blocks the flow** (point 3)
The critic must NOT sit between the user and their result. Sequence:
1. `tryon` runs **one** masked gpt-image-1 edit and returns the image **immediately**.
2. The voice agent **starts speaking the rationale** (~5–10s of natural talk).
3. **In parallel**, the critic (P4) checks the render. Most renders pass → nothing happens, **zero added latency.**
4. Only on a **catastrophic flag** (face warped / wrong garment colour / floating hat) → **one** silent background re-render → the UI **hot-swaps** the image while/after the agent is still talking.

Same grounding discipline as the rest of our work, applied to pixels — but off the critical path.

```
SYSTEM: You verify a virtual try-on. Compare the OUTPUT image to (A) the BASE photo and
(B) the INTENDED garments. Be strict: a wrong garment color or an altered face is a FAIL.
Return JSON only:
{
  "identity_preserved": 0-1,        // same person's face?
  "pose_preserved": 0-1,
  "tshirt_correct": bool,           // present + color matches intent
  "hat_natural": bool,              // present + fits the head, no floating/clipping
  "artifacts": [],                  // warped_face | extra_fingers | color_bleed | floating_hat | ...
  "verdict": "pass" | "retry",
  "fix_instruction": ""             // if retry: one concrete edit to add to the P3 prompt
}
USER: BASE [img], OUTPUT [img], INTENDED: {tshirt..., hat...}
```
**Cap = 1 background retry** (cost + anti-loop), then return the best render flagged `low_confidence`. Net: quality protection with **no perceived latency** — the rationale narration overlaps the check. The differentiator vs a naive demo, in our house style.

---

## 6. MVP cut (first longshot) vs vision

**SHIP in the hackathon (the demo that has to work):**
- Front-facing half-body selfie (or a clean LiveKit video frame).
- `analyze` → StyleProfile in one P1 call (WB trick + feasibility gate + confidences).
- Rule engine → constraints → P2 → **2 hats + 2 tees** with rationale.
- Garments from a **pre-baked ~12-item seed catalog** (reliability) — generative mode visible as "v2".
- `tryon` on the user's pick → image-edit → **P4 critic, ≤2 retries.**
- Surfaced by the **partner's LiveKit voice agent**: speaks the profile + rationale while showing the try-on.

**DEFER (the vision, say it out loud in the pitch):** deterministic Lab color module · full 12-season analysis · live garment generation · real product catalog + checkout (the B2B engine) · multi-angle/full-body · pants/shoes/accessories · "save my profile, shop later."

---

## 7. Models, cost, tooling
- **analyze + recommend + enrich:** GPT-4o / 4o-mini vision on our **OpenAI credit ($100 total: 50+50)**. *(MiMo-only is the RevSignal rule; not this project.)*
- **tryon:** **OpenAI gpt-image-1** image-edit, same credit (~$0.02–0.19/render).
- **voice/video transport:** LiveKit (partner's layer).
- **Cost discipline:** catalog enrichment is one-time/cached · cap critic to 1 retry · render combos only on request. $100 is plenty for the demo — just don't loop renders.

---

## 8. Decisions — now resolved (was open)
1. **Voice / LiveKit:** ✅ partner owns it (LiveKit + voice). On-theme guard satisfied.
2. **tryon model:** ✅ OpenAI **gpt-image-1**, masked edit, on our $100 credit.
3. **garments:** ✅ real **store catalog** products (B2B); the try-on render is generated live. Recommendation = retrieval + ranking over the enriched catalog (§4).
4. **base photo:** ✅ the person's initial photo; products come from the store catalog; the two meet in the §4.2 scoring schema.
5. **combos:** ✅ items rendered separately by default + a **toplu/combo search** returns 1–2 curated hat+tee looks (§4.4).

**The tool-call contract is now written — see §9** (partner repo `michalrokita/Telli-Livekit-Hack` exists, scaffolded with the official `livekit-agents` + `livekit-simulations` skills).

---

## 9. Repo & tool-call contract — partner's LiveKit agent ↔ your 3 tools
> Repo = `github.com/michalrokita/Telli-Livekit-Hack` (currently just a README + the official `livekit-agents` + `livekit-simulations` skills). This section is the seam so both halves build in parallel without colliding.

### 9.1 Proposed repo layout (clean seam)
```
/agent/            # PARTNER — LiveKit voice agent (entrypoint, AgentSession, function_tools, UI)
/stylist/          # YOU — the brain. NO LiveKit dependency → independently testable.
    schemas.py     #   StyleProfile / CatalogProduct / Options   (THE contract)
    rules.py       #   §4.1 tables → MatchProfile → scoring → colour harmony
    analyze.py     #   analyze(photo)            -> StyleProfile        (P0+P1)
    recommend.py   #   recommend(profile,n,combo)-> Options            (scoring + P2)
    tryon.py       #   tryon(photo,option_ids)   -> {image_url, critic} (P3 + async P4)
    catalog/       #   enriched catalog json (P-enrich, offline, cached)
    tests/         #   fixture tests per function (the skill MANDATES tests)
```
The brain has **zero LiveKit imports** → the partner just `import stylist` (or calls a tiny local FastAPI). The seam is `schemas.py`. Hand him that file first.

### 9.2 The 3 LiveKit `@function_tool`s the partner adds to his Agent
Each is a thin wrapper that calls your brain. The agent's job is to *talk*; the brain does the work.
```python
@function_tool
async def analyze_user_photo(self):            # called once when the user is on camera
    frame = self.room.grab_video_frame()       # PARTNER side (LiveKit video track)
    self.profile = stylist.analyze(frame)
    return short_spoken_summary(self.profile)   # agent reads it: "warm tones, athletic build…"

@function_tool
async def recommend_items(self, category: str, combo: bool = False):
    self.options = stylist.recommend(self.profile, n=2, combo=combo)
    return spoken_options(self.options)         # fast: deterministic over the pre-enriched catalog

@function_tool
async def try_on(self, option_ids: list[str]):
    # SPEAK WHILE IT RENDERS — never silent (see 9.3)
    job = stylist.tryon(self.last_photo, option_ids)
    self.ui.show(job.image_url)                 # push image to UI out-of-band
    return "Here's how that looks on you."      # critic runs async + hot-swaps if needed
```

### 9.3 Latency contract (the skill's #1 rule: "latency is critical")
- **Keep each tool's synchronous return tiny** (IDs + one short sentence). Push images to the UI **out-of-band** — the agent speaks, the UI shows. Don't return base64 into the conversation.
- **`tryon` is the only slow call (~few s)** → always pair with a verbal filler turn ("let me put that on you…"). Never a silent gap. The async critic (§5.3) overlaps the narration.
- **Pre-enrich the catalog offline** → `recommend` is sub-second.
- **Don't bloat the agent's system prompt** — styling logic lives in `/stylist`, not in the agent's context. The skill warns context bloat kills latency; the agent just calls tools.
- **Pre-warm `analyze`** the moment a clear face is on camera, so the profile is ready before the user asks.

### 9.4 Tests & simulations (their repo culture)
- `stylist/tests/`: fixture photos → asserted StyleProfile shape; a sample catalog → asserted ranking order; golden combos. Pure functions = trivial to test.
- Use the installed **`livekit-simulations`** skill to script voice scenarios for the full loop: happy path · bad photo → "turn to face me / take your cap off" (the feasibility gate, §3.2) · combo request (§4.4). This is also your demo dry-run harness.

### 9.5 Who builds what (final, maps to the repo)
| | Partner (`/agent`) | You (`/stylist`) |
|---|---|---|
| LiveKit voice loop (STT/LLM/TTS via LiveKit Inference) | ✅ | — |
| video frame-grab + UI to show try-on | ✅ | — |
| the 3 `@function_tool` wrappers | ✅ (calls your brain) | provides the functions |
| analyze / recommend / tryon logic + prompts + scoring | — | ✅ |
| catalog enrichment + tests | — | ✅ |

---
*v0.2 — ArtificialArtz · the brain half. Built to be improved. The contract = `schemas.py` (§3/§4) + the tool seam (§9): hand the partner `schemas.py`, both halves build in parallel.*
