#!/usr/bin/env python3
"""List notifications/alerts for a Call SID. Requires TWILIO_* env."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from relay_config import load_twilio_vals


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: python3 call_notifs.py <CallSid>", file=sys.stderr)
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
    print("---call notifications---")
    try:
        notes = client.calls(sid).notifications.list(limit=20)
        print("count", len(notes))
        for n in notes:
            print("code", getattr(n, "error_code", None))
            print("msg", (getattr(n, "message_text", "") or "")[:400])
    except Exception as e:
        print("call_notif_err", type(e).__name__)
    print("---monitor alerts---")
    try:
        alerts = client.monitor.v1.alerts.list(limit=15)
        print("alerts", len(alerts))
        for a in alerts:
            print(
                getattr(a, "date_created", None),
                getattr(a, "error_code", None),
                getattr(a, "log_level", None),
                (getattr(a, "alert_text", "") or "")[:220],
            )
    except Exception as e:
        print("alert_err", type(e).__name__)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
