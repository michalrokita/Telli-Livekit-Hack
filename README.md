# Telli Hack

LiveKit voice shopping demo scaffold: a custom Next.js storefront paired with a Python LiveKit Agent for an animated personal-shopper flow.

## Quick Demo Run

Install the two runtimes:

```sh
pnpm install
cd apps/agent
uv sync
```

Create app-local env files from the root template:

```sh
cp .env.example apps/web/.env.local
cp .env.example apps/agent/.env.local
```

Run the web app and agent in separate terminals:

```sh
pnpm dev:web
```

```sh
cd apps/agent
uv run src/agent.py dev
```

The helper script prints the same commands with the resolved project path:

```sh
bash scripts/dev.sh
```

## Real LiveKit + OpenAI Setup

1. Create or choose a LiveKit Cloud project at `cloud.livekit.io`.
2. Put `LIVEKIT_URL`, `LIVEKIT_API_KEY`, and `LIVEKIT_API_SECRET` in both app-local env files.
3. Put the same WebSocket URL in `NEXT_PUBLIC_LIVEKIT_URL` in `apps/web/.env.local`; it is public and lets the browser enter real voice mode.
4. Put `OPENAI_API_KEY`, `OPENAI_REALTIME_MODEL`, and `OPENAI_REALTIME_VOICE` in `apps/agent/.env.local`.
5. Keep the LiveKit API secret server-side only. The web app requests a short-lived room token from its `/api/token` route.
6. Start the Python agent in `dev` mode, then open the Next.js app and join a demo room.

## Environment Variables

The root [.env.example](.env.example) is the shared checklist. Copy it into:

- `apps/web/.env.local` for the Next.js token route and public demo defaults.
- `apps/agent/.env.local` for LiveKit worker connection and OpenAI realtime model settings.

Important variables:

- `LIVEKIT_URL`: LiveKit Cloud WebSocket URL, for example `wss://project.livekit.cloud`.
- `LIVEKIT_API_KEY` / `LIVEKIT_API_SECRET`: server-side token signing and agent worker credentials.
- `LIVEKIT_AGENT_NAME`: agent dispatch name used by the token route and Python worker.
- `NEXT_PUBLIC_LIVEKIT_URL`: the same WebSocket URL, exposed to the browser so the chat can connect.
- `OPENAI_API_KEY`: required by the LiveKit OpenAI realtime plugin.
- `OPENAI_REALTIME_MODEL` / `OPENAI_REALTIME_VOICE`: realtime model and voice used by the shopping assistant.

## Commands

```sh
pnpm dev:web        # Next.js storefront
pnpm build          # web production build
pnpm test:web       # web helper tests
pnpm test:agent     # Python mock-service tests
pnpm test           # web + agent tests
bash scripts/dev.sh # print demo run commands
```

## Architecture

- `apps/web`: custom Next.js shopping UI. It owns product cards, cart state, camera capture, try-on animation, and the `/api/token` endpoint that returns LiveKit connection credentials.
- `apps/agent`: Python LiveKit Agent. The intended runtime is `AgentSession` with `openai.realtime.RealtimeModel` for low-latency speech-to-speech shopping help.
- LiveKit room: the browser joins with a short-lived token, publishes mic/camera tracks, and receives agent audio/transcript events.
- Token route: signs a room token with `room_config` so LiveKit can dispatch the configured agent into the room.
- Future frontend RPC: product selection, cart changes, and animation triggers can move through LiveKit RPC so the agent can act on UI state without owning browser-only data.

See [docs/livekit-notes.md](docs/livekit-notes.md) for the LiveKit-specific decisions behind this scaffold.
