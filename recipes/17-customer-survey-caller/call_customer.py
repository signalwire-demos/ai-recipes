#!/usr/bin/env python3
"""Start an outbound survey: REST-dial the customer into this agent.

  python call_customer.py P-0101                  # dials CUSTOMER_NUMBER from FROM_NUMBER
  python call_customer.py P-0101 --to +15550123   # override the number
  python call_customer.py P-0101 --dry-run        # print the plan, don't dial

The platform fetches the agent's SWML from PUBLIC_URL with the recipe's basic auth
when the customer answers. The customer id rides in the URL (?customer=P-0101),
so every answer row in data/results.jsonl carries customer_id P-0101.
"""
import argparse
import os
import re
import sys
from urllib.parse import quote, urlencode, urlparse

import config  # loads .env files and sets the knobs


def agent_url(customer_id: str, mask: bool = False) -> str:
    base = urlparse(os.environ["PUBLIC_URL"])
    user = quote(os.environ["SWML_BASIC_AUTH_USER"], safe="")
    password = "***" if mask else quote(os.environ["SWML_BASIC_AUTH_PASSWORD"], safe="")
    path = base.path.rstrip("/") + config.ROUTE
    return f"https://{user}:{password}@{base.netloc}{path}?{urlencode({'customer': customer_id})}"


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("customer_id", help="letters, digits and dashes, e.g. P-0101")
    p.add_argument("--to", default=config.CUSTOMER_NUMBER, help="number to dial (default CUSTOMER_NUMBER)")
    p.add_argument("--from", dest="from_", default=config.FROM_NUMBER, help="caller ID (default FROM_NUMBER)")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv)

    if not re.match(config.CUSTOMER_ID_PATTERN, args.customer_id):
        p.error("customer_id must be 1-32 letters, digits or dashes")
    missing = [k for k, v in {"--to / CUSTOMER_NUMBER": args.to, "--from / FROM_NUMBER": args.from_,
                              "PUBLIC_URL": os.environ.get("PUBLIC_URL"),
                              "SWML_BASIC_AUTH_USER": os.environ.get("SWML_BASIC_AUTH_USER"),
                              "SWML_BASIC_AUTH_PASSWORD": os.environ.get("SWML_BASIC_AUTH_PASSWORD")}.items() if not v]
    if missing:
        p.error("missing: " + ", ".join(missing))

    print(f"dial {args.to} from {args.from_} -> {agent_url(args.customer_id, mask=True)}")
    if args.dry_run:
        return 0

    from signalwire.rest import RestClient  # reads SIGNALWIRE_PROJECT_ID / _API_TOKEN / _SPACE
    client = RestClient()
    call = client.calling.dial(from_=args.from_, to=args.to, url=agent_url(args.customer_id))
    print(f"call id: {call.get('id')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
