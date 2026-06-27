"""stylist — the LiveKit-free inference brain of the AI voice stylist.

Pure, stateless styling intelligence for the telli x LiveKit hackathon:
analyze a photo into a StyleProfile, recommend rule-constrained hat / t-shirt
options with a stylist rationale, and render identity-preserving try-on images
verified by a critic. ZERO LiveKit imports — the partner's voice agent imports
this package and calls it as plain functions.

The partner seam is exactly three callables + the data contract:

    from stylist import analyze, recommend, tryon, schemas

    profile = analyze(frame)                 # StyleProfile
    options = recommend(profile)             # Options  (combo=True for outfits)
    result  = tryon(photo, ["HAT-CAP-002"])  # TryOnResult (status="pending", async critic)

The data contract lives in ``stylist.schemas``; live model calls go through
``stylist._openai`` (record/replay, httpx-based) and happen only INSIDE the
functions — importing this package triggers no network. The partner handover is
``SEAM.md`` at the repo root.
"""

from . import schemas
from .analyze import analyze
from .recommend import recommend
from .tryon import tryon

__all__ = ["analyze", "recommend", "tryon", "schemas"]
__version__ = "0.1.0"
