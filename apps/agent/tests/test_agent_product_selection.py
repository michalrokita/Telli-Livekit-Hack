from agent import (
    _compact_cart_response,
    _compact_delivery_response,
    _compact_tryon_response,
    _delivery_payload,
    _delivery_source_matches_payload,
    _looks_like_ready_confirmation,
    _resolve_product_selectors,
    _turn_handling_options,
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


def test_tryon_tool_response_is_compact_and_points_to_cart_selection():
    response = _compact_tryon_response(["Camel Cord Cap", "Olive Canvas Cap"])

    assert response == {
        "status": "tryons_ready",
        "product_names": ["Camel Cord Cap", "Olive Canvas Cap"],
        "next_step": "Say the try-on previews are ready, then ask which product names to add to cart.",
    }


def test_cart_tool_response_is_compact_and_asks_for_delivery_details_immediately():
    response = _compact_cart_response(["Camel Cord Cap"])

    assert response == {
        "status": "items_added",
        "added_names": ["Camel Cord Cap"],
        "next_step": (
            "Say the items were added, then ask for delivery details now: "
            "recipient name, street address, city, state, postal code, and phone."
        ),
    }


def test_delivery_tool_response_is_compact_and_points_to_payment():
    response = _compact_delivery_response()

    assert response == {
        "status": "delivery_details_filled",
        "next_step": "Tell the customer the form is filled, ask them to review it, and point to mock Apple Pay.",
    }


def test_camera_capture_requires_explicit_ready_confirmation():
    assert _looks_like_ready_confirmation("I'm ready")
    assert _looks_like_ready_confirmation("go ahead and take the photo")
    assert not _looks_like_ready_confirmation("what was that")
    assert not _looks_like_ready_confirmation("background transcript")


def test_delivery_payload_must_match_spoken_source():
    payload = _delivery_payload(
        recipient_name="Sagar",
        street_address="1 Main Street",
        city="Boston",
        state="MA",
        postal_code="02111",
        phone="123-456-7890",
    )

    assert _delivery_source_matches_payload(
        "Send it to Sagar at 1 Main Street in Boston MA, 02111, phone 123-456-7890.",
        payload,
    )
    assert not _delivery_source_matches_payload("Hi.", payload)
    assert not _delivery_source_matches_payload("The family is fine, thanks.", payload)


def test_turn_handling_requires_clearer_interruption_signal():
    options = _turn_handling_options()

    assert options["endpointing"] == {
        "mode": "fixed",
        "min_delay": 0.45,
        "max_delay": 3.0,
    }
    assert options["interruption"] == {
        "enabled": True,
        "mode": "adaptive",
        "min_duration": 0.9,
        "min_words": 2,
        "false_interruption_timeout": 1.8,
        "resume_false_interruption": True,
        "discard_audio_if_uninterruptible": True,
        "backchannel_boundary": (1.2, 1.8),
    }
    assert options["turn_detection"] is not None
