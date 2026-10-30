import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent)); sys.modules.pop("snippet", None)  # noqa: E702
from snippet import parse_date, record_date  # noqa: E402

TODAY = date(2026, 10, 30)
BACKLOG = ["1 1 70", "Jan 1 70", "January first 1970", "first of January 1970", "New Year's Day 1970"]


@pytest.mark.parametrize("phrase", BACKLOG)
def test_all_five_backlog_phrasings_resolve_to_1970_01_01(phrase):
    assert parse_date(phrase, TODAY) == ("1970-01-01", None)


@pytest.mark.parametrize("phrase,expected", [
    ("Jan 1st, 1970", "1970-01-01"),
    ("the twenty-first of March 1999", "1999-03-21"),
    ("13 1 70", "1970-01-13"),            # 13 can only be the day
    ("1/13/1970", "1970-01-13"),
    ("christmas eve 2025", "2025-12-24"),
    ("12 25 26", "2026-12-25"),           # 2-digit year at or before this year: 20xx
    ("march 3 27", "1927-03-03"),         # after this year: 19xx
])
def test_other_phrasings(phrase, expected):
    assert parse_date(phrase, TODAY) == (expected, None)


def test_ambiguous_numeric_date_asks_back():
    iso, question = parse_date("1 2 70", TODAY)
    assert iso is None
    assert question == "Did you mean January 2 or February 1?"


@pytest.mark.parametrize("phrase,fragment", [
    ("March 3", "Which year"), ("next week", "didn't catch"), ("January 1970", "didn't catch"),
    ("Feb 30 2020", "doesn't exist"), ("", "didn't catch"),
])
def test_incomplete_or_invalid_dates_ask_back(phrase, fragment):
    iso, question = parse_date(phrase, TODAY)
    assert iso is None and fragment in question


def test_handler_stores_iso_date_in_global_data():
    out = record_date({"phrase": "New Year's Day 1970"}, {}).to_dict()
    assert out["action"] == [{"set_global_data": {"date": "1970-01-01"}}]
    assert "January 1, 1970" in out["response"]


def test_handler_does_not_store_an_ambiguous_date():
    out = record_date({"phrase": "1 2 70"}, {}).to_dict()
    assert "action" not in out or out["action"] == []
    assert "January 2 or February 1" in out["response"]
