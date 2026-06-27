#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
WEB_CMD="pnpm dev:web"
AGENT_CMD="cd apps/agent && uv run src/agent.py dev"

print_help() {
  cat <<EOF
Telli Hack demo runner

Default mode prints the commands to run in separate terminals.

Usage:
  bash scripts/dev.sh          Print web + agent commands
  bash scripts/dev.sh --web    Run the Next.js web app
  bash scripts/dev.sh --agent  Run the LiveKit Python agent
  bash scripts/dev.sh --check  Check expected local env files

Commands:
  cd "$ROOT" && $WEB_CMD
  cd "$ROOT" && $AGENT_CMD
EOF
}

check_env() {
  missing=0

  if [ ! -f "$ROOT/apps/web/.env.local" ]; then
    echo "Missing apps/web/.env.local; copy .env.example there for the token route."
    missing=1
  fi

  if [ ! -f "$ROOT/apps/agent/.env.local" ]; then
    echo "Missing apps/agent/.env.local; copy .env.example there for the agent."
    missing=1
  fi

  if [ "$missing" -eq 0 ]; then
    echo "Env files are present."
  fi

  return "$missing"
}

case "${1:-}" in
  ""|--print)
    print_help
    ;;
  --web)
    cd "$ROOT"
    exec pnpm dev:web
    ;;
  --agent)
    cd "$ROOT/apps/agent"
    exec uv run src/agent.py dev
    ;;
  --check)
    check_env
    ;;
  -h|--help)
    print_help
    ;;
  *)
    echo "Unknown option: $1" >&2
    print_help >&2
    exit 2
    ;;
esac
