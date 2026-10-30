"""Fill the rep page without a phone: replay a fixture call against the running app.

    python app.py &                       # then open http://localhost:$PORT/rep/
    python replay.py price-and-boss       # names are in data/transcripts.json

Each customer line goes to POST /swaig as a flag_objection call, the same request the
sidecar's model makes on a live call; the classifier decides which lines become cards.
The replay ends with an ai_sidecar `final` event to POST /events (documented shape).
"""
import base64
import json
import os
import sys
import time
import urllib.request

import config


def post(path: str, body: dict) -> None:
    auth = f"{os.environ.get('SWML_BASIC_AUTH_USER', '')}:{os.environ.get('SWML_BASIC_AUTH_PASSWORD', '')}"
    req = urllib.request.Request(
        f"http://localhost:{config.PORT}{path}", data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json",
                 "Authorization": "Basic " + base64.b64encode(auth.encode()).decode()})
    urllib.request.urlopen(req, timeout=5).read()


def main(name: str) -> None:
    calls = {c["name"]: c for c in json.loads((config.HERE / "data" / "transcripts.json").read_text())["calls"]}
    call_id = f"replay-{name}"
    for line in calls[name]["lines"]:
        if line["speaker"] != "customer":
            continue
        print("customer:", line["text"])
        post("/swaig", {"function": "flag_objection", "call_id": call_id,
                        "argument": {"parsed": [{"customer_quote": line["text"]}]}})
        time.sleep(1.5)
    post("/events", {"call_info": {"call_id": call_id},
                     "sidecar_event": {"type": "final", "stop_reason": "transcribe_close"}})


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "price-and-boss")
