"""stylist.serve — OPTIONAL tiny HTTP wrapper over the 3 brain callables.

Language-agnostic calling for partners who would rather hit a local endpoint than
``import stylist`` (e.g. the LiveKit agent running in a different process/runtime).

FastAPI is **lazy-imported inside** :func:`create_app` on purpose: ``import
stylist.serve`` must succeed even when fastapi is NOT installed (the brain's hard
rule is stdlib-only inside ``/stylist``; fastapi is an optional dev extra). Nothing
at module import time touches fastapi.

Run it (after ``pip install fastapi uvicorn``):

    python3 -c "import uvicorn, stylist.serve as s; uvicorn.run(s.create_app())"

Endpoints (all POST, JSON in / JSON out):

    POST /analyze    {"image": <server-local path>, "model"?, "cassette"?}
                     -> StyleProfile.to_dict()
    POST /recommend  {"profile": <StyleProfile dict>, "n"?, "combo"?, "cassette"?}
                     -> Options.to_dict()
    POST /tryon      {"base_photo": <path>, "option_ids": [...],
                      "combo"?, "cassette"?, "critic_cassette"?}
                     -> TryOnResult.to_dict()  (status="pending"; critic runs async)
"""

from __future__ import annotations

from . import schemas
from .analyze import analyze
from .recommend import recommend
from .tryon import tryon

__all__ = ["create_app"]


def create_app():
    """Build and return the FastAPI app. ``import fastapi`` happens HERE, not at
    module load, so importing this module never requires fastapi."""
    import fastapi  # lazy — optional dependency, imported only when serving.

    app = fastapi.FastAPI(title="stylist brain", version="0.1.0")

    @app.post("/analyze")
    def _analyze(payload: dict):
        profile = analyze(
            payload["image"],
            model=payload.get("model", "gpt-5.5"),
            cassette=payload.get("cassette"),
        )
        return profile.to_dict()

    @app.post("/recommend")
    def _recommend(payload: dict):
        profile = schemas.StyleProfile.from_dict(payload["profile"])
        options = recommend(
            profile,
            n=payload.get("n", 2),
            combo=payload.get("combo", False),
            cassette=payload.get("cassette"),
        )
        return options.to_dict()

    @app.post("/tryon")
    def _tryon(payload: dict):
        result = tryon(
            payload["base_photo"],
            payload["option_ids"],
            combo=payload.get("combo", False),
            cassette=payload.get("cassette"),
            critic_cassette=payload.get("critic_cassette"),
        )
        # Synchronous result is status="pending"; the async critic settles later.
        # An HTTP caller that needs the verdict should poll a render store, not block.
        return result.to_dict()

    return app
