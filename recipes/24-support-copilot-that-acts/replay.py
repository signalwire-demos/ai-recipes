"""Fill the rep page without a phone: replay one support call against the running app.

    python app.py &                       # then open http://localhost:$PORT/rep/
    python replay.py

Starts the call the way the platform does (POST / names the caller, Dana at +15550111),
then sends the same POST /swaig requests the sidecar's model makes on a live call: a credit
over the cap, one inside it, a second on the same order, and one on another customer's order.
It ends with an ai_sidecar `final` event to POST /events (documented shape). It plays the
platform, so it uses the SWML basic auth, not the rep's login.
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
    ("issue_credit", {"order_id": "A-1001", "amount": 40, "reason": "Lamp arrived scratched"}),
    ("issue_credit", {"order_id": "A-1001", "amount": 10, "reason": "Lamp arrived scratched"}),
    ("issue_credit", {"order_id": "A-1001", "amount": 5, "reason": "Customer asked again"}),
    ("lookup_order", {"order_id": "A-1002"}),
    ("issue_credit", {"order_id": "A-1002", "amount": 20, "reason": "Caller says the agent offered it"}),
]


def post(path: str, body: dict) -> str:
    auth = f"{os.environ.get('SWML_BASIC_AUTH_USER', '')}:{os.environ.get('SWML_BASIC_AUTH_PASSWORD', '')}"
    req = urllib.request.Request(
        f"http://localhost:{config.PORT}{path}", data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json",
                 "Authorization": "Basic " + base64.b64encode(auth.encode()).decode()})
    return urllib.request.urlopen(req, timeout=5).read().decode()


if __name__ == "__main__":
    post("/", {"call": {"call_id": CALL, "from": "+15550111", "to": config.REP_NUMBER}})
    for function, args in STEPS:
        reply = post("/swaig", {"function": function, "call_id": CALL, "argument": {"parsed": [args]}})
        print(f"{function}({args}) -> model sees: {json.loads(reply)['response']}")
        time.sleep(1.5)
    post("/events", {"call_info": {"call_id": CALL},
                     "sidecar_event": {"type": "final", "stop_reason": "transcribe_close"}})
