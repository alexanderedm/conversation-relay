#!/bin/bash
ROOT="$(cd "$(dirname "$0")" && pwd)"
exec "$ROOT/watch_tunnel.sh"
