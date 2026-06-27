"""stylist._openai — shared OpenAI HTTP wrapper with record/replay.

Uses ``httpx`` (imported LAZILY inside the live-call branch) — never the ``openai``
SDK — so ``import stylist._openai`` succeeds even if httpx is absent. Tests and
offline development run entirely from cassettes; live calls happen only when
``STYLIST_LIVE=1``.

Environment:
  * ``OPENAI_API_KEY`` — required for live calls; read only inside the live branch.
  * ``STYLIST_LIVE=1``  — enable real network calls (default: replay from cassette).
  * ``STYLIST_RECORD=1`` — when live, persist the result to a cassette.

Cassettes live in ``stylist/tests/fixtures/cassettes/``:
  * chat / vision  -> ``<name>.json`` (the parsed JSON object the model returned)
  * image edits    -> ``<name>.png``  (the raw rendered PNG bytes)

The API key is never printed, logged, or written to a cassette.
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path

CASSETTE_DIR = Path(__file__).resolve().parent / "tests" / "fixtures" / "cassettes"

_CHAT_URL = "https://api.openai.com/v1/chat/completions"
_IMAGE_EDIT_URL = "https://api.openai.com/v1/images/edits"
_CHAT_TIMEOUT_S = 120.0
_IMAGE_TIMEOUT_S = 300.0


class OpenAIError(Exception):
    """Any failure talking to (or standing in for) the OpenAI API."""


class OpenAIReplayError(OpenAIError):
    """Replay was requested but the needed cassette is missing."""


# --------------------------------------------------------------------------- #
# Environment / mode helpers                                                   #
# --------------------------------------------------------------------------- #
def _live() -> bool:
    return os.environ.get("STYLIST_LIVE") == "1"


def _record() -> bool:
    return os.environ.get("STYLIST_RECORD") == "1"


def _require_key() -> str:
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise OpenAIError(
            "OPENAI_API_KEY is not set, but a live call was requested (STYLIST_LIVE=1)."
        )
    return key


def _cassette_path(name: str, ext: str) -> Path:
    return CASSETTE_DIR / f"{name}.{ext}"


# --------------------------------------------------------------------------- #
# Image helpers (pure, no network)                                            #
# --------------------------------------------------------------------------- #
def load_image_bytes(image) -> bytes:
    """Return raw bytes for ``image`` given a filesystem path (str/PathLike) or bytes."""
    if isinstance(image, (bytes, bytearray)):
        return bytes(image)
    if isinstance(image, (str, os.PathLike)):
        with open(image, "rb") as fh:
            return fh.read()
    raise OpenAIError(
        f"unsupported image type {type(image).__name__!r}; expected a path or bytes"
    )


def encode_image_b64(image) -> str:
    """Base64-encode ``image`` (path or bytes) with NO ``data:`` prefix."""
    return base64.b64encode(load_image_bytes(image)).decode("ascii")


# --------------------------------------------------------------------------- #
# Cassette read/write                                                          #
# --------------------------------------------------------------------------- #
def _replay_json(cassette: str | None) -> dict:
    if cassette is None:
        raise OpenAIReplayError(
            "replay mode (STYLIST_LIVE unset) but no cassette name was given; cannot replay."
        )
    path = _cassette_path(cassette, "json")
    if not path.exists():
        raise OpenAIReplayError(
            f"cassette not found: {path} "
            f"(set STYLIST_LIVE=1 to make a live call, plus STYLIST_RECORD=1 to record it)."
        )
    return json.loads(path.read_text())


def _write_json(cassette: str | None, obj: dict) -> None:
    if cassette is None:
        return
    path = _cassette_path(cassette, "json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False))


def _replay_png(cassette: str | None) -> bytes:
    if cassette is None:
        raise OpenAIReplayError(
            "replay mode (STYLIST_LIVE unset) but no cassette name was given for an image edit."
        )
    path = _cassette_path(cassette, "png")
    if not path.exists():
        raise OpenAIReplayError(
            f"image cassette not found: {path} "
            f"(set STYLIST_LIVE=1 + STYLIST_RECORD=1 to record it)."
        )
    return path.read_bytes()


def _write_png(cassette: str | None, png: bytes) -> None:
    if cassette is None:
        return
    path = _cassette_path(cassette, "png")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png)


# --------------------------------------------------------------------------- #
# Chat / vision                                                                #
# --------------------------------------------------------------------------- #
def complete_json(
    *,
    system: str,
    user_content,
    model: str = "gpt-5.4-mini",
    cassette: str | None = None,
    max_retries: int = 1,
    max_output_tokens: int | None = None,
) -> dict:
    """Chat Completions returning a parsed JSON object.

    ``user_content`` may be a plain string or a list of OpenAI content parts
    (text + image_url parts) — it is passed straight through. On a JSON parse
    failure of the model output the call is retried ``max_retries`` times
    (default 1 -> max 2 attempts, anti-loop), then ``OpenAIError`` is raised.

    ``model`` defaults to the fast ``gpt-5.4-mini`` tier; pass ``gpt-5.5`` for the
    capability-critical vision reads (analyze, catalog enrich). ``max_output_tokens``
    is sent as ``max_completion_tokens`` — gpt-5.x rejects the legacy ``max_tokens``.
    """
    if not _live():
        return _replay_json(cassette)

    import httpx  # lazy: keeps `import stylist._openai` dependency-free

    api_key = _require_key()
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_content},
        ],
        "response_format": {"type": "json_object"},
    }
    if max_output_tokens is not None:
        payload["max_completion_tokens"] = max_output_tokens
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    attempts = max(1, max_retries + 1)
    last_parse_err: Exception | None = None
    with httpx.Client(timeout=_CHAT_TIMEOUT_S) as client:
        for _ in range(attempts):
            resp = client.post(_CHAT_URL, headers=headers, json=payload)
            if resp.status_code != 200:
                raise OpenAIError(
                    f"chat completions failed: HTTP {resp.status_code}: {resp.text[:500]}"
                )
            try:
                content = resp.json()["choices"][0]["message"]["content"]
                parsed = json.loads(content)
            except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
                last_parse_err = exc
                continue
            if _record():
                _write_json(cassette, parsed)
            return parsed

    raise OpenAIError(
        f"model did not return valid JSON after {attempts} attempt(s): {last_parse_err}"
    )


def vision_json(
    *,
    system: str,
    user_text: str,
    image,
    model: str = "gpt-5.4-mini",
    cassette: str | None = None,
    max_output_tokens: int | None = None,
) -> dict:
    """Convenience wrapper: attach one image to a text prompt and call ``complete_json``."""
    b64 = encode_image_b64(image)
    user_content = [
        {"type": "text", "text": user_text},
        {
            "type": "image_url",
            "image_url": {"url": "data:image/png;base64," + b64},
        },
    ]
    return complete_json(
        system=system,
        user_content=user_content,
        model=model,
        cassette=cassette,
        max_output_tokens=max_output_tokens,
    )


# --------------------------------------------------------------------------- #
# Image edit (gpt-image-2)                                                     #
# --------------------------------------------------------------------------- #
def edit_image(
    *,
    base_image,
    prompt: str,
    mask=None,
    reference_images=None,
    model: str = "gpt-image-2",
    size: str = "1024x1024",
    cassette: str | None = None,
) -> bytes:
    """Identity-preserving image edit -> PNG bytes.

    ``base_image`` (+ any ``reference_images``) are sent as ``image[]`` inputs;
    an optional ``mask`` locks everything outside the edit region. Returns the
    decoded PNG from ``data[0].b64_json``.
    """
    if not _live():
        return _replay_png(cassette)

    import httpx  # lazy

    api_key = _require_key()
    files = [("image[]", ("base.png", load_image_bytes(base_image), "image/png"))]
    if reference_images:
        for i, ref in enumerate(reference_images):
            files.append(("image[]", (f"ref{i}.png", load_image_bytes(ref), "image/png")))
    if mask is not None:
        files.append(("mask", ("mask.png", load_image_bytes(mask), "image/png")))

    data = {"prompt": prompt, "model": model, "size": size}
    headers = {"Authorization": f"Bearer {api_key}"}

    with httpx.Client(timeout=_IMAGE_TIMEOUT_S) as client:
        resp = client.post(_IMAGE_EDIT_URL, headers=headers, data=data, files=files)
    if resp.status_code != 200:
        raise OpenAIError(
            f"image edit failed: HTTP {resp.status_code}: {resp.text[:500]}"
        )
    try:
        b64png = resp.json()["data"][0]["b64_json"]
        png = base64.b64decode(b64png)
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise OpenAIError(f"image edit response missing b64 PNG data: {exc}") from exc

    if _record():
        _write_png(cassette, png)
    return png
