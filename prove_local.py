#!/usr/bin/env python3
"""Local proofs. Never places a live call. Never reads hardcoded secret paths."""
from __future__ import annotations

import ast
import asyncio
import os
import socket
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from aiohttp import ClientSession, FormData

sys.path.insert(0, str(Path(__file__).resolve().parent))
from relay_config import RECORD_DIR, ROOT, TRANSCRIPT_DIR

# Minimal MPEG-ish bytes; Twilio would send a real mp3. Size > 0 is enough.
SAMPLE_MP3 = b"\xff\xfb\x90\x00" + b"\x00" * 256


def syntax_check() -> None:
    for name in (
        "app.py",
        "place_call.py",
        "print_payload.py",
        "relay_config.py",
        "server.py",
        "dummy_ws_check.py",
    ):
        ast.parse((ROOT / name).read_text(encoding="utf-8"))
        print("syntax=pass file=" + name)


async def health_check() -> dict:
    async with ClientSession() as s:
        async with s.get("http://127.0.0.1:8765/health") as resp:
            data = await resp.json()
            print(
                "health=pass ok=%s wss=%s https=%s"
                % (data.get("ok"), bool(data.get("public_wss")), bool(data.get("public_https")))
            )
            return data


async def recording_mock() -> None:
    call = "CAprove00000000000000000000000000"
    rec = "REprove00000000000000000000000000"
    dest = RECORD_DIR / (call + ".mp3")
    if dest.exists():
        dest.unlink()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path.endswith(".mp3") or self.path == "/sample":
                body = SAMPLE_MP3
                self.send_response(200)
                self.send_header("Content-Type", "audio/mpeg")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_error(404)

        def log_message(self, *_args):
            return

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    httpd = HTTPServer(("127.0.0.1", port), Handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    rec_url = f"http://127.0.0.1:{port}/sample"
    form = FormData()
    form.add_field("RecordingSid", rec)
    form.add_field("RecordingUrl", rec_url)
    form.add_field("RecordingStatus", "completed")
    form.add_field("CallSid", call)
    async with ClientSession() as s:
        async with s.post("http://127.0.0.1:8765/recording_status", data=form) as resp:
            code = resp.status
    httpd.shutdown()
    if code != 200:
        print("recording_mock=fail http=%s" % code)
        raise SystemExit(1)
    if not dest.exists() or dest.stat().st_size <= 0:
        print("recording_mock=fail missing_file path=%s" % dest)
        raise SystemExit(1)
    print("recording_mock=pass bytes=%s path=%s" % (dest.stat().st_size, dest))


async def main() -> int:
    os.chdir(ROOT)
    syntax_check()
    await health_check()
    await recording_mock()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
