# conversation-relay

Live office voice on **+12364993754** uses **Retell** over **Twilio Elastic SIP** (outbound and inbound). ConversationRelay and MiniMax are **not** the live path.

Intended public home: `https://github.com/alexanderedm/conversation-relay`

This repository contains **no API keys, tokens, SIP passwords, or personal phone numbers**. Configure local prototype env from placeholders (see `.env.example`). Do not commit `.env`, `credentials.env`, `state.json`, recordings, transcripts, or logs. Do not publish personal 403 numbers. Do not invent or publish a personal phone number.

## Current production (Retell + Twilio SIP)

One Canadian office number handles both outbound and inbound: **+12364993754**.

Voice audio goes Retell over Twilio Elastic SIP:

- **Termination** (Twilio → Retell): `chiao-office-retell.pstn.twilio.com`
- **Inbound origination**: `sip:sip.retellai.com`

| Direction | Agent | Behavior |
|---|---|---|
| Outbound | Chiao Office Outbound | Published. Close with *Have a good day* / *Have a good evening*, not only *Thanks that's all*. |
| Inbound | Chiao Office Inbound | Same Retell Cimo voice. Answers *Edmund Chiao's office.* Takes a message (name / reason / callback) one question at a time. Closes with *Thanks for calling Edmund Chiao's office. Have a good evening.* / *Have a good day.* |

SIP credentials, Retell API keys, and Twilio auth live in those dashboards — not in this tree.

### Practice-only number

**+18254518021** is a scripted fake rental desk for practice. It is **not** a customer number and not the office line.

## Secrets

Keep the existing no-secrets rules:

- No Twilio SID/token, Retell key, MiniMax key, SIP password, or recovery codes
- No personal 403 numbers
- Placeholder env examples stay placeholders (`+1XXXXXXXXXX`, empty keys)
- No `recordings/*.mp3`, `transcripts/*.jsonl`, `logs/`, or live `state.json`
- No `cloudflared` binary
- No `minimax.json` / connector-secrets scan

Logs redact `Bearer` tokens, Auth Token assignments, and `AC…` / `SK…` key shapes.

## Historical: ConversationRelay + MiniMax (parked)

This tree still contains the original local ConversationRelay + MiniMax websocket server (TwiML `<ConversationRelay>`, trycloudflare tunnel, MiniMax short replies). That path is **parked / historical only**. Live office calls do not use ConversationRelay, MiniMax, or the tunnel.

What follows is how to run that parked prototype locally. It is not production voice.

### Defaults (STT / TTS split)

Twilio **64101** (`Invalid values (google/cmn-TW/long) for transcription settings`) killed live calls that used Google STT + `cmn-TW` + `long`. Listen stays on the combo that already worked. Speak stays Google `cmn-TW`.

Leading TwiML `<Say>` (plays even if websocket/TTS is late):

- `language="cmn-TW"`
- `voice="Google.cmn-TW-Standard-A"`
- text: `Office audio check.`

Then `<ConversationRelay>`:

| Attribute | Value | Why |
|---|---|---|
| `language` | `en-US` | Session default = STT+TTS; we override TTS. Do **not** set this to `cmn-TW` or STT becomes invalid. |
| `ttsLanguage` | `cmn-TW` | Spoken replies / welcome after the websocket connects |
| `transcriptionLanguage` | `en-US` | Google STT. `google/cmn-TW/long` is Twilio **64101**. |
| `ttsProvider` | `Google` | Already produced audible audio |
| `voice` | `cmn-TW-Standard-A` | Documented Google Standard voice for `cmn-TW` |
| `transcriptionProvider` | `Google` | |
| `speechModel` | `telephony` | Google phone STT; same combo as the audible English test call |
| `interruptible` | `any` | |
| `record` | `true` (Calls.create) | Dual channel + `/recording_status` |
| nested `<Language>` | `cmn-TW` TTS-only (no STT attrs); `en-US` + Google `telephony` | STT must stay a valid Google pair |

**Do not default to `language=multi` + ElevenLabs.** That combination produced silent billed calls.

`welcomeGreeting` is spoken only **after** the websocket connects. The leading `<Say>` is the fallback so the callee hears something first.

### Tunnel hostnames change

trycloudflare issues a **new hostname every time the tunnel restarts**.

- `watch_tunnel.sh` rewrites `state.json` (`public_wss` / `public_https`) on each spawn.
- `place_call.py` **re-reads `state.json` immediately before** `calls.create`. Never cache the hostname in an env var.
- After a restart, preview TwiML again so you are not pointing ConversationRelay at a dead host.

Copy `state.example.json` to `state.json` only for local inspection. The example uses `wss://example.trycloudflare.com/ws` — a fake host.

### Configure via env

```bash
cp .env.example .env
# edit .env — placeholder keys only; never commit real values
```

| Variable | Purpose |
|---|---|---|
| `TWILIO_ACCOUNT_SID` | Account SID (`AC…`) |
| `TWILIO_AUTH_TOKEN` | Auth Token |
| `TWILIO_FROM_NUMBER` | Caller ID you own (`+1XXXXXXXXXX`) |
| `TWILIO_TO_NUMBER` | Destination (`+1XXXXXXXXXX`) |
| `MINIMAX_API_KEY` | MiniMax API key |
| `MINIMAX_BASE_URL` | Default `https://api.minimax.io/v1` |
| `MINIMAX_MODEL` | Default `MiniMax-M3` |
| `RELAY_PLACE_CALL` | Empty by default. Set to `1` **only** to allow a live dial |

Load order: process environment, then `./.env`, then `./credentials.env` (gitignored). There is no box-specific fallback path.

`place_call.py` refuses to dial if `TWILIO_TO_NUMBER` or `TWILIO_FROM_NUMBER` is missing. There are no hardcoded phone numbers in the scripts.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Install [cloudflared](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/) separately (or set `CLOUDFLARED=`). A `cloudflared` binary is **not** shipped in this repo.

### Start server + tunnel

```bash
./launch.sh                 # HTTP/WS on 127.0.0.1:8765
./launch_tunnel.sh          # trycloudflare → rewrites state.json
# or both:
./restart.sh
```

Endpoints:

- `GET /health` — `ok`, public URLs from `state.json`, current STT/TTS defaults
- `GET /ws` (also `/conversation-relay`) — ConversationRelay websocket
- `POST /connect_action` — session end + recording poll if the callback missed
- `POST /recording_status` — downloads mp3 under `recordings/<CallSid>.mp3`

Transcripts land in `transcripts/<CallSid>.jsonl` (gitignored).

### Preview TwiML (no call)

```bash
python3 place_call.py --print-only
python3 print_payload.py
```

These print the payload built from the **current** `state.json`. They do not dial.

### Live call guard

```bash
RELAY_PLACE_CALL=1 python3 place_call.py
```

Without `RELAY_PLACE_CALL=1` the script exits and does nothing. Fetch an existing recording (still no new call):

```bash
python3 place_call.py --fetch-recording CA...
```

### Local proofs (no phone)

```bash
./run_dummy.sh
python3 prove_local.py          # syntax + /health + mock recording download
python3 check_auth.py           # yes/no reachability; never prints secrets
```

### Chinese / TTS notes

- `zh-TW` is **not** a ConversationRelay default-table language. This prototype uses documented `cmn-TW` for **TTS only**.
- ConversationRelay's default voice table has **no** Chinese rows. TTS uses the official Twilio TTS table (`cmn-TW` + Google `cmn-TW-Standard-A`).
- ConversationRelay STT `google/cmn-TW/long` is **invalid (64101)** and dropped live calls at ~7s. Listen is `en-US` + Google `telephony` until a proven Chinese STT exists. Speak stays Google `cmn-TW`.
- `language=multi` requires ElevenLabs TTS + Deepgram STT and already went silent. Do not use it.
