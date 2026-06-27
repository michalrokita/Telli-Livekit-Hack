# Style Concierge Agent

LiveKit realtime voice worker for the Telli Hack shopping demo.

## Run

```bash
uv sync
cp .env.example .env.local
uv run src/agent.py dev
```

The worker defaults to agent name `style-concierge`, OpenAI realtime model
`gpt-realtime-2`, and voice `marin`. Override with `AGENT_NAME`,
`OPENAI_REALTIME_MODEL`, and `OPENAI_REALTIME_VOICE`.

## Test

```bash
uv run pytest
```

Mock product, try-on, cart, and checkout services are deterministic and do not
require credentials.
