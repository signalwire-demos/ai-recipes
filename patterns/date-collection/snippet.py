"""Date collection: the model passes the caller's raw phrase, the handler parses it.

parse_date() is standard library only. It understands numeric dates (1 1 70,
1/13/1970), month names and abbreviations, ordinals as words or
digits (first, twenty-first, 1st), "the first of January", and a small holiday
table. When the phrase could mean two dates it returns a question instead of
guessing.
"""
import calendar
import re
from datetime import date

from signalwire import FunctionResult

MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_name) if m}
MONTHS |= {m.lower(): i for i, m in enumerate(calendar.month_abbr) if m} | {"sept": 9}
_U = "first second third fourth fifth sixth seventh eighth ninth".split()
_T = "tenth eleventh twelfth thirteenth fourteenth fifteenth sixteenth seventeenth eighteenth nineteenth".split()
ORDINALS = {f"twenty {w}": 21 + i for i, w in enumerate(_U)} | {"thirty first": 31, "twentieth": 20,
            "thirtieth": 30} | {w: 10 + i for i, w in enumerate(_T)} | {w: 1 + i for i, w in enumerate(_U)}
HOLIDAYS = {"new years day": "january 1", "new years eve": "december 31", "christmas eve": "december 24",
            "christmas day": "december 25", "christmas": "december 25", "independence day": "july 4",
            "fourth of july": "july 4", "halloween": "october 31", "valentines day": "february 14"}


def parse_date(phrase: str, today: date | None = None) -> tuple[str | None, str | None]:
    """Return (ISO date, None) or (None, the question to ask the caller)."""
    s = re.sub(r"[^a-z0-9 ]", " ", phrase.lower().replace("'", "").replace("-", " "))
    s = re.sub(r"\b(\d+)(st|nd|rd|th)\b", r"\1", " ".join(s.split()))
    for words, value in [*HOLIDAYS.items(), *ORDINALS.items()]:  # longest phrases first
        s = re.sub(rf"\b{words}\b", str(value), s)
    nums = [int(t) for t in s.split() if t.isdigit()]
    month = next((MONTHS[t] for t in s.split() if t in MONTHS), None)
    if month is None and len(nums) >= 2:           # all digits: 1 1 70, 1/13/70, 13 1 70
        m, d = nums[:2]
        if m != d and max(m, d) <= 12:
            return None, f"Did you mean {calendar.month_name[m]} {d} or {calendar.month_name[d]} {m}?"
        month, nums = min(m, d), [max(m, d), *nums[2:]]  # a number over 12 can only be the day
    if month is None or not nums or nums[0] > 31:
        return None, "I didn't catch a date. What's the month, day and year?"
    day, year = nums[0], (nums[1:] or [None])[0]
    if year is None:
        return None, f"Which year for {calendar.month_name[month]} {day}?"
    year += (2000 if year <= (today or date.today()).year % 100 else 1900) if year < 100 else 0
    try:
        return date(year, month, day).isoformat(), None
    except ValueError:
        return None, "That date doesn't exist. What's the date again?"


def record_date(args, raw_data):
    iso, question = parse_date(str(args.get("phrase", "")))
    if question:
        return FunctionResult(f"Ask the caller: {question}")
    d = date.fromisoformat(iso)
    spoken = f"{calendar.month_name[d.month]} {d.day}, {d.year}"
    return FunctionResult(f"Got {spoken}. Read it back to the caller.").update_global_data({"date": iso})


# Register on any agent with agent.define_tool(**TOOL). The phrase is passed verbatim.
TOOL = dict(name="record_date", handler=record_date,
            description="Record a date. Pass the caller's exact words; do not reformat them.",
            parameters={"phrase": {"type": "string", "description": "The caller's words, e.g. 'Jan 1 70'"}},
            required=["phrase"])
