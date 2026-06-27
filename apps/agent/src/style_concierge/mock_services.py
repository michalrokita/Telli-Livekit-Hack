"""Deterministic mock services for the Style Concierge voice demo.

The functions in this module intentionally do not call external APIs. They
return rich, stable payloads that make the demo feel asynchronous and visual
while remaining safe to run in tests and without credentials.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from decimal import Decimal
from typing import Any


Product = dict[str, Any]
Qualities = Mapping[str, Any]


_CATEGORY_COPY = {
    "hats": {
        "noun": "hat",
        "headline": "city-ready hat",
        "occasion": "weekend errands, travel days, and coffee runs",
        "anchors": ["structured brim", "warm neutral", "low-profile crown"],
    },
    "tshirts": {
        "noun": "t-shirt",
        "headline": "premium everyday tee",
        "occasion": "layered workdays, relaxed dinners, and easy weekends",
        "anchors": ["soft drape", "clean neckline", "rich cotton texture"],
    },
}

# Mirrors the `stylist` brain catalog (stylist/catalog/sample_catalog.json): same product
# IDs + flat-garment images (served by the web app from /catalog) so the agent's fallback
# product list shares one identity with what the UI shows and what try-on renders.
# (id, name, color, price, category, image_path)
_CATALOG = [
    ("TEE-OLIVE-001", "Heavyweight Olive Crew Tee", "olive", 29.9, "tshirts", "/catalog/tee-olive-001.png"),
    ("TEE-RUST-002", "Garment-Dyed Rust Pocket Tee", "rust", 32.0, "tshirts", "/catalog/tee-rust-002.png"),
    ("TEE-NAVY-003", "Classic Navy Crew Tee", "navy", 24.9, "tshirts", "/catalog/tee-navy-003.png"),
    ("TEE-CHARCOAL-004", "Charcoal Slub V-Neck Tee", "charcoal", 27.5, "tshirts", "/catalog/tee-charcoal-004.png"),
    ("TEE-CREAM-005", "Vintage Cream Boxy Tee", "cream", 34.9, "tshirts", "/catalog/tee-cream-005.png"),
    ("TEE-TEAL-006", "Teal Ringer Tee", "teal", 26.0, "tshirts", "/catalog/tee-teal-006.png"),
    ("TEE-BLACK-007", "Midnight Black Crew Tee", "black", 25.0, "tshirts", "/catalog/tee-black-007.png"),
    ("TEE-WHITE-008", "Essential White Crew Tee", "white", 22.9, "tshirts", "/catalog/tee-white-008.png"),
    ("HAT-CAP-009", "Olive 6-Panel Cap", "olive", 28.0, "hats", "/catalog/hat-cap-009.png"),
    ("HAT-FEDORA-010", "Charcoal Short-Brim Fedora", "charcoal", 59.9, "hats", "/catalog/hat-fedora-010.png"),
    ("HAT-BEANIE-011", "Navy Ribbed Beanie", "navy", 21.0, "hats", "/catalog/hat-beanie-011.png"),
    ("HAT-BUCKET-012", "Rust Cotton Bucket Hat", "rust", 33.0, "hats", "/catalog/hat-bucket-012.png"),
    ("HAT-CAP-013", "Black 5-Panel Cap", "black", 26.5, "hats", "/catalog/hat-cap-013.png"),
    ("HAT-BEANIE-014", "Cream Cuffed Beanie", "cream", 23.5, "hats", "/catalog/hat-beanie-014.png"),
]


def _normalize_category(category: str) -> str:
    normalized = category.strip().lower().replace("-", "").replace("_", "")
    if normalized in {"hat", "caps", "cap"}:
        return "hats"
    if normalized in {"tshirt", "tshirts", "tee", "tees", "shirt"}:
        return "tshirts"
    return "hats"


def _copy_category(category: str) -> dict[str, Any]:
    normalized = _normalize_category(category)
    return _CATEGORY_COPY[normalized]


def analyze_customer_image(image_ref: str, category: str = "hats") -> dict[str, Any]:
    """Return deterministic style qualities extracted from a customer image.

    Args:
        image_ref: Stable reference to the customer photo or video frame.
        category: Shopping category currently being considered.
    """

    category_key = _normalize_category(category)
    copy = _copy_category(category_key)

    return {
        "image_ref": image_ref,
        "category": category_key,
        "hair_color": "dark brown",
        "skin_tone": "warm olive",
        "undertone": "golden",
        "contrast": "medium",
        "face_shape": "soft oval",
        "fit_cues": {
            "best_scale": "medium visual weight",
            "neckline_or_brim": "clean rounded lines",
            "avoid": "icy pastels and overly stark contrast",
        },
        "palette": [
            "deep olive",
            "washed black",
            "warm taupe",
            "bone white",
            "clay beige",
        ],
        "style_notes": [
            f"Warm neutrals will flatter the customer's golden undertone for this {copy['noun']} choice.",
            "Medium contrast keeps the look sharp without overpowering the face.",
            "Textured materials add dimension next to dark brown hair.",
            f"Best use case: {copy['occasion']}.",
        ],
        "summary": (
            f"I see dark brown hair, warm olive skin, and a golden undertone, "
            f"so I would steer the {copy['noun']} recommendations toward "
            "warm neutrals, medium contrast, and refined texture."
        ),
        "confidence": 0.92,
        "mock_analysis": True,
    }


def search_products(
    category: str,
    style_goal: str,
    qualities: Qualities | None = None,
) -> list[Product]:
    """Return five deterministic products matched to the category and qualities."""

    category_key = _normalize_category(category)
    copy = _copy_category(category_key)
    qualities = qualities or {}
    style_goal_text = style_goal.strip() or "an easy, polished everyday look"
    hair_color = qualities.get("hair_color", "dark brown")
    skin_tone = qualities.get("skin_tone", "warm olive")
    contrast = qualities.get("contrast", "medium")

    catalog = [item for item in _CATALOG if item[4] == category_key][:5]

    return [
        {
            "id": product_id,
            "category": product_category,
            "name": name,
            "color": color,
            "price": price,
            "currency": "USD",
            "image_url": image_path,
            "match_score": round(0.96 - (index * 0.035), 3),
            "why_it_matches": [
                f"Fits the requested style goal: {style_goal_text}.",
                f"The {color.lower()} tone works well with {skin_tone} skin.",
                f"Balanced for {contrast} contrast and {hair_color} hair.",
            ],
            "styling_tip": (
                f"Pair this {copy['noun']} with {copy['anchors'][index % len(copy['anchors'])]} "
                "to keep the outfit intentional but easy."
            ),
            "inventory": {
                "status": "in_stock",
                "available_sizes": ["S", "M", "L", "XL"] if product_category == "tshirts" else ["OS"],
                "ships_in_days": 2 + (index % 2),
            },
        }
        for index, (product_id, name, color, price, product_category, image_path) in enumerate(catalog)
    ]


def generate_try_on_images(
    image_ref: str,
    products: Sequence[Product],
    selected_product_ids: Sequence[str],
) -> list[dict[str, Any]]:
    """Return completed mock try-on images for the selected products.

    The payload includes a long-running generation timeline even though the
    function completes immediately.
    """

    product_by_id = {str(product["id"]): product for product in products}
    images: list[dict[str, Any]] = []

    for position, product_id in enumerate(selected_product_ids, start=1):
        product = product_by_id.get(str(product_id))
        if product is None:
            continue

        job_id = f"tryon-{image_ref}-{product_id}".replace(" ", "-").lower()
        images.append(
            {
                "id": f"{job_id}-image",
                "job_id": job_id,
                "customer_image_ref": image_ref,
                "product_id": product_id,
                "product_name": product["name"],
                "status": "complete",
                "position": position,
                "image_url": f"https://demo.style-concierge.local/tryons/{job_id}.jpg",
                "thumbnail_url": f"https://demo.style-concierge.local/tryons/{job_id}-thumb.jpg",
                "mock_generation": True,
                "long_running_generation": {
                    "represented": True,
                    "estimated_seconds": 18,
                    "phases": [
                        {"name": "mask_customer", "status": "complete", "progress": 0.25},
                        {"name": "align_product", "status": "complete", "progress": 0.55},
                        {"name": "render_try_on", "status": "complete", "progress": 0.9},
                        {"name": "polish_preview", "status": "complete", "progress": 1.0},
                    ],
                },
                "caption": f"{product['name']} shown on the customer with realistic fit and lighting.",
            }
        )

    return images


def summarize_cart(items: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Summarize cart line items for the mock checkout flow."""

    lines = list(items)
    item_count = sum(int(line.get("quantity", 1)) for line in lines)
    subtotal = sum(
        Decimal(str(line.get("price", 0))) * int(line.get("quantity", 1))
        for line in lines
    )

    return {
        "item_count": item_count,
        "just_added_count": len(lines),
        "subtotal": float(subtotal),
        "currency": "USD",
        "cart_id": "cart-style-concierge-demo",
        "checkout": {
            "status": "ready_for_delivery_details" if item_count else "empty",
            "payment_method": "mock_apple_pay",
            "apple_pay_sheet": {
                "merchant": "Style Concierge Demo",
                "button_label": "Pay with Apple Pay",
                "status": "mock_ready",
            },
        },
        "lines": [
            {
                "product_id": line.get("product_id"),
                "quantity": int(line.get("quantity", 1)),
                "name": line.get("name", "Selected item"),
                "price": float(Decimal(str(line.get("price", 0)))),
            }
            for line in lines
        ],
    }
