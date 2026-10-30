#!/usr/bin/env python3
"""Start an outbound phone screen: REST-dial the candidate into this agent.

  python call_candidate.py C-0101                  # dials CANDIDATE_NUMBER from FROM_NUMBER
  python call_candidate.py C-0101 --to +15550123   # override the number
  python call_candidate.py C-0101 --dry-run        # print the plan, don't dial

The platform fetches the agent's SWML from PUBLIC_URL with the recipe's basic auth
when the candidate answers. The candidate id rides in the URL (?candidate=C-0101),
so the agent saves the screen as data/candidates/C-0101.json.
"""
import argparse
import os
import re
import sys
from urllib.parse import quote, urlencode, urlparse

import config  # loads .env files and sets the knobs


def agent_url(candidate_id: str, mask: bool = False) -> str:
    base = urlparse(os.environ["PUBLIC_URL"])
    user = quote(os.environ["SWML_BASIC_AUTH_USER"], safe="")
    password = "***" if mask else quote(os.environ["SWML_BASIC_AUTH_PASSWORD"], safe="")
    path = base.path.rstrip("/") + config.ROUTE
    return f"https://{user}:{password}@{base.netloc}{path}?{urlencode({'candidate': candidate_id})}"


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("candidate_id", help="letters, digits and dashes, e.g. C-0101")
    p.add_argument("--to", default=config.CANDIDATE_NUMBER, help="number to dial (default CANDIDATE_NUMBER)")
    p.add_argument("--from", dest="from_", default=config.FROM_NUMBER, help="caller ID (default FROM_NUMBER)")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv)

    if not re.match(config.CANDIDATE_ID_PATTERN, args.candidate_id):
        p.error("candidate_id must be 1-32 letters, digits or dashes")
    missing = [k for k, v in {"--to / CANDIDATE_NUMBER": args.to, "--from / FROM_NUMBER": args.from_,
                              "PUBLIC_URL": os.environ.get("PUBLIC_URL"),
                              "SWML_BASIC_AUTH_USER": os.environ.get("SWML_BASIC_AUTH_USER"),
                              "SWML_BASIC_AUTH_PASSWORD": os.environ.get("SWML_BASIC_AUTH_PASSWORD")}.items() if not v]
    if missing:
        p.error("missing: " + ", ".join(missing))

    print(f"dial {args.to} from {args.from_} -> {agent_url(args.candidate_id, mask=True)}")
    if args.dry_run:
        return 0

    from signalwire.rest import RestClient  # reads SIGNALWIRE_PROJECT_ID / _API_TOKEN / _SPACE
    client = RestClient()
    call = client.calling.dial(from_=args.from_, to=args.to, url=agent_url(args.candidate_id))
    print(f"call id: {call.get('id')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
