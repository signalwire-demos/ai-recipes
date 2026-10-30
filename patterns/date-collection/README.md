# Date collection

**Problem.** Callers say dates as "1 1 70", "Jan 1 70", "January first 1970", "first of
January 1970" or "New Year's Day 1970". If the model reformats them, it guesses, and its
guesses about "1 2 70" or a two-digit year aren't auditable.

**Snippet** ([snippet.py](snippet.py), standard library plus a holiday table):

```python
def parse_date(phrase, today=None):
    s = ...  # lowercase, drop punctuation and "1st" suffixes, holidays and ordinal words -> numbers
    nums = [int(t) for t in s.split() if t.isdigit()]
    month = next((MONTHS[t] for t in s.split() if t in MONTHS), None)
    if month is None and len(nums) >= 2:           # all digits: 1 1 70, 1/13/70, 13 1 70
        m, d = nums[:2]
        if m != d and max(m, d) <= 12:
            return None, f"Did you mean {calendar.month_name[m]} {d} or {calendar.month_name[d]} {m}?"
        month, nums = min(m, d), [max(m, d), *nums[2:]]
    ...
    return date(year, month, day).isoformat(), None
```

`record_date` wraps it: a question goes back to the model to ask, and a date is stored in
`global_data["date"]` as ISO. Register it with `agent.define_tool(**TOOL)`.

**Why it holds.** The tool's description tells the model to pass the caller's exact words, so
the parse is in code you can test. It never guesses: a numeric date where both numbers could be
the month (`1 2 70`), a date with no year, or an impossible date (`Feb 30`) comes back as a
question. A two-digit year is never in the future (`70` is 1970, `26` is 2026). Add holidays
to `HOLIDAYS`. To prefer one numeric order instead of asking, change the ambiguity branch.

**Test.** `pytest patterns/date-collection`: all five backlog phrasings resolve to
`1970-01-01`, and ambiguous, incomplete and impossible dates are sent back.

**Used by.** #1, #12, #20.
