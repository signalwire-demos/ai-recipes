"""Code-side checks for every claim answer. The model passes the caller's words; code decides.

Each check returns (value, None) when the answer is accepted, or (None, reason) when it is
rejected. The reason is spoken back as a re-ask. The same checks run twice: as per-question
tools during the gather, and again in submit_claim before anything is filed, because a
gather_submit answer is still caller input typed in by the model.

parse_date() is copied from patterns/date-collection (standard library only), with three
changes for incident dates: an ISO date is accepted as is, "today"/"yesterday" resolve, and a
date with no year means its most recent past occurrence.
"""
import calendar
import re
from datetime import date, timedelta

import config

# --- dates (copied from patterns/date-collection/snippet.py) ------------------
MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_name) if m}
MONTHS |= {m.lower(): i for i, m in enumerate(calendar.month_abbr) if m} | {"sept": 9}
_U = "first second third fourth fifth sixth seventh eighth ninth".split()
_T = "tenth eleventh twelfth thirteenth fourteenth fifteenth sixteenth seventeenth eighteenth nineteenth".split()
ORDINALS = {f"twenty {w}": 21 + i for i, w in enumerate(_U)} | {"thirty first": 31, "twentieth": 20,
            "thirtieth": 30} | {w: 10 + i for i, w in enumerate(_T)} | {w: 1 + i for i, w in enumerate(_U)}
HOLIDAYS = {"new years day": "january 1", "new years eve": "december 31", "christmas eve": "december 24",
            "christmas day": "december 25", "christmas": "december 25", "independence day": "july 4",
            "fourth of july": "july 4", "halloween": "october 31", "valentines day": "february 14"}


def parse_date(phrase: str, today: date) -> tuple[str | None, str | None]:
    """Return (ISO date, None) or (None, the question to ask the caller)."""
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", phrase.strip()):
        try:
            return date.fromisoformat(phrase.strip()).isoformat(), None
        except ValueError:
            return None, "That date doesn't exist. What's the date again?"
    s = re.sub(r"[^a-z0-9 ]", " ", phrase.lower().replace("'", "").replace("-", " "))
    s = re.sub(r"\b(\d+)(st|nd|rd|th)\b", r"\1", " ".join(s.split()))
    for word, back in (("today", 0), ("yesterday", 1)):
        if re.search(rf"\b{word}\b", s):
            return (today - timedelta(days=back)).isoformat(), None
    for words, value in [*HOLIDAYS.items(), *ORDINALS.items()]:  # longest phrases first
        s = re.sub(rf"\b{words}\b", str(value), s)
    nums = [int(t) for t in s.split() if t.isdigit()]
    month = next((MONTHS[t] for t in s.split() if t in MONTHS), None)
    if month is None and len(nums) >= 2:           # all digits: 10 28 26, 10/28/2026
        m, d = nums[:2]
        if m != d and max(m, d) <= 12:
            return None, f"Did you mean {calendar.month_name[m]} {d} or {calendar.month_name[d]} {m}?"
        month, nums = min(m, d), [max(m, d), *nums[2:]]  # a number over 12 can only be the day
    if month is None or not nums or nums[0] > 31:
        return None, "I didn't catch a date. What's the month and day?"
    day, year = nums[0], (nums[1:] or [None])[0]
    if year is None:                               # no year: the most recent one not in the future
        year = today.year if (month, day) <= (today.month, today.day) else today.year - 1
    year += (2000 if year <= today.year % 100 else 1900) if year < 100 else 0
    try:
        return date(year, month, day).isoformat(), None
    except ValueError:
        return None, "That date doesn't exist. What's the date again?"


# --- the checks ---------------------------------------------------------------
_DIGITS = {"zero": "0", "oh": "0", "one": "1", "two": "2", "three": "3", "four": "4",
           "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9"}
YES = {"yes", "yeah", "yep", "true", "injured", "hurt"}
NO = {"no", "nope", "false", "nobody", "noone", "none"}
UNSURE = {"maybe", "sure", "know", "unsure", "possibly"}


def check_policy_number(words: str) -> tuple[str | None, str | None]:
    """'P O L zero one zero one', 'my policy is pol-0101' -> 'POL-0101'."""
    prefix, n = config.POLICY_PREFIX, config.POLICY_DIGITS
    s = re.sub(r"[a-z]+", lambda m: _DIGITS.get(m[0], m[0]), str(words).lower())
    head = r"\W*".join(re.escape(c) for c in prefix.lower())
    m = re.search(rf"(?<![a-z0-9]){head}\W*((?:\d\W*){{{n}}})(?!\W*\d)", s)
    if m:
        return f"{prefix}-{re.sub(r'\D', '', m[1])}", None
    return None, (f"That isn't a policy number. It starts with {' '.join(prefix)} and then "
                  f"{n} digits. What is the policy number?")


def check_incident_date(words: str, today: date | None = None) -> tuple[str | None, str | None]:
    """A real calendar date, not in the future, not older than MAX_CLAIM_AGE_DAYS."""
    today = today or date.today()
    if check_policy_number(words)[0] or re.search(rf"\b{config.POLICY_PREFIX.lower()}\b", str(words).lower()):
        return None, "That sounds like the policy number. On what date did the incident happen?"
    iso, question = parse_date(str(words), today)
    if question:
        return None, question
    d = date.fromisoformat(iso)
    if d > today:
        return None, "That date is in the future. On what date did the incident happen?"
    if (today - d).days > config.MAX_CLAIM_AGE_DAYS:
        return None, "That's too long ago to file by phone. On what date did the incident happen?"
    return iso, None


_DATE_WORDS = set(MONTHS) | set(" ".join(ORDINALS).split()) | {"the", "of", "on", "today", "yesterday", "st", "nd", "rd", "th"}


def check_location(words: str) -> tuple[str | None, str | None]:
    text = " ".join(str(words).split())
    tokens = re.findall(r"[a-z]+|\d+", text.lower())
    if (len("".join(t for t in tokens if t.isalpha())) < 3 or check_policy_number(text)[0]
            or set(tokens) <= YES | NO):
        return None, "Where did the incident happen? A street, intersection or city is fine."
    if all(t.isdigit() or t in _DATE_WORDS for t in tokens):
        return None, "That sounds like a date. Where did the incident happen?"
    return text, None


def check_description(words: str) -> tuple[str | None, str | None]:
    text = " ".join(str(words).split())
    if len(text.split()) < 2:
        return None, "In a sentence or two, what happened?"
    return text, None


def check_injuries(answer) -> tuple[bool | None, str | None]:
    if isinstance(answer, bool):
        return answer, None
    words = set(re.findall(r"[a-z]+", str(answer).lower().replace("no one", "noone")))
    if words & UNSURE:
        pass
    elif words & NO:                 # "no", "nobody was hurt"
        return False, None
    elif words & YES:                # "yes", "my passenger was hurt"
        return True, None
    return None, "Please answer yes or no: was anyone hurt?"


def spoken_date(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{calendar.month_name[d.month]} {d.day}, {d.year}"


CHECKS = {"policy_number": check_policy_number, "incident_date": check_incident_date,
          "location": check_location, "description": check_description,
          "injuries": check_injuries}
