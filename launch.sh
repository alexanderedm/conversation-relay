#!/bin/bash
# Start the local ConversationRelay HTTP/websocket server.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
export RELAY_PORT="${RELAY_PORT:-8765}"
export RELAY_HOST="${RELAY_HOST:-127.0.0.1}"
export PYTHONPATH="${ROOT}${PYTHONPATH:+:$PYTHONPATH}"
exec python3 "$ROOT/app.py"
