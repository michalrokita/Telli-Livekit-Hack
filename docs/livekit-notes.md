# LiveKit Notes

These decisions reflect the current LiveKit docs reviewed for the demo scaffold.

## Custom Frontend

Use a custom Next.js frontend instead of the hosted Agent Embed Widget. The hosted widget is great for a generic launcher and popup, but this demo needs first-class product cards, cart state, camera capture, try-on animations, and tight control over room join state. The custom app can still use LiveKit components and client SDKs, while keeping the shopping UI native to the page.

## Agent Runtime

Use a Python LiveKit Agent with `AgentSession` and `openai.realtime.RealtimeModel`.

```python
import os

from livekit.agents import AgentSession
from livekit.plugins import openai

session = AgentSession(
    llm=openai.realtime.RealtimeModel(
        model=os.environ.get("OPENAI_REALTIME_MODEL", "gpt-realtime-2"),
        voice=os.environ.get("OPENAI_REALTIME_VOICE", "marin"),
    )
)
```

Realtime speech-to-speech is the right demo default because latency and expressive voice matter more than a fully audited STT-LLM-TTS text trail. If exact scripted speech or stricter auditability becomes important, switch to a cascaded STT-LLM-TTS pipeline or a half-cascade realtime model plus separate TTS.

## Token Endpoint

Expose a web route such as `POST /api/token` that keeps LiveKit secrets server-side and returns the standardized endpoint response:

```json
{
  "server_url": "wss://your-project.livekit.cloud",
  "participant_token": "ey..."
}
```

The request body can include:

- `room_name`
- `participant_identity`
- `participant_name`
- `room_config`
- `participant_metadata`
- `participant_attributes`

Pass `room_config` through to the access token builder so agent dispatch metadata, including `LIVEKIT_AGENT_NAME`, reaches LiveKit. Add real authentication before using this outside local demo mode.

## Frontend RPC Path

Use LiveKit RPC for browser-owned shopping state that the agent should read or mutate later. Candidate methods:

- `getVisibleProducts`
- `selectProduct`
- `addToCart`
- `startTryOnAnimation`
- `captureCustomerFrame`

Register RPC methods on the frontend participant before or during room join, use JSON string payloads, keep payloads small, and set short response timeouts. This lets the agent request UI actions without duplicating cart/product/camera state in the Python process.

## References

- https://docs.livekit.io/agents/start/voice-ai.md
- https://docs.livekit.io/agents/logic/sessions.md
- https://docs.livekit.io/agents/models/realtime.md
- https://docs.livekit.io/agents/models/realtime/plugins/openai.md
- https://docs.livekit.io/frontends/build/authentication/endpoint.md
- https://docs.livekit.io/agents/logic/tools/forwarding.md
- https://docs.livekit.io/transport/data/rpc.md
