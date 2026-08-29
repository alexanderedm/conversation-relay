#!/usr/bin/env python3
"""Print the ready outbound Calls.create payload. Does not place a call."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from place_call import dest_numbers, public_https, public_wss, twiml_for

wss = public_wss()
to_num, from_num = dest_numbers()
print("to=" + (to_num or "(unset)"))
print("from=" + (to_num or "(unset)"))
print("public_wss=" + wss)
print("public_https=" + public_https())
print("twiml=" + twiml_for(wss))
print("place_cmd=RELAY_PLACE_CALL=1 python3 place_call.py")
print("preview_cmd=python3 place_call.py --print-only")
