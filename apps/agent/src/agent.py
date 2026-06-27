from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from livekit import agents
from livekit.agents import Agent, AgentServer, AgentSession, RunContext, function_tool, room_io
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
2. Ask permission to use a picture or live camera frame before analyzing appearance.
3. After permission, call analyze_customer_image_tool and briefly explain the detected qualities:
   hair color, skin tone, undertone, contrast, palette, and practical style notes.
4. Call search_matching_products and recommend exactly five products with short reasons.
5. Ask which products they like and wait for selected product IDs or names.
6. Call generate_customer_tryons for selected items. Explain that try-on generation can take a moment,
   and use the payload status and preview URLs as mocked demo results.
7. When the customer chooses items to buy, call add_items_to_cart.
8. Ask for delivery details: recipient name, street address, city, state, postal code, and phone.
9. Show the mock Apple Pay checkout from the cart payload and ask the customer to confirm.

Never claim a real purchase, payment, or image API call was made. The try-on images, inventory,
cart, and Apple Pay sheet are mocked demo payloads.
""".strip()


class StyleConciergeAgent(Agent):
    def __init__(self) -> None:
        super().__init__(instructions=AGENT_INSTRUCTIONS)
        self._last_products: list[dict[str, Any]] = []
        self._cart_lines: list[dict[str, Any]] = []

    @function_tool(name="analyze_customer_image_tool")
    async def analyze_customer_image_tool(
        self,
        context: RunContext,
        image_ref: str,
        category: str,
    ) -> dict[str, Any]:
        """Analyze the customer's permitted picture for styling qualities.

        Args:
            image_ref: A reference to the customer image or current camera frame.
            category: The category the customer chose, usually hats or tshirts.
        """

        return analyze_customer_image(image_ref=image_ref, category=category)

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
        return {
            "status": "complete",
            "count": len(self._last_products),
            "products": self._last_products,
        }

    @function_tool(name="generate_customer_tryons")
    async def generate_customer_tryons(
        self,
        context: RunContext,
        image_ref: str,
        selected_product_ids: list[str],
    ) -> dict[str, Any]:
        """Generate mocked try-on previews for selected products.

        Args:
            image_ref: A reference to the customer image or current camera frame.
            selected_product_ids: Product IDs the customer wants to preview.
        """

        await self.session.generate_reply(
            instructions=(
                "Briefly tell the customer their try-on previews are being prepared "
                "and that the animated cards will update as the demo finishes generation."
            )
        )
        try_on_images = generate_try_on_images(image_ref, self._last_products, selected_product_ids)
        return {
            "status": "complete",
            "selected_count": len(try_on_images),
            "generation_mode": "mocked_long_running_image_pipeline",
            "images": try_on_images,
        }

    @function_tool(name="add_items_to_cart")
    async def add_items_to_cart(
        self,
        context: RunContext,
        product_ids: list[str],
    ) -> dict[str, Any]:
        """Add selected products to the demo cart and return mock checkout details.

        Args:
            product_ids: Product IDs the customer confirmed they want to buy.
        """

        if hasattr(context, "disallow_interruptions"):
            context.disallow_interruptions()

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
        summary = summarize_cart(new_lines)
        summary["cart_total"] = summarize_cart(self._cart_lines)
        summary["mutation"] = "items_added"
        return summary


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
