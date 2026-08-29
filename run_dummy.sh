#!/bin/bash
# Local websocket check. Does not call a phone.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
export PYTHONPATH="${ROOT}${PYTHONPATH:+:$PYTHONPATH}"
exec python3 "$ROOT/dummy_ws_check.py" "$@"
