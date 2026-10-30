"""Return the calls. Sweeps data/runtime/callbacks.json and REST-dials each pending customer
into the app's /callback?id=... route, where the saved context is loaded before the call starts.

  python callback_worker.py            # sweep every WORKER_INTERVAL seconds
  python callback_worker.py --once     # one sweep, then exit
"""
import argparse
import os
import time
from urllib.parse import quote, urlparse

import config
import store


def callback_url(record_id: str) -> str:
    """https://USER:PASS@host/callback?id=CB-0001 (the platform fetches SWML with basic auth)."""
    u = urlparse(config.PUBLIC_URL)
    user = quote(os.environ.get("SWML_BASIC_AUTH_USER", ""), safe="")
    password = quote(os.environ.get("SWML_BASIC_AUTH_PASSWORD", ""), safe="")
    auth = f"{user}:{password}@" if user and password else ""
    return f"{u.scheme}://{auth}{u.netloc}{config.CALLBACK_ROUTE}?id={record_id}"


def sweep(client) -> list[str]:
    """Dial every pending callback once. Returns the record ids dialed."""
    dialed = []
    for rec in store.pending():
        try:
            call = client.calling.dial(from_=config.FROM_NUMBER, to=rec["number"],
                                       url=callback_url(rec["id"]))
        except Exception as exc:  # leave it pending; the next sweep retries
            print(f"{rec['id']}: dial failed: {exc}")
            continue
        store.update(rec["id"], status="dialing", call_id=call.get("id"), dialed_at=store.now())
        print(f"{rec['id']}: dialing {rec['number']} (call {call.get('id')})")
        dialed.append(rec["id"])
    return dialed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--once", action="store_true", help="one sweep, then exit")
    args = parser.parse_args()
    if not (config.PUBLIC_URL and config.FROM_NUMBER):
        raise SystemExit("Set PUBLIC_URL and FROM_NUMBER (or OUTBOUND_2) in .env first.")

    from signalwire.rest import RestClient  # reads SIGNALWIRE_PROJECT_ID / _API_TOKEN / _SPACE

    client = RestClient()
    while True:
        sweep(client)
        if args.once:
            return
        time.sleep(config.WORKER_INTERVAL)


if __name__ == "__main__":
    main()
