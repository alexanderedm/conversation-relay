#!/usr/bin/env python3
"""Reachability checks. Prints yes/no only. Never prints secrets."""
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from relay_config import apply_env_files, load_twilio_vals

apply_env_files()


def check_twilio() -> str:
    try:
        from twilio.rest import Client

        vals = load_twilio_vals()
        sid = vals.get("TWILIO_ACCOUNT_SID") or ""
        token = vals.get("TWILIO_AUTH_TOKEN") or ""
        if not sid or not token:
            print("twilio=no kind=missing_creds")
            return "no"
        client = Client(sid, token)
        acct = client.api.accounts(sid).fetch()
        from_num = vals.get("TWILIO_FROM_NUMBER") or ""
        listed = False
        if from_num:
            nums = [n.phone_number for n in client.incoming_phone_numbers.list(limit=20)]
            listed = from_num in nums
        print(
            "twilio=yes account_status=%s from_listed=%s"
            % (acct.status, listed if from_num else "unset")
        )
        return "yes"
    except Exception as exc:
        print("twilio=no kind=%s" % type(exc).__name__)
        return "no"


def check_minimax() -> str:
    try:
        key = (os.environ.get("MINIMAX_API_KEY") or "").strip()
        if not key:
            print("minimax=no kind=missing_key")
            return "no"
        base = (os.environ.get("MINIMAX_BASE_URL") or "https://api.minimax.io/v1").rstrip("/")
        model = os.environ.get("MINIMAX_MODEL") or "MiniMax-M3"
        body = {
            "model": model,
            "messages": [
                {"role": "system", "content": "Reply with the single word pong."},
                {"role": "user", "content": "ping"},
            ],
            "max_completion_tokens": 16,
            "thinking": {"type": "disabled"},
        }
        req = urllib.request.Request(
            base + "/chat/completions",
            data=json.dumps(body).encode(),
            method="POST",
            headers={
                "Authorization": "Bearer " + key,
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=45) as r:
            payload = json.loads(r.read().decode())
        text = ((payload.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        print("minimax=yes http=200 reply_len=%s" % len(text.strip()))
        return "yes"
    except urllib.error.HTTPError as e:
        print("minimax=no http=%s" % e.code)
        return "no"
    except Exception as exc:
        print("minimax=no kind=%s" % type(exc).__name__)
        return "no"


if __name__ == "__main__":
    check_twilio()
    check_minimax()
