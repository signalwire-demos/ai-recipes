"""Replay a fixture call into a running app, so /captions can be watched without a phone.

  python replay.py                      # data/fixtures/meeting-call.jsonl, real-time pacing
  python replay.py --speed 4 --url http://localhost:3000

Each event's timestamp is moved to "now minus a simulated platform delay", so the delay
badges on the page show believable numbers. Uses the basic auth from config/.env.
"""
import argparse
import json
import os
import random
import time
from pathlib import Path

import httpx

import config
from adapter import call_id_of

FIXTURE = config.HERE / "data" / "fixtures" / "meeting-call.jsonl"


def restamp(body: dict, now: float, delay_s: float) -> dict:
    """Copy of a sidecar-style fixture body with its microsecond ts set to now - delay."""
    body = json.loads(json.dumps(body))
    body["transcribe_event"]["ts"] = int((now - delay_s) * 1e6)
    return body


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--file", type=Path, default=FIXTURE)
    ap.add_argument("--url", default=f"http://localhost:{config.PORT}")
    ap.add_argument("--speed", type=float, default=1.0)
    args = ap.parse_args()
    auth = (os.environ.get("SWML_BASIC_AUTH_USER", ""), os.environ.get("SWML_BASIC_AUTH_PASSWORD", ""))
    bodies = [json.loads(line) for line in args.file.read_text().splitlines() if line.strip()]
    prev = bodies[0]["transcribe_event"]["ts"]
    for body in bodies:
        time.sleep(max(0, body["transcribe_event"]["ts"] - prev) / 1e6 / args.speed)
        prev = body["transcribe_event"]["ts"]
        r = httpx.post(f"{args.url}{config.TRANSCRIPT_PATH}", auth=auth,
                       json=restamp(body, time.time(), random.uniform(0.25, 1.2)))
        print(r.status_code, body["transcribe_event"]["type"], body["transcribe_event"]["text"])
    print(f"open {args.url}/captions?call_id={call_id_of(bodies[0])}")


if __name__ == "__main__":
    main()
