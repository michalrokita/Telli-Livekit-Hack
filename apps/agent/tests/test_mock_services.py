from style_concierge.mock_services import (
    analyze_customer_image,
    generate_try_on_images,
    search_products,
    summarize_cart,
)


def test_image_analysis_extracts_demo_qualities():
    result = analyze_customer_image("customer-demo", category="hats")

    assert result["hair_color"]
    assert result["skin_tone"]
    assert len(result["style_notes"]) >= 3
    assert "hat" in result["summary"].lower()


def test_product_search_returns_five_matching_items():
    products = search_products(
        category="tshirts",
        style_goal="easy premium basics",
        qualities={
            "hair_color": "dark brown",
            "skin_tone": "warm olive",
            "undertone": "golden",
            "contrast": "medium",
        },
    )

    assert len(products) == 5
    assert [product["id"] for product in products] == [
        "TEE-OLIVE-001",
        "TEE-RUST-002",
        "TEE-NAVY-003",
        "TEE-CHARCOAL-004",
        "TEE-CREAM-005",
    ]
    assert [product["name"] for product in products[:2]] == [
        "Heavyweight Olive Crew Tee",
        "Garment-Dyed Rust Pocket Tee",
    ]
    assert all(product["price"] > 0 for product in products)
    assert all(product["category"] == "tshirts" for product in products)


def test_try_on_generation_uses_selected_product_ids():
    products = search_products(
        category="hats",
        style_goal="city weekend",
        qualities={
            "hair_color": "dark brown",
            "skin_tone": "warm olive",
            "undertone": "golden",
            "contrast": "medium",
        },
    )
    selected_ids = [product["id"] for product in products[:2]]

    images = generate_try_on_images("customer-demo", products, selected_ids)

    assert [image["product_id"] for image in images] == selected_ids
    assert all(image["status"] == "complete" for image in images)


def test_cart_summary_counts_quantities():
    summary = summarize_cart(
        [
            {"product_id": "hat-1", "quantity": 1},
            {"product_id": "tee-1", "quantity": 2},
        ]
    )

    assert summary["item_count"] == 3
    assert summary["just_added_count"] == 2
