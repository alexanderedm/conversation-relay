#!/usr/bin/env python3
"""Fetch status for a Call SID. Requires TWILIO_* env. Does not place a call."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from relay_config import load_twilio_vals


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: python3 call_status.py <CallSid>", file=sys.stderr)
        return 2
    sid = sys.argv[1]
    vals = load_twilio_vals()
    acct = vals.get("TWILIO_ACCOUNT_SID") or ""
    token = vals.get("TWILIO_AUTH_TOKEN") or ""
    if not acct or not token:
        print("missing TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN", file=sys.stderr)
        return 2
    from twilio.rest import Client

    client = Client(acct, token)
    call = client.calls(sid).fetch()
    print("sid=" + call.sid)
    print("status=" + str(call.status))
    print("duration=" + str(call.duration))
    print("answered=" + str(getattr(call, "answered_by", None)))
    err = getattr(call, "error_code", None) or getattr(call, "error_message", None)
    print("error=" + str(err))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
