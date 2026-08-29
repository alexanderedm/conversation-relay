#!/usr/bin/env python3
"""Zero-cost local websocket sanity check. Does not call a phone."""
import asyncio
import json
import sys
from pathlib import Path

from aiohttp import ClientSession, WSMsgType

sys.path.insert(0, str(Path(__file__).resolve().parent))
from relay_config import TRANSCRIPT_DIR

PORT = 8765


async def main() -> int:
    url = sys.argv[1] if len(sys.argv) > 1 else f"http://127.0.0.1:{PORT}/ws"
    call = "CAdummy00000000000000000000000000"
    async with ClientSession() as s:
        async with s.get(f"http://127.0.0.1:{PORT}/health") as h:
            health = await h.json()
            print(
                "health_ok=%s public_wss=%s"
                % (health.get("ok"), bool(health.get("public_wss")))
            )
        async with s.ws_connect(url, heartbeat=10) as ws:
            await ws.send_json(
                {
                    "type": "setup",
                    "sessionId": "VXdummy00000000000000000000000000",
                    "callSid": call,
                    "direction": "outbound-api",
                }
            )
            await ws.send_json(
                {
                    "type": "prompt",
                    "voicePrompt": "你好，你是誰？",
                    "lang": "cmn-TW",
                    "last": True,
                }
            )
            got = None
            try:
                msg = await asyncio.wait_for(ws.receive(), timeout=40)
            except asyncio.TimeoutError:
                print("dummy=timeout")
                return 1
            if msg.type == WSMsgType.TEXT:
                got = json.loads(msg.data)
            await ws.close()
    if not got:
        print("dummy=no-message")
        return 1
    token = str(got.get("token") or "")
    path = TRANSCRIPT_DIR / (call + ".jsonl")
    print(
        "dummy=ok type=%s last=%s reply_len=%s lang=%s jsonl=%s"
        % (got.get("type"), got.get("last"), len(token), got.get("lang"), path.exists())
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
