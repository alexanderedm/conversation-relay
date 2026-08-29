#!/bin/bash
# Keep trycloudflare alive. On death, restart and rewrite state.json.
# Hostnames CHANGE on every restart — place_call.py always re-reads state.json.
set -u
ROOT="$(cd "$(dirname "$0")" && pwd)"
PORT="${RELAY_PORT:-8765}"
LOGDIR="$ROOT/logs"
STATE="$ROOT/state.json"
if [ -n "${CLOUDFLARED:-}" ]; then
  CF="$CLOUDFLARED"
elif [ -x "$ROOT/cloudflared" ]; then
  CF="$ROOT/cloudflared"
elif command -v cloudflared >/dev/null 2>&1; then
  CF="$(command -v cloudflared)"
else
  echo "cloudflared not found. Install it, place a binary at $ROOT/cloudflared, or set CLOUDFLARED=." >&2
  exit 1
fi
mkdir -p "$LOGDIR"

write_state() {
  local host="$1"
  python3 - "$host" "$PORT" "$STATE" "$ROOT" << 'ENDSTATE'
import json, sys
from datetime import datetime, timezone
from pathlib import Path
host, port, state, root = sys.argv[1], int(sys.argv[2]), sys.argv[3], sys.argv[4]
Path(state).write_text(json.dumps({
    "local_port": port,
    "local_ws": f"http://127.0.0.1:{port}/ws",
    "public_https": f"https://{host}",
    "public_wss": f"wss://{host}/ws",
    "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "restart": f"{root}/restart.sh",
    "server_cmd": f"{root}/launch.sh",
    "tunnel_cmd": f"{root}/watch_tunnel.sh",
}, indent=2) + "\n")
print(f"public_wss=wss://{host}/ws")
print(f"local_port={port}")
ENDSTATE
}

extract_host() {
  local log="$1"
  rg -o "https://[a-zA-Z0-9.-]+\.trycloudflare\.com" "$log" 2>/dev/null | tail -n 1 | sed 's#https://##'
}

echo $$ > "$LOGDIR/watch.pid"
echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) watch_start" >> "$LOGDIR/tunnel.log"

while true; do
  RUNLOG="$LOGDIR/tunnel.current.log"
  : > "$RUNLOG"
  echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) cloudflared_spawn" >> "$LOGDIR/tunnel.log"
  "$CF" tunnel --url "http://127.0.0.1:${PORT}" --no-autoupdate >> "$RUNLOG" 2>&1 &
  CF_PID=$!
  echo "$CF_PID" > "$LOGDIR/tunnel.pid"
  HOST=""
  for i in $(seq 1 45); do
    HOST=$(extract_host "$RUNLOG" || true)
    if [ -n "$HOST" ]; then
      write_state "$HOST" | tee -a "$LOGDIR/tunnel.log"
      echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) tunnel_ready host_len=${#HOST}" >> "$LOGDIR/tunnel.log"
      break
    fi
    if ! kill -0 "$CF_PID" 2>/dev/null; then
      break
    fi
    sleep 1
  done
  if [ -z "$HOST" ]; then
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) tunnel_hostname_timeout" >> "$LOGDIR/tunnel.log"
  fi
  wait "$CF_PID" || true
  cat "$RUNLOG" >> "$LOGDIR/tunnel.log" || true
  echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) cloudflared_exit restarting" >> "$LOGDIR/tunnel.log"
  sleep 2
done
