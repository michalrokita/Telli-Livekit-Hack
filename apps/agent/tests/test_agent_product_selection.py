from agent import (
    _delivery_details_prompt,
    _delivery_filled_prompt,
    _delivery_payload,
    _resolve_product_selectors,
)
from style_concierge.mock_services import search_products


def test_agent_resolves_displayed_product_names_to_internal_ids():
    products = search_products(
        category="tshirts",
        style_goal="easy premium basics",
        qualities={"hair_color": "dark brown", "skin_tone": "warm olive"},
    )

    assert _resolve_product_selectors(products, ["Clay Pocket Tee", "camel cap"]) == [
        "clay",
        "camel",
    ]


def test_agent_formats_delivery_payload_for_browser_rpc():
    assert _delivery_payload(
        recipient_name=" Mira Demo ",
        street_address=" 11 Spring Street ",
        city=" New York ",
        state=" NY ",
        postal_code=" 10012 ",
        phone=" 212-555-0198 ",
    ) == {
        "recipient": "Mira Demo",
        "address": "11 Spring Street",
        "city": "New York",
        "state": "NY",
        "postalCode": "10012",
        "phone": "212-555-0198",
    }


def test_cart_tool_prompt_asks_for_delivery_details_immediately():
    prompt = _delivery_details_prompt(["Camel Cord Cap"])

    assert "Camel Cord Cap" in prompt
    assert "ask for delivery details now" in prompt
    assert "Do not ask whether" in prompt
    assert "phone number" in prompt


def test_delivery_filled_prompt_points_to_payment():
    prompt = _delivery_filled_prompt()

    assert "delivery form is filled" in prompt
    assert "mock Apple Pay button" in prompt
