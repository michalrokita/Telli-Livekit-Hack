from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from livekit import rtc
from dotenv import load_dotenv
from livekit import agents
from livekit.agents import Agent, AgentServer, AgentSession, RunContext, ToolError, function_tool, get_job_context, room_io
from livekit.plugins import openai

from style_concierge.mock_services import (
    analyze_customer_image,
    generate_try_on_images,
    search_products,
    summarize_cart,
)


APP_DIR = Path(__file__).resolve().parents[1]
load_dotenv(APP_DIR / ".env.local")
load_dotenv(APP_DIR / ".env", override=False)

AGENT_NAME = os.getenv("AGENT_NAME") or os.getenv("LIVEKIT_AGENT_NAME") or "style-concierge"
REALTIME_MODEL = os.getenv("OPENAI_REALTIME_MODEL", "gpt-realtime-2")
REALTIME_VOICE = os.getenv("OPENAI_REALTIME_VOICE", "marin")


AGENT_INSTRUCTIONS = """
You are Style Concierge, a cheerful voice shopping assistant for a live demo.
Keep responses warm, concise, and easy to follow by voice.

Run this exact shopping flow:
1. Greet the customer cheerfully and ask whether they want to shop for hats or tshirts.
2. Ask permission to open the live camera preview before analyzing appearance.
3. After permission, call prepare_customer_camera to open the website camera preview.
   Tell the customer to say "I'm ready" when they like the frame. Do not capture yet.
4. Only after the customer says they are ready, say "Great, I'll take it now"
   and call analyze_customer_image_tool. The website tool shows the 3, 2, 1 countdown,
   captures the photo in the UI, and analyzes it.
5. Briefly explain the detected qualities:
   hair color, skin tone, undertone, contrast, palette, and practical style notes.
6. If the customer says they are not satisfied with the photo, wants to edit it, or wants a retake,
   call prepare_customer_camera again and repeat the ready/capture step before product search.
7. Call search_matching_products and recommend exactly five products with short reasons.
   Refer to products by their exact product names shown in the UI, never by handles like T1/T2/T3.
8. Ask which product names they like and wait for selected product names.
9. Call generate_customer_tryons for selected names. Explain that try-on generation can take a moment,
   and use the animated cards while the mocked image generation finishes.
10. After the try-on cards are ready, say the product names that are ready and ask which names to add.
11. When the customer chooses items to buy, call add_items_to_cart with product names.
12. The website shows an empty checkout delivery form after add_items_to_cart.
13. Immediately ask for delivery details: recipient name, street address, city, state, postal code, and phone.
   Do not wait for the customer to offer them.
14. After the customer gives delivery details, call fill_delivery_details so the website visibly fills the form.
15. Tell the customer you filled the form, ask them to review it, and point out the mock Apple Pay button.

Never claim a real purchase, payment, or image API call was made. The try-on images, inventory,
cart, and Apple Pay sheet are mocked demo payloads.

When using a tool, trust the tool to update the website UI. Do not merely describe
the UI change. Keep speaking naturally while the website shows camera capture,
analysis, products, try-ons, cart, and checkout.
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


def _delivery_details_prompt(product_names: list[str]) -> str:
    item_text = ", ".join(product_names) if product_names else "your item"
    return (
        f"Say you added {item_text} to the cart. Then ask for delivery details now: "
        "recipient name, street address, city and state, postal code, and phone number. "
        "Do not ask whether they want to provide details; ask for the details directly."
    )


def _delivery_filled_prompt() -> str:
    return (
        "Tell the customer the delivery form is filled in. Ask them to review it, "
        "then use the mock Apple Pay button when everything looks right."
    )


class StyleConciergeAgent(Agent):
    def __init__(self) -> None:
        super().__init__(instructions=AGENT_INSTRUCTIONS)
        self._last_products: list[dict[str, Any]] = []
        self._cart_lines: list[dict[str, Any]] = []
        self._camera_session_id: str | None = None

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
        return camera

    @function_tool(name="analyze_customer_image_tool")
    async def analyze_customer_image_tool(
        self,
        context: RunContext,
        image_ref: str,
        category: str,
    ) -> dict[str, Any]:
        """After the customer says they are ready, capture the photo in the website and analyze it.

        Args:
            image_ref: The camera session ID from prepare_customer_camera, or "current_camera".
            category: The category the customer chose, usually hats or tshirts.
        """

        image_ref = self._camera_session_id or image_ref
        browser_capture = await _browser_rpc(
            "captureCustomerImage",
            {"imageRef": image_ref, "category": category},
            timeout=45.0,
        )
        image_ref = str(browser_capture.get("imageRef") or image_ref)
        result = analyze_customer_image(image_ref=image_ref, category=category)
        result["browser_capture"] = browser_capture
        return result

    @function_tool(name="search_matching_products")
    async def search_matching_products(
        self,
        context: RunContext,
        category: str,
        style_goal: str,
        hair_color: str = "dark brown",
        skin_tone: str = "warm olive",
        undertone: str = "golden",
        contrast: str = "medium",
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

        self._last_products = search_products(
            category=category,
            style_goal=style_goal,
            qualities={
                "hair_color": hair_color,
                "skin_tone": skin_tone,
                "undertone": undertone,
                "contrast": contrast,
            },
        )
        await _browser_rpc(
            "showProductRecommendations",
            {
                "category": category,
                "styleGoal": style_goal,
                "products": self._last_products,
            },
            timeout=8.0,
        )
        return {
            "status": "complete",
            "count": len(self._last_products),
            "products": self._last_products,
            "selection_instruction": "Ask the customer to choose by product name, not by ID.",
        }

    @function_tool(name="generate_customer_tryons")
    async def generate_customer_tryons(
        self,
        context: RunContext,
        image_ref: str,
        selected_products: list[str],
    ) -> dict[str, Any]:
        """Generate mocked try-on previews for selected products.

        Args:
            image_ref: A reference to the customer image or current camera frame.
            selected_products: Exact product names the customer wants to preview.
                Product IDs are accepted internally, but speak and ask for names.
        """

        selected_product_ids = _resolve_product_selectors(self._last_products, selected_products)
        if not selected_product_ids:
            raise ToolError("Select products by their displayed product names before generating try-ons.")

        product_by_id = {str(product["id"]): product for product in self._last_products}
        selected_product_names = [
            str(product_by_id[product_id]["name"])
            for product_id in selected_product_ids
            if product_id in product_by_id
        ]

        await self.session.generate_reply(
            instructions=(
                "Briefly say: Great choice. I am rendering try-on previews for "
                f"{', '.join(selected_product_names)} now. Mention that the animated cards "
                "will update as the demo finishes generation."
            )
        )
        try_on_images = generate_try_on_images(image_ref, self._last_products, selected_product_ids)
        browser_tryons = await _browser_rpc(
            "generateTryOns",
            {
                "imageRef": image_ref,
                "selectedProductIds": selected_product_ids,
                "selectedProductNames": selected_product_names,
                "images": try_on_images,
            },
            timeout=25.0,
        )
        await self.session.generate_reply(
            instructions=(
                "Tell the customer the try-on previews are ready for "
                f"{', '.join(selected_product_names)}. Ask which product names they want to add to cart."
            )
        )
        return {
            "status": "complete",
            "selected_count": len(try_on_images),
            "generation_mode": "mocked_long_running_image_pipeline",
            "selected_product_names": selected_product_names,
            "images": try_on_images,
            "browser_tryons": browser_tryons,
        }

    @function_tool(name="add_items_to_cart")
    async def add_items_to_cart(
        self,
        context: RunContext,
        products: list[str],
    ) -> dict[str, Any]:
        """Add selected products to the demo cart and return mock checkout details.

        Args:
            products: Exact product names the customer confirmed they want to buy.
                Product IDs are accepted internally, but speak and ask for names.
        """

        if hasattr(context, "disallow_interruptions"):
            context.disallow_interruptions()

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
        browser_cart = await _browser_rpc(
            "addToCart",
            {
                "productIds": product_ids,
                "productNames": [line["name"] for line in new_lines],
                "lines": new_lines,
            },
            timeout=8.0,
        )
        summary = summarize_cart(new_lines)
        summary["cart_total"] = summarize_cart(self._cart_lines)
        summary["mutation"] = "items_added"
        summary["browser_cart"] = browser_cart
        await self.session.generate_reply(
            instructions=_delivery_details_prompt([line["name"] for line in new_lines])
        )
        return summary

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
    ) -> dict[str, Any]:
        """Fill the visible checkout delivery form after the customer speaks their details.

        Args:
            recipient_name: Full recipient name for delivery.
            street_address: Street address and apartment or unit.
            city: Delivery city.
            state: State, region, or province.
            postal_code: Postal or ZIP code.
            phone: Contact phone number for delivery.
        """

        payload = _delivery_payload(
            recipient_name=recipient_name,
            street_address=street_address,
            city=city,
            state=state,
            postal_code=postal_code,
            phone=phone,
        )
        browser_delivery = await _browser_rpc(
            "fillCheckoutDelivery",
            payload,
            timeout=8.0,
        )
        await self.session.generate_reply(instructions=_delivery_filled_prompt())
        return {
            "status": "delivery_details_filled",
            "delivery": payload,
            "browser_delivery": browser_delivery,
        }


server = AgentServer()


@server.rtc_session(agent_name=AGENT_NAME)
async def style_concierge(ctx: agents.JobContext) -> None:
    session = AgentSession(
        llm=openai.realtime.RealtimeModel(
            model=REALTIME_MODEL,
            voice=REALTIME_VOICE,
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
