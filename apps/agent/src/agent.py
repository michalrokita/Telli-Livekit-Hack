from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from livekit import rtc
from dotenv import load_dotenv
from livekit import agents
from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
    RunContext,
    ToolError,
    TurnHandlingOptions,
    function_tool,
    get_job_context,
    inference,
    room_io,
)
from livekit.plugins import openai

from style_concierge.mock_services import (
    search_products,
)


APP_DIR = Path(__file__).resolve().parents[1]
REPO_DIR = Path(__file__).resolve().parents[3]
load_dotenv(REPO_DIR / ".env.local")
load_dotenv(REPO_DIR / ".env", override=False)
load_dotenv(APP_DIR / ".env.local")
load_dotenv(APP_DIR / ".env", override=False)

# Make the repo-root `stylist` brain importable from the agent process. We APPEND (not
# prepend) so a plain `import platform` still resolves to the stdlib, not the repo's
# `platform/` package — the brain itself never needs the platform layer.
if str(REPO_DIR) not in sys.path:
    sys.path.append(str(REPO_DIR))


def _recommend_products(profile_dict: dict[str, Any], category_key: str, n: int = 5) -> list[dict[str, Any]]:
    """Run the brain's deterministic `recommend` over the unified catalog → product dicts.

    Synchronous (call via ``asyncio.to_thread``). Scoring is deterministic; the per-item
    rationale is a live LLM call when ``STYLIST_LIVE=1`` and falls back to templates offline.
    Product ids/images match the web catalog so the UI, recommend, and try-on share identity.
    """
    from stylist.recommend import recommend as stylist_recommend
    from stylist.schemas import StyleProfile

    profile = StyleProfile.from_dict(profile_dict)
    options = stylist_recommend(profile, n=max(n, 2)).to_dict()
    bucket = "hats" if category_key == "hats" else "tshirts"

    products: list[dict[str, Any]] = []
    for item in options.get(bucket, [])[:n]:
        product_id = str(item["product_id"])
        products.append(
            {
                "id": product_id,
                "category": category_key,
                "name": item.get("title", product_id),
                "color": item.get("color_hex", ""),
                "price": item.get("price", 0),
                "currency": "USD",
                "image_url": f"/catalog/{product_id.lower()}.png",
                "sizes": item.get("sizes", []),
                "match_score": item.get("score"),
                "recommendation_reason": item.get("rationale", ""),
            }
        )
    return products


AGENT_NAME = os.getenv("AGENT_NAME") or os.getenv("LIVEKIT_AGENT_NAME") or "style-concierge"
REALTIME_MODEL = os.getenv("OPENAI_REALTIME_MODEL", "gpt-realtime-2")
REALTIME_VOICE = os.getenv("OPENAI_REALTIME_VOICE", "marin")
INTERRUPTION_MIN_DURATION = float(os.getenv("MIRA_INTERRUPTION_MIN_DURATION", "1.1"))
INTERRUPTION_MIN_WORDS = int(os.getenv("MIRA_INTERRUPTION_MIN_WORDS", "2"))
FALSE_INTERRUPTION_TIMEOUT = float(os.getenv("MIRA_FALSE_INTERRUPTION_TIMEOUT", "1.8"))


AGENT_INSTRUCTIONS = """
You are Style Concierge, a cheerful voice shopping assistant for a live demo.
Keep replies brief and follow this flow: greet; ask hats or tshirts; ask to prepare
camera; call prepare_customer_camera; wait for the user to say they are ready; then
call analyze_customer_image_tool with the exact ready phrase the user said. Explain
the detected qualities briefly. If the photo is not satisfactory, retake before searching.

Call search_matching_products, then recommend the products it returns using each
product's name and its short reason (do not invent items, prices, or extra picks).
Ask the user to select by exact product names. Call generate_customer_tryons for selected names
with the exact customer sentence that named them. Mention generation can take a
moment, then ask which product names to add. Call add_items_to_cart only with the
exact customer sentence that named items for the cart, then immediately ask for
recipient name, street address, city, state, postal code, and phone. Call
fill_delivery_details only after the customer has actually spoken those fields.
Ask for missing fields instead of guessing. Ask the customer to review the form,
and point to mock Apple Pay.

Trust tools to update the website UI. Do not discuss internal API mode. Never claim
a real purchase or payment was made; inventory, cart, checkout, and Apple Pay are
demo surfaces.

Ignore unclear background speech, unrelated dictation, or transcripts in another
language unless the user clearly addresses Mira with shopping intent. If unsure,
ask one short clarifying question. Never advance the flow from noise, partial
phrases, or guessed details.
""".strip()


async def _browser_rpc(method: str, payload: dict[str, Any], timeout: float = 20.0) -> dict[str, Any]:
    room = get_job_context().room
    participant = _browser_participant(room)

    if participant is None:
        raise ToolError("The browser participant is not connected yet.")

    try:
        response = await room.local_participant.perform_rpc(
            destination_identity=participant.identity,
            method=method,
            payload=json.dumps(payload),
            response_timeout=timeout,
        )
    except Exception as exc:
        raise ToolError(f"Unable to update the website UI with {method}.") from exc

    try:
        parsed = json.loads(response)
    except json.JSONDecodeError:
        return {"status": "ok", "raw": response}

    return parsed if isinstance(parsed, dict) else {"status": "ok", "value": parsed}


def _browser_participant(room: rtc.Room) -> rtc.RemoteParticipant | None:
    standard_participants = [
        participant
        for participant in room.remote_participants.values()
        if participant.kind == rtc.ParticipantKind.PARTICIPANT_KIND_STANDARD
    ]

    return next(
        (
            participant
            for participant in standard_participants
            if participant.attributes.get("demo") == "loma-mira"
        ),
        standard_participants[0] if standard_participants else None,
    )


def _resolve_product_selectors(products: list[dict[str, Any]], selectors: list[str]) -> list[str]:
    resolved: list[str] = []

    for selector in selectors:
        product = _match_product_selector(products, str(selector))
        if product is None:
            continue

        product_id = str(product["id"])
        if product_id not in resolved:
            resolved.append(product_id)

    return resolved


def _match_product_selector(products: list[dict[str, Any]], selector: str) -> dict[str, Any] | None:
    normalized = _normalize_product_selector(selector)

    if not normalized:
        return None

    for product in products:
        if normalized in {
            _normalize_product_selector(str(product.get("id", ""))),
            _normalize_product_selector(str(product.get("name", ""))),
        }:
            return product

    selector_tokens = _product_selector_tokens(selector)
    for product in products:
        product_tokens = _product_selector_tokens(
            " ".join(
                [
                    str(product.get("id", "")),
                    str(product.get("name", "")),
                    str(product.get("color", "")),
                ]
            )
        )
        if selector_tokens and all(token in product_tokens for token in selector_tokens):
            return product

    ordinal_text = normalized[1:] if normalized.startswith("t") else normalized
    if ordinal_text.isdigit():
        ordinal = int(ordinal_text)
        if 1 <= ordinal <= len(products):
            return products[ordinal - 1]

    return None


def _normalize_product_selector(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def _product_selector_tokens(value: str) -> list[str]:
    return [token for token in re.split(r"[^a-z0-9]+", value.lower()) if token]


def _delivery_payload(
    recipient_name: str,
    street_address: str,
    city: str,
    state: str,
    postal_code: str,
    phone: str,
) -> dict[str, str]:
    return {
        "recipient": recipient_name.strip(),
        "address": street_address.strip(),
        "city": city.strip(),
        "state": state.strip(),
        "postalCode": postal_code.strip(),
        "phone": phone.strip(),
    }


def _product_names(products: list[dict[str, Any]]) -> list[str]:
    return [str(product["name"]) for product in products if product.get("name")]


def _string_value(source: dict[str, Any], *keys: str, fallback: str = "") -> str:
    for key in keys:
        value = source.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    return fallback


def _browser_qualities(capture: dict[str, Any]) -> dict[str, Any]:
    raw = capture.get("qualities")
    qualities = raw if isinstance(raw, dict) else {}
    style_notes = qualities.get("styleNotes") or qualities.get("style_notes") or []

    return {
        "hair_color": _string_value(qualities, "hairColor", "hair_color", fallback="natural hair color"),
        "skin_tone": _string_value(qualities, "skinTone", "skin_tone", fallback="balanced skin tone"),
        "undertone": _string_value(qualities, "undertone", fallback="neutral"),
        "contrast": _string_value(qualities, "contrast", fallback="medium"),
        "palette": _string_value(qualities, "palette", fallback="balanced"),
        "style_notes": style_notes if isinstance(style_notes, list) else [],
        "summary": _string_value(
            qualities,
            "summary",
            fallback="I have enough visual context to make a more personal edit.",
        ),
    }


def _compact_tryon_response(product_names: list[str]) -> dict[str, Any]:
    return {
        "status": "tryons_ready",
        "product_names": product_names,
        "next_step": "Say the try-on previews are ready, then ask which product names to add to cart.",
    }


def _compact_cart_response(added_names: list[str]) -> dict[str, Any]:
    return {
        "status": "items_added",
        "added_names": added_names,
        "next_step": (
            "Say the items were added, then ask for delivery details now: "
            "recipient name, street address, city, state, postal code, and phone."
        ),
    }


def _compact_delivery_response() -> dict[str, str]:
    return {
        "status": "delivery_details_filled",
        "next_step": "Tell the customer the form is filled, ask them to review it, and point to mock Apple Pay.",
    }


def _looks_like_ready_confirmation(value: str) -> bool:
    normalized = value.lower()
    return any(
        phrase in normalized
        for phrase in (
            "ready",
            "i'm ready",
            "im ready",
            "take it",
            "take the photo",
            "take a photo",
            "snap",
            "go ahead",
            "yes",
        )
    )


def _delivery_source_matches_payload(source_transcript: str, payload: dict[str, str]) -> bool:
    normalized = source_transcript.lower()
    if len(normalized.split()) < 6:
        return False

    recipient = payload["recipient"].split()[0].lower()
    address_token = payload["address"].split()[0].lower()
    postal_code = payload["postalCode"].lower()
    return recipient in normalized and (address_token in normalized or postal_code in normalized)


def _selection_source_matches_products(source_transcript: str, products: list[dict[str, Any]], selectors: list[str]) -> bool:
    if not selectors:
        return False

    normalized_source = _normalize_product_selector(source_transcript)
    if len(normalized_source) < 3:
        return False

    resolved_ids = _resolve_product_selectors(products, selectors)
    if not resolved_ids:
        return False

    product_by_id = {str(product.get("id")): product for product in products}
    for product_id in resolved_ids:
        product = product_by_id.get(product_id)
        if not product:
            return False

        name = str(product.get("name", ""))
        color = str(product.get("color", ""))
        selector_tokens = [
            token
            for token in _product_selector_tokens(f"{name} {color}")
            if len(token) > 2 and token not in {"tee", "cap", "hat", "the", "and"}
        ]
        if selector_tokens and any(token in normalized_source for token in selector_tokens):
            continue

        if _normalize_product_selector(name) in normalized_source:
            continue

        return False

    return True


def _turn_handling_options() -> TurnHandlingOptions:
    return TurnHandlingOptions(
        turn_detection=inference.TurnDetector(),
        interruption={
            "enabled": True,
            "mode": "adaptive",
            "min_duration": INTERRUPTION_MIN_DURATION,
            "min_words": INTERRUPTION_MIN_WORDS,
            "false_interruption_timeout": FALSE_INTERRUPTION_TIMEOUT,
            "resume_false_interruption": True,
            "discard_audio_if_uninterruptible": True,
            "backchannel_boundary": (1.2, 1.8),
        },
        endpointing={
            "mode": "fixed",
            "min_delay": 0.45,
            "max_delay": 3.0,
        },
    )


class StyleConciergeAgent(Agent):
    def __init__(self) -> None:
        super().__init__(instructions=AGENT_INSTRUCTIONS)
        self._last_products: list[dict[str, Any]] = []
        self._cart_lines: list[dict[str, Any]] = []
        self._camera_session_id: str | None = None
        self._last_image_ref: str | None = None
        self._last_qualities: dict[str, Any] | None = None
        self._last_profile: dict[str, Any] | None = None

    @function_tool(name="prepare_customer_camera")
    async def prepare_customer_camera(
        self,
        context: RunContext,
        category: str,
    ) -> dict[str, Any]:
        """Open the customer's camera preview in the website and wait for voice readiness.

        Args:
            category: The category the customer chose, usually hats or tshirts.
        """

        camera = await _browser_rpc(
            "prepareCustomerCamera",
            {"category": category},
            timeout=8.0,
        )
        camera_session_id = camera.get("cameraSessionId")
        if isinstance(camera_session_id, str):
            self._camera_session_id = camera_session_id
        return {
            "status": "camera_ready",
            "camera_session_id": self._camera_session_id or "current_camera",
            "next_step": "Tell the customer to say they are ready when they like the frame.",
        }

    @function_tool(name="analyze_customer_image_tool")
    async def analyze_customer_image_tool(
        self,
        context: RunContext,
        image_ref: str,
        category: str,
        ready_confirmation: str,
    ) -> dict[str, Any]:
        """After the customer says they are ready, capture the photo in the website and analyze it.

        Args:
            image_ref: The camera session ID from prepare_customer_camera, or "current_camera".
            category: The category the customer chose, usually hats or tshirts.
            ready_confirmation: The exact phrase the customer just said to confirm the photo should be taken.
        """

        if not _looks_like_ready_confirmation(ready_confirmation):
            raise ToolError("Wait until the customer explicitly says they are ready before capturing the photo.")

        image_ref = self._camera_session_id or image_ref
        browser_capture = await _browser_rpc(
            "captureCustomerImage",
            {"imageRef": image_ref, "category": category, "readyConfirmation": ready_confirmation},
            timeout=45.0,
        )
        image_ref = str(browser_capture.get("imageRef") or image_ref)
        result = _browser_qualities(browser_capture)
        self._last_image_ref = image_ref
        self._last_qualities = result
        # Raw StyleProfile dict from the brain's analyze — feeds the real `recommend`.
        style_profile = browser_capture.get("styleProfile")
        self._last_profile = style_profile if isinstance(style_profile, dict) else None
        return {
            "status": "analysis_complete",
            "image_ref": image_ref,
            "hair_color": result.get("hair_color"),
            "skin_tone": result.get("skin_tone"),
            "undertone": result.get("undertone"),
            "contrast": result.get("contrast"),
            "palette": result.get("palette"),
            "style_notes": result.get("style_notes", [])[:3],
            "summary": result.get("summary"),
            "next_step": "Ask whether the photo is satisfactory before searching products.",
        }

    @function_tool(name="search_matching_products")
    async def search_matching_products(
        self,
        context: RunContext,
        category: str,
        style_goal: str,
        hair_color: str = "",
        skin_tone: str = "",
        undertone: str = "",
        contrast: str = "",
    ) -> dict[str, Any]:
        """Find five matching demo products for the customer.

        Args:
            category: The requested category, either hats or tshirts.
            style_goal: The customer's stated style goal or shopping occasion.
            hair_color: Hair color detected by image analysis.
            skin_tone: Skin tone detected by image analysis.
            undertone: Undertone detected by image analysis.
            contrast: Overall visual contrast detected by image analysis.
        """

        if not self._last_qualities:
            raise ToolError("Analyze the customer image before searching for products.")

        category_key = "hats" if re.search(r"hat|cap", category, re.IGNORECASE) else "tshirts"

        # Primary path: the brain's deterministic `recommend` over the real catalog, scored
        # against the customer's actual StyleProfile. Falls back to the mock only if the
        # profile is missing or the brain call fails (never a hard error on the live demo).
        products: list[dict[str, Any]] = []
        if self._last_profile:
            try:
                products = await asyncio.to_thread(
                    _recommend_products, self._last_profile, category_key, 5
                )
            except Exception:
                products = []

        used_recommend = bool(products)
        if not products:
            products = search_products(
                category=category,
                style_goal=style_goal,
                qualities={
                    "hair_color": hair_color or self._last_qualities.get("hair_color"),
                    "skin_tone": skin_tone or self._last_qualities.get("skin_tone"),
                    "undertone": undertone or self._last_qualities.get("undertone"),
                    "contrast": contrast or self._last_qualities.get("contrast"),
                },
            )

        self._last_products = products
        await _browser_rpc(
            "showProductRecommendations",
            {
                "category": category_key,
                "styleGoal": style_goal,
                "products": products,
            },
            timeout=8.0,
        )
        return {
            "status": "complete",
            "source": "stylist_recommend" if used_recommend else "fallback",
            "count": len(products),
            "product_names": _product_names(products),
            "recommendations": [
                {
                    "name": product["name"],
                    "reason": product.get("recommendation_reason") or product.get("styling_tip", ""),
                }
                for product in products
            ],
            "next_step": "Recommend each product name with its short reason, then ask which names they like.",
        }

    @function_tool(name="generate_customer_tryons")
    async def generate_customer_tryons(
        self,
        context: RunContext,
        image_ref: str,
        selected_products: list[str],
        source_transcript: str,
    ) -> dict[str, Any]:
        """Generate try-on previews for selected products.

        Args:
            image_ref: A reference to the customer image or current camera frame.
            selected_products: Exact product names the customer wants to preview.
                Product IDs are accepted internally, but speak and ask for names.
            source_transcript: The exact customer sentence naming the products to preview.
        """

        if not _selection_source_matches_products(source_transcript, self._last_products, selected_products):
            raise ToolError("Ask the customer to name the displayed products before generating try-ons.")

        selected_product_ids = _resolve_product_selectors(self._last_products, selected_products)
        if not selected_product_ids:
            raise ToolError("Select products by their displayed product names before generating try-ons.")

        product_by_id = {str(product["id"]): product for product in self._last_products}
        selected_product_names = [
            str(product_by_id[product_id]["name"])
            for product_id in selected_product_ids
            if product_id in product_by_id
        ]

        await _browser_rpc(
            "generateTryOns",
            {
                "imageRef": self._last_image_ref or image_ref,
                "selectedProductIds": selected_product_ids,
                "selectedProductNames": selected_product_names,
                "sourceTranscript": source_transcript,
            },
            timeout=75.0,
        )
        return _compact_tryon_response(selected_product_names)

    @function_tool(name="add_items_to_cart")
    async def add_items_to_cart(
        self,
        context: RunContext,
        products: list[str],
        source_transcript: str,
    ) -> dict[str, Any]:
        """Add selected products to the demo cart and return mock checkout details.

        Args:
            products: Exact product names the customer confirmed they want to buy.
                Product IDs are accepted internally, but speak and ask for names.
            source_transcript: The exact customer sentence naming the products to add to cart.
        """

        if hasattr(context, "disallow_interruptions"):
            context.disallow_interruptions()

        if not _selection_source_matches_products(source_transcript, self._last_products, products):
            raise ToolError("Ask the customer to name the displayed products before adding them to cart.")

        product_ids = _resolve_product_selectors(self._last_products, products)
        if not product_ids:
            raise ToolError("Select products by their displayed product names before adding to cart.")

        product_by_id = {product["id"]: product for product in self._last_products}
        new_lines = []
        for product_id in product_ids:
            product = product_by_id.get(product_id)
            new_lines.append(
                {
                    "product_id": product_id,
                    "quantity": 1,
                    "name": product["name"] if product else "Selected item",
                    "price": product["price"] if product else 0,
                }
            )

        self._cart_lines.extend(new_lines)
        await _browser_rpc(
            "addToCart",
            {
                "productIds": product_ids,
                "productNames": [line["name"] for line in new_lines],
                "lines": new_lines,
            },
            timeout=8.0,
        )
        return _compact_cart_response([line["name"] for line in new_lines])

    @function_tool(name="fill_delivery_details")
    async def fill_delivery_details(
        self,
        context: RunContext,
        recipient_name: str,
        street_address: str,
        city: str,
        state: str,
        postal_code: str,
        phone: str,
        source_transcript: str,
    ) -> dict[str, Any]:
        """Fill the visible checkout delivery form after the customer speaks their details.

        Args:
            recipient_name: Full recipient name for delivery.
            street_address: Street address and apartment or unit.
            city: Delivery city.
            state: State, region, or province.
            postal_code: Postal or ZIP code.
            phone: Contact phone number for delivery.
            source_transcript: The exact customer sentence containing the delivery details.
        """

        payload = _delivery_payload(
            recipient_name=recipient_name,
            street_address=street_address,
            city=city,
            state=state,
            postal_code=postal_code,
            phone=phone,
        )
        if not _delivery_source_matches_payload(source_transcript, payload):
            raise ToolError("Do not guess delivery details. Ask the customer for the missing delivery fields.")

        await _browser_rpc(
            "fillCheckoutDelivery",
            payload,
            timeout=8.0,
        )
        return _compact_delivery_response()


server = AgentServer()


@server.rtc_session(agent_name=AGENT_NAME)
async def style_concierge(ctx: agents.JobContext) -> None:
    session = AgentSession(
        turn_handling=_turn_handling_options(),
        llm=openai.realtime.RealtimeModel(
            model=REALTIME_MODEL,
            voice=REALTIME_VOICE,
            turn_detection=None,
        )
    )

    await session.start(
        room=ctx.room,
        agent=StyleConciergeAgent(),
        room_options=room_io.RoomOptions(video_input=True),
    )

    await session.generate_reply(
        instructions="Greet the customer cheerfully and ask whether they want hats or tshirts today."
    )


if __name__ == "__main__":
    agents.cli.run_app(server)
