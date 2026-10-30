"""Fill the rep page without a phone: replay one support call against the running app.

    python app.py &                       # then open http://localhost:$PORT/rep/
    python replay.py

Sends the same POST /swaig requests the sidecar's model makes on a live call: a lookup,
a credit inside the cap, a second credit on the same order, and one over the cap. It
ends with an ai_sidecar `final` event to POST /events (documented shape).
"""
import base64
import json
import os
import time
import urllib.request

import config

CALL = "replay-support"
STEPS = [
    ("lookup_order", {"order_id": "A-1001"}),
    ("issue_credit", {"order_id": "A-1001", "amount": 10, "reason": "Lamp arrived scratched"}),
    ("issue_credit", {"order_id": "A-1001", "amount": 5, "reason": "Customer asked again"}),
    ("lookup_order", {"order_id": "A-1002"}),
    ("issue_credit", {"order_id": "A-1002", "amount": 60, "reason": "Lost first shipment"}),
]


def post(path: str, body: dict) -> str:
    auth = f"{os.environ.get('SWML_BASIC_AUTH_USER', '')}:{os.environ.get('SWML_BASIC_AUTH_PASSWORD', '')}"
    req = urllib.request.Request(
        f"http://localhost:{config.PORT}{path}", data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json",
                 "Authorization": "Basic " + base64.b64encode(auth.encode()).decode()})
    return urllib.request.urlopen(req, timeout=5).read().decode()


if __name__ == "__main__":
    for function, args in STEPS:
        reply = post("/swaig", {"function": function, "call_id": CALL, "argument": {"parsed": [args]}})
        print(f"{function}({args}) -> model sees: {json.loads(reply)['response']}")
        time.sleep(1.5)
    post("/events", {"call_info": {"call_id": CALL},
                     "sidecar_event": {"type": "final", "stop_reason": "transcribe_close"}})
