"""stylist.catalog — seed catalog + offline, cached enrichment (Phase 4).

A real store hands us messy products with only ``title / price / sizes / image``.
This module turns each raw product into a fully-typed ``schemas.CatalogProduct`` by
running a ONE-TIME vision pass (P-enrich, §4.5) over the product image — reading the
colour from the *pixels*, not the title — and caching the result to ``enriched.json``.
The live recommendation path never re-enriches; it just loads the cache.

Public surface (the seam the recommend engine consumes):
  * ``enrich(product, *, model="gpt-5.5", cassette=None) -> CatalogProduct``
  * ``enrich_catalog(*, force=False) -> list[CatalogProduct]``   (idempotent, writes enriched.json)
  * ``load_catalog() -> list[CatalogProduct]``                    (reads enriched.json)
  * ``build_images(*, force=False)``                              (regenerate the synthetic PNGs)

Model: enrichment must READ COLOUR FROM PIXELS → capability-critical → ``model="gpt-5.5"``.
Offline/replay: vision calls go through ``stylist._openai`` cassettes
(``tests/fixtures/cassettes/catalog_<id>.json``); ``STYLIST_LIVE=1`` makes them real.

Source of truth: ``stylist-engine-algorithm.md`` §4.2 (schema), §4.5 (P-enrich), §6 (MVP seed).
"""

from __future__ import annotations

import json
from pathlib import Path

from stylist import schemas
from stylist._openai import vision_json

# --------------------------------------------------------------------------- #
# Paths                                                                        #
# --------------------------------------------------------------------------- #
_HERE = Path(__file__).resolve().parent          # stylist/catalog
_STYLIST_ROOT = _HERE.parent                      # stylist
SAMPLE_PATH = _HERE / "sample_catalog.json"
ENRICHED_PATH = _HERE / "enriched.json"
IMAGES_DIR = _HERE / "images"

# Colour / saturation enrichment model. Pixels, not the title → the strong tier.
ENRICH_MODEL = "gpt-5.5"

# --------------------------------------------------------------------------- #
# P-enrich — the §4.5 SYSTEM prompt, VERBATIM.                                 #
# --------------------------------------------------------------------------- #
P_ENRICH_SYSTEM = (
    "You tag a clothing product for a styling engine. From the product image + title, "
    "output ONLY JSON: { category, archetype, "
    "color:{name,hex,family(warm|cool|neutral),value(light|mid|dark),saturation}, "
    "pattern, pattern_scale, style_tags[], formality(1-5), "
    "presentation(masculine|feminine|unisex) }. "
    "Read colour from the garment pixels, not the title. No prose."
)

# Fields the vision pass OWNS; everything else comes from the raw store record.
_ENRICHED_FIELDS = (
    "archetype",
    "color",
    "pattern",
    "pattern_scale",
    "style_tags",
    "formality",
    "presentation",
)
# Raw store fields we trust over the model (category stays authoritative from the store).
_RAW_FIELDS = ("id", "category", "title", "price", "sizes", "image_url")


# --------------------------------------------------------------------------- #
# Raw catalog loader                                                           #
# --------------------------------------------------------------------------- #
def load_sample(path: Path | str | None = None) -> list[dict]:
    """Load the raw seed catalog (list of ``{id, category, title, price, sizes, image_url}``)."""
    p = Path(path) if path is not None else SAMPLE_PATH
    data = json.loads(Path(p).read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"sample catalog must be a JSON array, got {type(data).__name__}")
    return data


def _image_path(image_url: str) -> Path:
    """Resolve a catalog ``image_url`` (relative to the stylist package) to a real path."""
    p = Path(image_url)
    return p if p.is_absolute() else (_STYLIST_ROOT / p)


def _cassette_for(product: dict) -> str:
    return f"catalog_{product['id']}"


# --------------------------------------------------------------------------- #
# enrich — one product → CatalogProduct (vision reads colour from pixels)      #
# --------------------------------------------------------------------------- #
def enrich(product: dict, *, model: str = ENRICH_MODEL, cassette: str | None = None) -> schemas.CatalogProduct:
    """Enrich ONE raw store product into a typed ``CatalogProduct`` via P-enrich.

    The raw ``id/category/title/price/sizes/image_url`` are merged with the model's
    ``color/archetype/pattern/style_tags/formality/presentation`` (colour read from the
    garment pixels). Offline by default: replays ``catalog_<id>.json`` unless ``STYLIST_LIVE=1``.
    """
    if cassette is None:
        cassette = _cassette_for(product)

    enriched = vision_json(
        system=P_ENRICH_SYSTEM,
        user_text=f'title: "{product["title"]}"',
        image=str(_image_path(product["image_url"])),
        model=model,
        cassette=cassette,
    )

    merged: dict = {k: product[k] for k in _RAW_FIELDS}
    for k in _ENRICHED_FIELDS:
        if k not in enriched:
            raise ValueError(
                f"P-enrich output for {product.get('id')!r} is missing required field {k!r}"
            )
        merged[k] = enriched[k]
    return schemas.CatalogProduct.from_dict(merged)


# --------------------------------------------------------------------------- #
# enrich_catalog — whole seed → enriched.json, idempotent + cached            #
# --------------------------------------------------------------------------- #
def enrich_catalog(*, force: bool = False) -> list[schemas.CatalogProduct]:
    """Enrich every seed product, caching to ``enriched.json``.

    Idempotent: ids already present in ``enriched.json`` are reused as-is (no vision
    call, so no cassette needed) unless ``force=True`` re-enriches everything.
    Returns the products in seed order and (re)writes ``enriched.json`` only on change.
    """
    raw = load_sample()

    cached: dict[str, dict] = {}
    if ENRICHED_PATH.exists() and not force:
        for d in json.loads(ENRICHED_PATH.read_text(encoding="utf-8")):
            cached[d["id"]] = d

    out: list[schemas.CatalogProduct] = []
    changed = False
    for product in raw:
        pid = product["id"]
        if not force and pid in cached:
            out.append(schemas.CatalogProduct.from_dict(cached[pid]))  # re-validate cache
        else:
            out.append(enrich(product, model=ENRICH_MODEL))
            changed = True

    if changed or not ENRICHED_PATH.exists():
        payload = [p.to_dict() for p in out]
        ENRICHED_PATH.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    return out


def load_catalog() -> list[schemas.CatalogProduct]:
    """Load the cached enriched catalog into ``CatalogProduct[]`` (the live-path read).

    ``image_url`` is resolved to an ABSOLUTE path (it is stored relative to the stylist
    package) so any consumer — e.g. ``tryon`` opening it as a gpt-image-2 render
    reference — works regardless of the current working directory.
    """
    if not ENRICHED_PATH.exists():
        raise FileNotFoundError(
            f"{ENRICHED_PATH} not found — run enrich_catalog() first to build the cache."
        )
    data = json.loads(ENRICHED_PATH.read_text(encoding="utf-8"))
    out: list[schemas.CatalogProduct] = []
    for d in data:
        cp = schemas.CatalogProduct.from_dict(d)
        cp.image_url = str(_image_path(cp.image_url))
        out.append(cp)
    return out


# --------------------------------------------------------------------------- #
# Synthetic product images (PIL, offline) — a clean garment silhouette whose   #
# DOMINANT colour matches the product so the vision pass could read it.        #
# The swatch hex is sourced from each product's cassette → swatch == cassette  #
# colour (single source of truth), so "read colour from pixels" stays honest.  #
# --------------------------------------------------------------------------- #
_W = _H = 640


def _hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def _shade(rgb: tuple[int, int, int], f: float) -> tuple[int, int, int]:
    return tuple(max(0, min(255, int(c * f))) for c in rgb)  # type: ignore[return-value]


def _shape_for(product: dict) -> str:
    if product["category"] == "tshirt":
        return "tee"
    t = product["title"].lower()
    for kw in ("fedora", "beanie", "bucket", "cap"):
        if kw in t:
            return kw
    return "cap"


def _swatch_hex_from_cassette(product: dict, cassette_dir: Path) -> str | None:
    path = cassette_dir / f"{_cassette_for(product)}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))["color"]["hex"]


def _backdrop():
    # Vertical studio gradient → every backdrop row is a slightly different colour,
    # so the single flat garment colour is the unambiguous modal (dominant) colour.
    from PIL import Image

    img = Image.new("RGB", (_W, _H))
    px = img.load()
    top, bot = (238, 238, 242), (203, 204, 210)
    for y in range(_H):
        t = y / (_H - 1)
        row = tuple(int(top[i] + (bot[i] - top[i]) * t) for i in range(3))
        for x in range(_W):
            px[x, y] = row
    return img


def _draw_tee(rgb):
    from PIL import Image, ImageDraw

    img = _backdrop()
    d = ImageDraw.Draw(img)
    edge = _shade(rgb, 0.78)
    cx = _W // 2
    # sleeves
    d.polygon([(150, 250), (235, 215), (270, 300), (205, 345)], fill=rgb, outline=edge)
    d.polygon([(490, 250), (405, 215), (370, 300), (435, 345)], fill=rgb, outline=edge)
    # torso
    d.rounded_rectangle([205, 240, 435, 575], radius=26, fill=rgb, outline=edge, width=2)
    # neckline carved out of the backdrop colour at the top centre
    d.pieslice([cx - 58, 222, cx + 58, 300], start=0, end=180, fill=(224, 225, 230))
    d.arc([cx - 58, 222, cx + 58, 300], start=0, end=180, fill=edge, width=3)
    return img


def _draw_cap(rgb):
    from PIL import Image, ImageDraw

    img = _backdrop()
    d = ImageDraw.Draw(img)
    edge = _shade(rgb, 0.78)
    # curved brim sweeping to the right
    d.pieslice([300, 360, 540, 470], start=300, end=80, fill=_shade(rgb, 0.9), outline=edge)
    # rounded crown
    d.pieslice([170, 200, 450, 470], start=180, end=360, fill=rgb, outline=edge, width=2)
    d.rectangle([170, 330, 450, 392], fill=rgb)
    d.ellipse([300, 215, 320, 235], fill=edge)  # top button
    return img


def _draw_beanie(rgb):
    from PIL import Image, ImageDraw

    img = _backdrop()
    d = ImageDraw.Draw(img)
    edge = _shade(rgb, 0.78)
    # dome
    d.pieslice([200, 190, 440, 470], start=180, end=360, fill=rgb, outline=edge, width=2)
    d.rectangle([200, 330, 440, 405], fill=rgb)
    # folded cuff band
    d.rounded_rectangle([192, 392, 448, 452], radius=18, fill=_shade(rgb, 0.88), outline=edge, width=2)
    return img


def _draw_bucket(rgb):
    from PIL import Image, ImageDraw

    img = _backdrop()
    d = ImageDraw.Draw(img)
    edge = _shade(rgb, 0.78)
    # downward brim
    d.polygon([(180, 360), (460, 360), (500, 440), (140, 440)], fill=_shade(rgb, 0.9), outline=edge)
    # trapezoid crown
    d.polygon([(235, 220), (405, 220), (440, 370), (200, 370)], fill=rgb, outline=edge)
    d.line([(210, 330), (430, 330)], fill=edge, width=3)  # band seam
    return img


def _draw_fedora(rgb):
    from PIL import Image, ImageDraw

    img = _backdrop()
    d = ImageDraw.Draw(img)
    edge = _shade(rgb, 0.78)
    # wide flat brim
    d.ellipse([135, 380, 505, 460], fill=_shade(rgb, 0.9), outline=edge, width=2)
    # pinched crown
    d.rounded_rectangle([245, 230, 395, 415], radius=40, fill=rgb, outline=edge, width=2)
    d.rectangle([245, 380, 395, 415], fill=rgb)
    # ribbon band
    d.rectangle([245, 360, 395, 392], fill=_shade(rgb, 0.7))
    return img


_DRAW = {
    "tee": _draw_tee,
    "cap": _draw_cap,
    "beanie": _draw_beanie,
    "bucket": _draw_bucket,
    "fedora": _draw_fedora,
}


def build_images(*, force: bool = False, cassette_dir: Path | str | None = None) -> list[Path]:
    """Render one synthetic PNG per seed product under ``catalog/images/``.

    The fill colour is read from each product's cassette (so the swatch the vision
    pass 'sees' equals the cassette colour). Falls back to a mid-grey if a cassette is
    missing — generation never blocks. Returns the list of written paths.
    """
    from stylist._openai import CASSETTE_DIR

    cdir = Path(cassette_dir) if cassette_dir is not None else CASSETTE_DIR
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for product in load_sample():
        out = _image_path(product["image_url"])
        if out.exists() and not force:
            written.append(out)
            continue
        hexv = _swatch_hex_from_cassette(product, cdir) or "#808080"
        rgb = _hex_to_rgb(hexv)
        img = _DRAW[_shape_for(product)](rgb)
        out.parent.mkdir(parents=True, exist_ok=True)
        img.save(out, "PNG")
        written.append(out)
    return written


__all__ = [
    "P_ENRICH_SYSTEM",
    "ENRICH_MODEL",
    "SAMPLE_PATH",
    "ENRICHED_PATH",
    "IMAGES_DIR",
    "load_sample",
    "enrich",
    "enrich_catalog",
    "load_catalog",
    "build_images",
]
