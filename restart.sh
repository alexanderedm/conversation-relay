#!/bin/bash
# Restart the local ConversationRelay server + self-healing Cloudflare tunnel.
# After restart, a NEW trycloudflare hostname is issued; state.json is rewritten.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
PORT="${RELAY_PORT:-8765}"
LOGDIR="$ROOT/logs"
STATE="$ROOT/state.json"
mkdir -p "$LOGDIR"

# Kill prior workers only (not this script).
pkill -f "$ROOT/app.py" 2>/dev/null || true
pkill -f "$ROOT/server.py" 2>/dev/null || true
pkill -f "$ROOT/launch.sh" 2>/dev/null || true
pkill -f "$ROOT/watch_tunnel.sh" 2>/dev/null || true
pkill -f "$ROOT/launch_tunnel.sh" 2>/dev/null || true
pkill -f "cloudflared tunnel --url http://127.0.0.1:${PORT}" 2>/dev/null || true
sleep 1

: > "$LOGDIR/server.log"
: > "$LOGDIR/tunnel.log"
: > "$LOGDIR/tunnel.current.log"

# Invalidate stale public URLs so we wait for a real rewrite.
python3 - "$STATE" "$PORT" "$ROOT" << 'ENDSTATE'
import json, sys
from pathlib import Path
state, port, root = sys.argv[1], int(sys.argv[2]), sys.argv[3]
Path(state).write_text(json.dumps({
    "local_port": port,
    "local_ws": f"http://127.0.0.1:{port}/ws",
    "public_https": "",
    "public_wss": "",
    "updated_at": "",
    "pending": True,
    "restart": f"{root}/restart.sh",
    "server_cmd": f"{root}/launch.sh",
    "tunnel_cmd": f"{root}/watch_tunnel.sh",
}, indent=2) + "\n")
ENDSTATE

nohup "$ROOT/launch.sh" >> "$LOGDIR/server.log" 2>&1 &
echo $! > "$LOGDIR/server.pid"

nohup "$ROOT/watch_tunnel.sh" >> "$LOGDIR/watch.stdout.log" 2>&1 &
echo $! > "$LOGDIR/watch.pid"

HOST=""
for i in $(seq 1 50); do
  if [ -f "$STATE" ]; then
    HOST=$(python3 - "$STATE" << 'ENDHOST'
import json, sys
from pathlib import Path
p = Path(sys.argv[1])
try:
    data = json.loads(p.read_text())
except Exception:
    data = {}
wss = (data.get("public_wss") or "").strip()
if wss.startswith("wss://") and not data.get("pending"):
    print(wss.replace("wss://", "").split("/")[0])
else:
    print("")
ENDHOST
)
  fi
  if [ -n "$HOST" ]; then
    if curl -fsS "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1; then
      echo "public_wss=wss://${HOST}/ws"
      echo "local_port=${PORT}"
      echo "state=$STATE"
      exit 0
    fi
  fi
  sleep 1
done

echo "tunnel/server not ready; see $LOGDIR/server.log and $LOGDIR/tunnel.log" >&2
exit 1
