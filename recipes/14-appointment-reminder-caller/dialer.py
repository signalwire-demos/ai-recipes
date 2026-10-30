"""Dial each appointment contact into the reminder agent, with consent rules built in.

  python dialer.py --dry-run     # who would be called now, and why the others are skipped
  python dialer.py               # REST-dial everyone who passes, from FROM_NUMBER (OUTBOUND_1)

A contact is called only if consent is "yes", the number is not on the do-not-call
list, and it is inside CALL_WINDOW in the contact's own time zone.
"""
import argparse
from datetime import datetime, time
from urllib.parse import quote, urlparse
from zoneinfo import ZoneInfo

import config
import contacts


def parse_window(window: str) -> tuple[time, time]:
    start, end = (time.fromisoformat(part.strip()) for part in window.split("-"))
    return start, end


def skip_reason(contact: dict, dnc: set[str], now_utc: datetime) -> str | None:
    if contact.get("consent", "").strip().lower() != "yes":
        return "no consent"
    if contact["phone"] in dnc:
        return "on do-not-call list"
    local = now_utc.astimezone(ZoneInfo(contact["timezone"]))
    start, end = parse_window(config.CALL_WINDOW)
    if not start <= local.time() < end:
        return f"outside calling hours ({local:%H:%M} local)"
    return None


def plan(now_utc: datetime) -> tuple[list[dict], list[tuple[dict, str]]]:
    dnc = contacts.load_dnc()
    call, skip = [], []
    for contact in contacts.load_contacts().values():
        reason = skip_reason(contact, dnc, now_utc)
        if reason:
            skip.append((contact, reason))
        else:
            call.append(contact)
    return call, skip


def agent_url(appointment_id: str) -> str:
    u = urlparse(config.PUBLIC_URL)
    user, password = (quote(x, safe="") for x in config.BASIC_AUTH)
    return f"{u.scheme}://{user}:{password}@{u.netloc}{config.ROUTE}?appt={quote(appointment_id)}"


def dial(contact: dict, client) -> str:
    call = client.calling.dial(from_=config.FROM_NUMBER, to=contact["phone"],
                               url=agent_url(contact["appointment_id"]))
    return call["id"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="print the plan; dial nobody")
    args = parser.parse_args()

    call, skip = plan(datetime.now(ZoneInfo("UTC")))
    for contact, reason in skip:
        print(f"skip  {contact['appointment_id']}  {contact['phone']}  {reason}")
    for contact in call:
        print(f"call  {contact['appointment_id']}  {contact['phone']}  {contact['timezone']}")
    if args.dry_run or not call:
        return

    if not (config.FROM_NUMBER and config.PUBLIC_URL):
        raise SystemExit("Set FROM_NUMBER (or OUTBOUND_1) and PUBLIC_URL in .env first.")
    from signalwire.rest import RestClient    # reads SIGNALWIRE_PROJECT_ID / _API_TOKEN / _SPACE
    client = RestClient()
    for contact in call:
        print(f"dialed {contact['appointment_id']}  call id {dial(contact, client)}")


if __name__ == "__main__":
    main()
