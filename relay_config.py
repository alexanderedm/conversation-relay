#!/usr/bin/env python3
"""Shared ConversationRelay defaults. No secrets.

Credentials and phone numbers come from the process environment, then
optional local files (.env / credentials.env in this repo). Both files
are gitignored.
"""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
STATE_PATH = ROOT / "state.json"
LOG_DIR = ROOT / "logs"
TRANSCRIPT_DIR = ROOT / "transcripts"
RECORD_DIR = ROOT / "recordings"

_ENV_FILES = (
    ROOT / ".env",
    ROOT / "credentials.env",
)


def apply_env_files() -> None:
    """Load KEY=VALUE from local files into os.environ if the key is unset."""
    for path in _ENV_FILES:
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


def load_twilio_vals() -> dict[str, str]:
    apply_env_files()
    keys = (
        "TWILIO_ACCOUNT_SID",
        "TWILIO_AUTH_TOKEN",
        "TWILIO_FROM_NUMBER",
        "TWILIO_TO_NUMBER",
    )
    return {k: (os.environ.get(k) or "").strip() for k in keys}


apply_env_files()

# TTS: Google cmn-TW (leading <Say> + ConversationRelay ttsLanguage).
# STT: do NOT use Google + cmn-TW + long — Twilio 64101
#   "Invalid values (google/cmn-TW/long) for transcription settings".
# Listen uses the combo that already worked: Google en-US telephony.
LANGUAGE = "cmn-TW"
TTS_LANGUAGE = "cmn-TW"
TRANSCRIPTION_LANGUAGE = "en-US"
TTS_PROVIDER = "Google"
VOICE = "cmn-TW-Standard-A"
SAY_VOICE = "Google.cmn-TW-Standard-A"
TRANSCRIPTION_PROVIDER = "Google"
SPEECH_MODEL = "telephony"
EN_LANGUAGE = "en-US"
EN_VOICE = "en-US-Journey-O"
EN_SPEECH_MODEL = "telephony"

WELCOME = "您好。"
SAY_FALLBACK = "Office audio check."
HINTS = "助理"

DEFAULT_TO = (os.environ.get("TWILIO_TO_NUMBER") or "").strip()
DEFAULT_FROM = (os.environ.get("TWILIO_FROM_NUMBER") or "").strip()
CREDS = ROOT / "credentials.env"
