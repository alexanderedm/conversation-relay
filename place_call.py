#!/usr/bin/env python3
"""Place an outbound ConversationRelay test call. Does not run unless invoked.

Safety: refuses to place a live call unless RELAY_PLACE_CALL=1.
Always re-reads state.json immediately before creating the call.
Refuses if TWILIO_TO_NUMBER or TWILIO_FROM_NUMBER is missing.

Usage (preview only — no call):
  python3 place_call.py --print-only

Usage (live call — only when you intend to dial):
  RELAY_PLACE_CALL=1 python3 place_call.py

Fetch an existing recording (no new call):
  python3 place_call.py --fetch-recording CA...
"""
from __future__ import annotations

import argparse
import html
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from relay_config import (
    DEFAULT_FROM,
    DEFAULT_TO,
    EN_LANGUAGE,
    EN_SPEECH_MODEL,
    EN_VOICE,
    HINTS,
    LANGUAGE,
    SAY_FALLBACK,
    SAY_VOICE,
    SPEECH_MODEL,
    STATE_PATH,
    TRANSCRIPTION_LANGUAGE,
    TRANSCRIPTION_PROVIDER,
    TTS_LANGUAGE,
    TTS_PROVIDER,
    VOICE,
    WELCOME,
    apply_env_files,
    load_twilio_vals,
)

apply_env_files()


def read_state() -> dict:
    if not STATE_PATH.exists():
        raise SystemExit("missing state.json — start the tunnel first (or copy state.example.json)")
    data = json.loads(STATE_PATH.read_text())
    if not isinstance(data, dict):
        raise SystemExit("state.json is not an object")
    return data


def public_wss() -> str:
    url = (read_state().get("public_wss") or "").strip()
    if not url.startswith("wss://"):
        raise SystemExit("state.json has no public_wss")
    return url


def public_https() -> str:
    return (read_state().get("public_https") or "").rstrip("/")


def action_url() -> str:
    base = public_https()
    if not base.startswith("https://"):
        raise SystemExit("state.json has no public_https")
    return base + "/connect_action"


def recording_callback_url() -> str:
    return public_https() + "/recording_status"


def dest_numbers() -> tuple[str, str]:
    vals = load_twilio_vals()
    to_num = (vals.get("TWILIO_TO_NUMBER") or DEFAULT_TO or "").strip()
    from_num = (vals.get("TWILIO_FROM_NUMBER") or DEFAULT_FROM or "").strip()
    return to_num, from_num


def require_numbers() -> tuple[str, str]:
    to_num, from_num = dest_numbers()
    if not to_num or not from_num:
        raise SystemExit(
            "TWILIO_TO_NUMBER and TWILIO_FROM_NUMBER must be set "
            "(env, .env, or credentials.env). No default numbers."
        )
    return to_num, from_num


def twiml_for(wss: str | None = None) -> str:
    url = html.escape(wss or public_wss(), quote=True)
    greet = html.escape(WELCOME, quote=True)
    say = html.escape(SAY_FALLBACK, quote=True)
    action = html.escape(action_url(), quote=True)
    hints = html.escape(HINTS, quote=True)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response>"
        f'<Say language="{LANGUAGE}" voice="{SAY_VOICE}">{say}</Say>'
        f'<Connect action="{action}">'
        f'<ConversationRelay url="{url}" '
        f'welcomeGreeting="{greet}" '
        f'language="{TRANSCRIPTION_LANGUAGE}" '
        f'ttsLanguage="{TTS_LANGUAGE}" '
        f'transcriptionLanguage="{TRANSCRIPTION_LANGUAGE}" '
        f'ttsProvider="{TTS_PROVIDER}" '
        f'voice="{VOICE}" '
        f'transcriptionProvider="{TRANSCRIPTION_PROVIDER}" '
        f'speechModel="{SPEECH_MODEL}" '
        'interruptible="any" '
        'debug="debugging" '
        'events="speaker-events tokens-played" '
        f'hints="{hints}">'
        f'<Language code="{LANGUAGE}" ttsProvider="{TTS_PROVIDER}" '
        f'voice="{VOICE}"/>'
        f'<Language code="{EN_LANGUAGE}" ttsProvider="{TTS_PROVIDER}" '
        f'voice="{EN_VOICE}" transcriptionProvider="{TRANSCRIPTION_PROVIDER}" '
        f'speechModel="{SPEECH_MODEL}"/>'
        "</ConversationRelay>"
        "</Connect>"
        "</Response>"
    )


def fetch_recording(call_sid: str) -> int:
    """Poll Twilio Recordings API for an existing call. Does not place a call."""
    from app import download_recording, poll_twilio_recording, recording_path

    print("fetch_mode=poll")
    print("call=" + call_sid[:10])
    dest = recording_path(call_sid)
    print("dest=" + str(dest))
    found = poll_twilio_recording(call_sid)
    if not found:
        print("result=empty")
        print("note=no recording SID on this call; callback-miss poll path executed")
        return 0
    rec_sid, media = found
    print("rec=" + rec_sid[:10])
    import asyncio

    async def _go() -> None:
        from aiohttp import ClientSession
        import app as ap

        ap.HTTP = ClientSession()
        try:
            saved = await download_recording(call_sid, media, rec_sid)
            print("saved=" + ("yes" if saved else "no"))
            if saved:
                print("bytes=" + str(saved.stat().st_size))
                print("path=" + str(saved))
        finally:
            await ap.HTTP.close()
            ap.HTTP = None

    asyncio.run(_go())
    return 0


def place_call() -> int:
    if os.environ.get("RELAY_PLACE_CALL") != "1":
        print("refusing live call: set RELAY_PLACE_CALL=1 to allow dialing", file=sys.stderr)
        return 2
    from twilio.rest import Client

    vals = load_twilio_vals()
    sid = vals.get("TWILIO_ACCOUNT_SID") or ""
    token = vals.get("TWILIO_AUTH_TOKEN") or ""
    if not sid or not token:
        print("refusing: TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN must be set", file=sys.stderr)
        return 2
    to_num, from_num = require_numbers()
    wss = public_wss()
    twiml = twiml_for(wss)
    client = Client(sid, token)
    rec_cb = recording_callback_url()
    call = client.calls.create(
        to=to_num,
        from_=from_num,
        twiml=twiml,
        record=True,
        recording_channels="dual",
        recording_status_callback=rec_cb,
        recording_status_callback_event=["completed"],
    )
    print("record=true")
    print("sid=" + call.sid)
    print("status=" + str(call.status))
    print("to=" + str(call.to))
    print("from_num=" + str(getattr(call, "from_formatted", "") or ""))
    print("wss_host_len=" + str(len(wss)))
    print("language=" + LANGUAGE)
    print("voice=" + VOICE)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="ConversationRelay call helper")
    parser.add_argument("--print-only", action="store_true", help="print TwiML from latest state.json")
    parser.add_argument("--fetch-recording", metavar="CALL_SID", help="poll/download an existing recording")
    args = parser.parse_args()
    if args.fetch_recording:
        return fetch_recording(args.fetch_recording)
    if args.print_only:
        wss = public_wss()
        to_num, from_num = dest_numbers()
        print("to=" + (to_num or "(unset)"))
        print("from=" + (from_num or "(unset)"))
        print("public_wss=" + wss)
        print("public_https=" + public_https())
        print("twiml=" + twiml_for(wss))
        print("language=" + TRANSCRIPTION_LANGUAGE)
        print("ttsLanguage=" + TTS_LANGUAGE)
        print("transcriptionLanguage=" + TRANSCRIPTION_LANGUAGE)
        print("ttsProvider=" + TTS_PROVIDER)
        print("voice=" + VOICE)
        print("transcriptionProvider=" + TRANSCRIPTION_PROVIDER)
        print("speechModel=" + SPEECH_MODEL)
        print("record=true")
        return 0
    return place_call()


if __name__ == "__main__":
    raise SystemExit(main())
