"""Calendar backend: a local .ics file (RFC 5545 subset: VEVENT with UID, TZID times, STATUS).

Swap this module for a Google Calendar adapter by keeping the same three functions.
"""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import config

FMT = "%Y%m%dT%H%M%S"


def _read() -> list[str]:
    return config.CALENDAR_FILE.read_text().splitlines()


def _write(lines: list[str]) -> None:
    config.CALENDAR_FILE.write_text("\r\n".join(lines) + "\r\n")


def _event_span(lines: list[str], uid: str) -> tuple[int, int] | None:
    start = None
    for i, line in enumerate(lines):
        if line == "BEGIN:VEVENT":
            start = i
        elif line == f"UID:{uid}" and start is not None:
            return start, lines.index("END:VEVENT", i)
    return None


def _parse_time(value: str) -> datetime:      # "DTSTART;TZID=America/Chicago:20270113T140000"
    params, _, stamp = value.partition(":")
    tz = params.split("TZID=", 1)[1] if "TZID=" in params else "UTC"
    return datetime.strptime(stamp.rstrip("Z"), FMT).replace(tzinfo=ZoneInfo(tz))


def get_event(uid: str) -> dict | None:
    lines = _read()
    span = _event_span(lines, uid)
    if not span:
        return None
    ev = {"uid": uid}
    for line in lines[span[0]:span[1]]:
        key = line.split(":", 1)[0].split(";", 1)[0]
        if key in ("DTSTART", "DTEND"):
            ev[key.lower()[2:]] = _parse_time(line)
        elif key in ("SUMMARY", "STATUS"):
            ev[key.lower()] = line.split(":", 1)[1]
    return ev


def _update(uid: str, fields: dict[str, str]) -> None:
    lines = _read()
    start, end = _event_span(lines, uid)
    for i in range(start, end):
        key = lines[i].split(":", 1)[0].split(";", 1)[0]
        if key in fields:
            lines[i] = fields[key]
    _write(lines)


def set_status(uid: str, status: str) -> None:       # CONFIRMED | CANCELLED
    _update(uid, {"STATUS": f"STATUS:{status}"})


def reschedule(uid: str, new_start: datetime) -> None:
    ev = get_event(uid)
    tz = ev["start"].tzinfo.key
    new_end = new_start + (ev["end"] - ev["start"])
    _update(uid, {"DTSTART": f"DTSTART;TZID={tz}:{new_start.strftime(FMT)}",
                  "DTEND": f"DTEND;TZID={tz}:{new_end.strftime(FMT)}",
                  "STATUS": "STATUS:CONFIRMED"})


def spoken(start: datetime) -> str:
    return start.strftime("%A, %B %-d at %-I:%M %p").replace(":00 ", " ")


def parse_local(text: str, tz) -> datetime | None:
    try:
        return datetime.strptime(text.strip(), "%Y-%m-%d %H:%M").replace(tzinfo=tz)
    except ValueError:
        return None


def is_open_slot(start: datetime, now: datetime) -> bool:
    lo, hi = config.OPEN_HOURS
    return (start > now + timedelta(hours=1) and start.weekday() in config.OPEN_WEEKDAYS
            and lo <= start.hour < hi and start.minute in (0, 30))
