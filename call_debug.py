#!/usr/bin/env python3
"""Debug a Call SID (status, events, notifications). Requires TWILIO_* env."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from relay_config import load_twilio_vals


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: python3 call_debug.py <CallSid>", file=sys.stderr)
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
    keys = [
        "status", "duration", "start_time", "end_time", "direction",
        "answered_by", "caller_name", "price", "price_unit",
        "queue_time", "group_sid",
    ]
    for k in keys:
        print(f"{k}={getattr(call, k, None)}")
    print("sip_response=" + str(getattr(call, "sip_response_code", None)))
    print("---notifications---")
    try:
        notes = client.monitor.v1.alerts.list(resource_sid=sid, limit=20)
        print("alerts", len(notes))
        for a in notes:
            print(
                "alert",
                getattr(a, "error_code", None),
                (getattr(a, "alert_text", "") or "")[:240],
                getattr(a, "log_level", None),
            )
    except Exception as e:
        print("alerts_err", type(e).__name__)
    try:
        evs = client.calls(sid).events.list(limit=30)
        print("---events---", len(evs))
        for e in evs:
            print("event", getattr(e, "request", None), getattr(e, "response", None))
    except Exception as e:
        print("events_err", type(e).__name__)
    try:
        count = 0
        for n in client.api.accounts(acct).notifications.list(limit=30):
            msg = (getattr(n, "message_text", None) or "") + " " + (getattr(n, "error_code", None) or "")
            if sid[2:10] in (getattr(n, "call_sid", "") or "") or sid in str(getattr(n, "request_url", "")) or sid in msg:
                print("notif", n.sid, getattr(n, "error_code", None), (getattr(n, "message_text", "") or "")[:200])
                count += 1
        print("notif_matched", count)
        print("---latest_notifs---")
        for n in client.api.accounts(acct).notifications.list(limit=8):
            print("latest", getattr(n, "error_code", None), getattr(n, "call_sid", None), (getattr(n, "message_text", "") or "")[:180])
    except Exception as e:
        print("notif_err", type(e).__name__)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
