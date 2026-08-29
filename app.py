#!/usr/bin/env python3
"""Twilio ConversationRelay websocket server + MiniMax replies.

Logs high-level events only. Never logs API keys, tokens, or Authorization headers.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any

from aiohttp import BasicAuth, ClientSession, ClientTimeout, web

sys.path.insert(0, str(Path(__file__).resolve().parent))
from relay_config import (
    EN_LANGUAGE,
    LANGUAGE,
    LOG_DIR,
    RECORD_DIR,
    SPEECH_MODEL,
    STATE_PATH,
    TRANSCRIPT_DIR,
    TRANSCRIPTION_LANGUAGE,
    TRANSCRIPTION_PROVIDER,
    TTS_LANGUAGE,
    TTS_PROVIDER,
    VOICE,
    apply_env_files,
    load_twilio_vals,
)

apply_env_files()

PORT = int(os.environ.get("RELAY_PORT", "8765"))
HOST = os.environ.get("RELAY_HOST", "127.0.0.1")
MINIMAX_BASE = (os.environ.get("MINIMAX_BASE_URL") or "https://api.minimax.io/v1").rstrip("/")
MINIMAX_MODEL = os.environ.get("MINIMAX_MODEL") or "MiniMax-M3"
MAX_HISTORY = 8
MAX_COMPLETION = 256

SYSTEM_PROMPT = (
    "You are a phone assistant. "
    "Reply in Traditional Chinese if the caller speaks Chinese; "
    "reply in English if they speak English. "
    "Keep replies short for spoken TTS: one or two sentences, no markdown, "
    "no lists, no emojis, no stage directions."
)


def load_minimax_key() -> str:
    key = (os.environ.get("MINIMAX_API_KEY") or "").strip()
    if not key:
        raise RuntimeError("MINIMAX_API_KEY is not set (env, .env, or credentials.env)")
    return key


class RedactFilter(logging.Filter):
    _pats = (
        (re.compile(r"(Bearer\s+)\S+", re.I), r"\1[redacted]"),
        (re.compile(r"(Authorization:\s*)\S+", re.I), r"\1[redacted]"),
        (re.compile(r"AC[0-9a-f]{32}", re.I), lambda m: "AC…" + m.group(0)[-4:]),
        (re.compile(r"SK[0-9a-f]{32}", re.I), lambda m: "SK…" + m.group(0)[-4:]),
        (re.compile(r"(AuthToken|auth_token|TWILIO_AUTH_TOKEN)\s*[=:]\s*\S+", re.I), r"\1=[redacted]"),
    )

    def _scrub(self, text: str) -> str:
        for pat, repl in self._pats:
            text = pat.sub(repl, text)
        return text

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = self._scrub(record.msg)
        if record.args:
            cleaned = []
            for a in record.args:
                if isinstance(a, str):
                    a = self._scrub(a)
                cleaned.append(a)
            record.args = tuple(cleaned)
        return True


def setup_logging() -> logging.Logger:
    log = logging.getLogger("relay")
    if log.handlers:
        return log
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    filt = RedactFilter()
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(fmt)
    h.addFilter(filt)
    log.addHandler(h)
    # When nohup already captures stdout to logs/server.log, skip FileHandler
    # so lines are not duplicated.
    if sys.stdout.isatty():
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(LOG_DIR / "server.log")
        fh.setFormatter(fmt)
        fh.addFilter(filt)
        log.addHandler(fh)
    log.propagate = False
    return log


LOG = setup_logging()
MINIMAX_KEY = ""
HTTP: ClientSession | None = None
PENDING_POLLS: set[str] = set()


def load_twilio_env() -> dict[str, str]:
    return load_twilio_vals()


def read_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return {}
    try:
        data = json.loads(STATE_PATH.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_turn(call_sid: str, role: str, text: str, lang: str = "") -> Path:
    TRANSCRIPT_DIR.mkdir(parents=True, exist_ok=True)
    rec = {"call": call_sid, "role": role, "lang": lang, "text": text}
    path = TRANSCRIPT_DIR / (call_sid + ".jsonl")
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    LOG.info("saved_turn call=%s role=%s len=%s path=%s", call_sid[:8], role, len(text), str(path))
    return path


def recording_path(call_sid: str) -> Path:
    return RECORD_DIR / (call_sid + ".mp3")


def media_url_for(rec_url: str) -> str:
    url = (rec_url or "").strip()
    if url.endswith(".mp3"):
        return url
    return url + ".mp3"


def poll_twilio_recording(call_sid: str) -> tuple[str, str] | None:
    """Return (recording_sid, media_url) or None. Never logs secrets or full URLs."""
    try:
        from twilio.rest import Client
    except ImportError:
        LOG.error("recording_poll_skip twilio_sdk_missing")
        return None
    vals = load_twilio_env()
    sid = vals.get("TWILIO_ACCOUNT_SID") or ""
    token = vals.get("TWILIO_AUTH_TOKEN") or ""
    if not sid or not token:
        LOG.error("recording_poll_skip missing_creds")
        return None
    client = Client(sid, token)
    try:
        recs = list(client.calls(call_sid).recordings.list(limit=5))
    except Exception as exc:
        LOG.error("recording_poll_err kind=%s call=%s", type(exc).__name__, call_sid[:8])
        return None
    if not recs:
        LOG.info("recording_poll empty call=%s", call_sid[:8])
        return None
    rec = recs[0]
    rec_sid = rec.sid or ""
    media = f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Recordings/{rec_sid}.mp3"
    LOG.info("recording_poll hit call=%s rec=%s status=%s", call_sid[:8], rec_sid[:8], rec.status)
    return rec_sid, media


async def download_recording(call_sid: str, rec_url: str, rec_sid: str = "") -> Path | None:
    dest = recording_path(call_sid)
    RECORD_DIR.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 0:
        LOG.info("recording_already call=%s bytes=%s path=%s", call_sid[:8], dest.stat().st_size, str(dest))
        return dest
    if HTTP is None:
        LOG.error("recording_download_skip no_http")
        return None
    vals = load_twilio_env()
    sid = vals.get("TWILIO_ACCOUNT_SID") or ""
    token = vals.get("TWILIO_AUTH_TOKEN") or ""
    media = media_url_for(rec_url)
    auth = BasicAuth(sid, token) if sid and token else None
    try:
        async with HTTP.get(media, auth=auth, timeout=ClientTimeout(total=60)) as resp:
            body = await resp.read()
            code = resp.status
        if code >= 400:
            LOG.error("recording_download http=%s bytes=%s call=%s", code, len(body), call_sid[:8])
            return None
        dest.write_bytes(body)
        LOG.info(
            "recording_saved call=%s rec=%s bytes=%s path=%s",
            call_sid[:8],
            rec_sid[:8] if rec_sid else "-",
            dest.stat().st_size,
            str(dest),
        )
        return dest
    except Exception as exc:
        LOG.error("recording_download kind=%s call=%s", type(exc).__name__, call_sid[:8])
        return None


async def poll_recording_later(call_sid: str) -> None:
    if not call_sid or call_sid == "unknown":
        return
    if call_sid in PENDING_POLLS:
        return
    PENDING_POLLS.add(call_sid)
    dest = recording_path(call_sid)
    try:
        for delay in (8, 12, 20):
            await asyncio.sleep(delay)
            if dest.exists() and dest.stat().st_size > 0:
                LOG.info("recording_poll_skip already_saved path=%s", str(dest))
                return
            found = await asyncio.to_thread(poll_twilio_recording, call_sid)
            if not found:
                continue
            rec_sid, media = found
            saved = await download_recording(call_sid, media, rec_sid)
            if saved is not None:
                return
        LOG.warning("recording_poll_missed call=%s path_would_be=%s", call_sid[:8], str(dest))
    finally:
        PENDING_POLLS.discard(call_sid)


async def minimax_reply(messages: list[dict[str, str]]) -> str:
    assert HTTP is not None
    body = {
        "model": MINIMAX_MODEL,
        "messages": [{"role": "system", "content": SYSTEM_PROMPT}, *messages],
        "max_completion_tokens": MAX_COMPLETION,
        "thinking": {"type": "disabled"},
    }
    headers = {
        "Authorization": "Bearer " + MINIMAX_KEY,
        "Content-Type": "application/json",
    }
    try:
        async with HTTP.post(
            MINIMAX_BASE + "/chat/completions",
            json=body,
            headers=headers,
            timeout=ClientTimeout(total=30),
        ) as resp:
            status = resp.status
            raw = await resp.text()
    except Exception as exc:
        LOG.error("minimax_error kind=%s", type(exc).__name__)
        raise

    if status == 401:
        LOG.error("minimax_error http=401")
        raise RuntimeError("minimax 401")
    if status >= 400:
        LOG.error("minimax_error http=%s body_len=%s", status, len(raw))
        raise RuntimeError("minimax http %s" % status)

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        LOG.error("minimax_error invalid_json body_len=%s", len(raw))
        raise

    choice = (payload.get("choices") or [{}])[0]
    msg = choice.get("message") or {}
    text = (msg.get("content") or "").strip()
    if not text:
        LOG.error("minimax_error empty_content")
        raise RuntimeError("minimax empty content")
    return text


def spoken_lang(prompt_lang: str, text: str) -> str:
    lang = (prompt_lang or "").strip()
    if lang.startswith("en"):
        if re.search(r"[\u4e00-\u9fff]", text):
            return LANGUAGE
        return EN_LANGUAGE
    if lang.startswith("zh") or lang.startswith("cmn") or lang.startswith("yue"):
        return LANGUAGE
    if re.search(r"[\u4e00-\u9fff]", text):
        return LANGUAGE
    return LANGUAGE


async def handle_ws(request: web.Request) -> web.WebSocketResponse:
    ws = web.WebSocketResponse(heartbeat=20)
    await ws.prepare(request)
    LOG.info("connected path=%s peer=%s", request.path, request.remote)
    history: list[dict[str, str]] = []
    session_tag = "unknown"
    call_sid = "unknown"

    async for msg in ws:
        if msg.type == web.WSMsgType.TEXT:
            try:
                data: dict[str, Any] = json.loads(msg.data)
            except json.JSONDecodeError:
                LOG.error("bad_json bytes=%s", len(msg.data or ""))
                continue
            mtype = data.get("type")
            if mtype == "setup":
                sid = str(data.get("sessionId") or "")
                csid = str(data.get("callSid") or "")
                session_tag = (sid or csid or "anon")[:8]
                call_sid = csid or sid or "unknown"
                LOG.info(
                    "setup session=%s call=%s direction=%s",
                    session_tag,
                    csid[:8] if csid else "-",
                    data.get("direction"),
                )
            elif mtype == "prompt":
                voice = str(data.get("voicePrompt") or "")
                last = bool(data.get("last", True))
                LOG.info(
                    "transcript session=%s last=%s len=%s lang=%s",
                    session_tag,
                    last,
                    len(voice),
                    data.get("lang"),
                )
                if not last or not voice.strip():
                    continue
                history.append({"role": "user", "content": voice.strip()})
                history[:] = history[-MAX_HISTORY:]
                save_turn(call_sid, "user", voice.strip(), str(data.get("lang") or ""))
                try:
                    reply = await minimax_reply(history)
                except Exception:
                    reply = "抱歉，我剛才沒聽清楚，請再說一次。"
                history.append({"role": "assistant", "content": reply})
                history[:] = history[-MAX_HISTORY:]
                lang = spoken_lang(str(data.get("lang") or ""), reply)
                save_turn(call_sid, "assistant", reply, lang)
                LOG.info("reply session=%s len=%s lang=%s", session_tag, len(reply), lang)
                await ws.send_json(
                    {"type": "text", "token": reply, "last": True, "lang": lang}
                )
            elif mtype == "dtmf":
                LOG.info("dtmf session=%s", session_tag)
            elif mtype == "interrupt":
                LOG.info("interrupt session=%s", session_tag)
            elif mtype == "error":
                desc = str(data.get("description") or "")
                LOG.error("twilio_error session=%s desc_len=%s", session_tag, len(desc))
            else:
                LOG.info("event session=%s type=%s", session_tag, mtype)
        elif msg.type == web.WSMsgType.ERROR:
            LOG.error("ws_error session=%s kind=%s", session_tag, type(ws.exception()).__name__)
        elif msg.type in (web.WSMsgType.CLOSE, web.WSMsgType.CLOSING):
            break

    LOG.info("disconnected session=%s", session_tag)
    if call_sid and call_sid != "unknown" and not call_sid.startswith("CAdummy"):
        asyncio.create_task(poll_recording_later(call_sid))
    return ws


async def health(_request: web.Request) -> web.Response:
    state = read_state()
    return web.json_response(
        {
            "ok": True,
            "service": "conversation-relay",
            "local_port": PORT,
            "public_https": state.get("public_https") or "",
            "public_wss": state.get("public_wss") or "",
            "recordings_dir": str(RECORD_DIR),
            "transcripts_dir": str(TRANSCRIPT_DIR),
            "defaults": {
                "language": TRANSCRIPTION_LANGUAGE,
                "ttsLanguage": TTS_LANGUAGE,
                "transcriptionLanguage": TRANSCRIPTION_LANGUAGE,
                "ttsProvider": TTS_PROVIDER,
                "voice": VOICE,
                "transcriptionProvider": TRANSCRIPTION_PROVIDER,
                "speechModel": SPEECH_MODEL,
                "record": True,
            },
        }
    )


async def recording_status(request: web.Request) -> web.Response:
    post = await request.post()
    rec_sid = str(post.get("RecordingSid") or "")
    rec_url = str(post.get("RecordingUrl") or "")
    status = str(post.get("RecordingStatus") or "")
    call = str(post.get("CallSid") or "unknown")
    LOG.info(
        "recording_status call=%s rec=%s status=%s dest=%s",
        call[:8],
        rec_sid[:8],
        status,
        str(recording_path(call)),
    )
    if status.lower() != "completed":
        return web.Response(text="ok")
    if not rec_url or not rec_sid:
        return web.Response(text="ok")
    await download_recording(call, rec_url, rec_sid)
    return web.Response(text="ok")


async def connect_action(request: web.Request) -> web.Response:
    if request.method == "GET":
        return web.Response(text="<Response></Response>", content_type="text/xml")
    post = await request.post()
    skip = {"accountsid", "authtoken", "account_sid", "auth_token"}
    safe = {k: str(post.get(k, ""))[:120] for k in post.keys() if k.lower() not in skip}
    call = str(post.get("CallSid") or "")
    LOG.info(
        "connect_action keys=%s status=%s session=%s err=%s",
        sorted(safe.keys()),
        safe.get("CallStatus") or safe.get("SessionStatus"),
        (safe.get("SessionStatus") or "")[:40],
        (safe.get("ErrorCode") or "") + " " + (safe.get("ErrorMessage") or "")[:80],
    )
    if call:
        asyncio.create_task(poll_recording_later(call))
    return web.Response(text="<Response></Response>", content_type="text/xml")


async def on_startup(_app: web.Application) -> None:
    global MINIMAX_KEY, HTTP
    MINIMAX_KEY = load_minimax_key()
    HTTP = ClientSession()
    RECORD_DIR.mkdir(parents=True, exist_ok=True)
    TRANSCRIPT_DIR.mkdir(parents=True, exist_ok=True)
    LOG.info(
        "server_start host=%s port=%s minimax_key=present recordings=%s transcripts=%s",
        HOST,
        PORT,
        str(RECORD_DIR),
        str(TRANSCRIPT_DIR),
    )


async def on_cleanup(_app: web.Application) -> None:
    global HTTP
    if HTTP is not None:
        await HTTP.close()
        HTTP = None
    LOG.info("server_stop")


def main() -> None:
    app = web.Application()
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    app.router.add_get("/health", health)
    app.router.add_post("/connect_action", connect_action)
    app.router.add_get("/connect_action", connect_action)
    app.router.add_post("/recording_status", recording_status)
    app.router.add_get("/ws", handle_ws)
    app.router.add_get("/conversation-relay", handle_ws)
    web.run_app(app, host=HOST, port=PORT, print=lambda *_: None)


if __name__ == "__main__":
    main()
