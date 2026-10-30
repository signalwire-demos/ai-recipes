"""Slot validators and the grammar-filling merge.

Copied from patterns/grammar-filling and patterns/date-collection (recipes don't
import from patterns/). Changes from the patterns: parse_date takes a default
year and understands today / tomorrow / weekday names, because absences are
reported for the next few days.
"""
import calendar
import re
from datetime import date, timedelta

MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_name) if m}
MONTHS |= {m.lower(): i for i, m in enumerate(calendar.month_abbr) if m} | {"sept": 9}
WEEKDAYS = {d.lower(): i for i, d in enumerate(calendar.day_name)}
_U = "first second third fourth fifth sixth seventh eighth ninth".split()
_T = "tenth eleventh twelfth thirteenth fourteenth fifteenth sixteenth seventeenth eighteenth nineteenth".split()
ORDINALS = {f"twenty {w}": 21 + i for i, w in enumerate(_U)} | {"thirty first": 31, "twentieth": 20,
            "thirtieth": 30} | {w: 10 + i for i, w in enumerate(_T)} | {w: 1 + i for i, w in enumerate(_U)}
_ONES = "one two three four five six seven eight nine".split()
_TEENS = "ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split()
# Spoken numbers, as speech-to-text writes them ("eleven two" on live call 5b015855). Longest first.
CARDINALS = {f"twenty {w}": 21 + i for i, w in enumerate(_ONES)} | {"thirty one": 31, "twenty": 20,
             "thirty": 30} | {w: 10 + i for i, w in enumerate(_TEENS)} | {w: 1 + i for i, w in enumerate(_ONES)}
HOLIDAYS = {"new years day": "january 1", "new years eve": "december 31", "christmas eve": "december 24",
            "christmas day": "december 25", "christmas": "december 25", "independence day": "july 4",
            "fourth of july": "july 4", "halloween": "october 31", "valentines day": "february 14"}


def today() -> date:
    return date.today()  # tests patch this


def parse_date(phrase: str) -> tuple[str | None, str | None]:
    """Return (ISO date, None) or (None, the question to ask the caller)."""
    now = today()
    s = re.sub(r"[^a-z0-9 ]", " ", phrase.lower().replace("'", "").replace("-", " "))
    s = re.sub(r"\b(\d+)(st|nd|rd|th)\b", r"\1", " ".join(s.split()))
    words = s.split()
    for rel, days in (("today", 0), ("tomorrow", 1)):
        if rel in words:
            return (now + timedelta(days)).isoformat(), None
    day_name = next((w for w in words if w in WEEKDAYS), None)
    if day_name and not any(w in MONTHS or w.isdigit() for w in words):   # "Monday" = the next one
        return (now + timedelta((WEEKDAYS[day_name] - now.weekday()) % 7 or 7)).isoformat(), None
    s = re.sub(r"\btwenty (twenty|thirty)( (one|two|three|four|five|six|seven|eight|nine))?\b", " ", s)  # a spoken year
    for text, value in [*HOLIDAYS.items(), *ORDINALS.items(), *CARDINALS.items()]:   # longest phrases first
        s = re.sub(rf"\b{text}\b", str(value), s)
    nums = [int(t) for t in s.split() if t.isdigit()]
    month = next((MONTHS[t] for t in s.split() if t in MONTHS), None)
    if month is None and len(nums) >= 2:                                  # all digits: 3 4 26
        m, d = nums[:2]
        if m != d and max(m, d) <= 12:
            return None, f"did you mean {calendar.month_name[m]} {d} or {calendar.month_name[d]} {m}?"
        month, nums = min(m, d), [max(m, d), *nums[2:]]                   # over 12 can only be the day
    if month is None or not nums or nums[0] > 31:
        return None, "which date? Say the month and day."
    day, year = nums[0], (nums[1:] or [now.year])[0]                      # no year: this year
    year += (2000 if year <= now.year % 100 else 1900) if year < 100 else 0
    try:
        return date(year, month, day).isoformat(), None
    except ValueError:
        return None, "that date doesn't exist. Which date?"


def one_of(*choices):
    return lambda raw: (raw, None) if raw in choices else (None, f"choose {' or '.join(choices)}")


def matches(pattern: str, hint: str, fmt=str):
    def check(raw):
        value = fmt(raw)
        return (value, None) if re.fullmatch(pattern, value, re.I) else (None, hint)
    return check


def fill(saved: dict, incoming: dict, slots: dict) -> tuple[dict, list[str], dict]:
    """Merge one turn into the saved slots. Return (merged, missing names, {slot: question})."""
    merged, problems = dict(saved), {}
    for name, raw in incoming.items():
        if name in slots and raw not in (None, ""):
            value, problem = slots[name](" ".join(str(raw).lower().split()))
            if problem is None:
                merged[name] = value
            else:
                problems[name] = problem
    if merged.get("start_date") and merged.get("end_date") and merged["end_date"] < merged["start_date"]:
        problems["end_date"] = "that's before the first day. When is the last day?"
        merged.pop("end_date")
    return merged, [s for s in slots if s not in merged], problems
