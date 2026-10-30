"""Tests for the reservation line.

1. book_table is called directly with fixture args; assertions are on the
   FunctionResult actions (wire names: change_step, set_global_data).
2. Governance assertions read the SWML exactly as swaig-test dumps it.
"""
import json
import shutil
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

RECIPE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RECIPE))

import config  # noqa: E402
from app import ReservationAgent, add_today  # noqa: E402


def next_weekday(name: str) -> str:
    """The next date (from tomorrow) that falls on the given weekday."""
    d = date.today() + timedelta(days=1)
    while d.strftime("%A").lower() != name:
        d += timedelta(days=1)
    return d.isoformat()


@pytest.fixture(scope="module")
def agent():
    return ReservationAgent()


@pytest.fixture(autouse=True)
def sink(tmp_path, monkeypatch):
    path = tmp_path / "reservations.json"
    monkeypatch.setattr(config, "RESERVATIONS_FILE", path)
    return path


def booking(**overrides):
    args = {"name": "Dana Example", "party_size": 4, "date": next_weekday("friday"),
            "time": "19:30", "phone": "(555) 555-0142"}
    args.update(overrides)
    return args


def actions(result):
    return result.to_dict().get("action", [])


def find(acts, key):
    return [a[key] for a in acts if key in a]


def rows(path):
    return json.loads(path.read_text()) if path.exists() else []


# --- handler: the happy path ------------------------------------------------

def test_valid_booking_writes_one_row_and_changes_step(agent, sink):
    acts = actions(agent.book_table(booking(), {}))
    assert find(acts, "change_step") == ["confirmed"]
    saved = rows(sink)
    assert len(saved) == 1
    assert saved[0]["name"] == "Dana Example"
    assert saved[0]["party_size"] == 4
    assert saved[0]["phone"] == "5555550142"
    # the confirmed step reads exactly what was written
    assert find(acts, "set_global_data") == [{"booking": saved[0]}]


def test_second_booking_appends(agent, sink):
    agent.book_table(booking(), {})
    agent.book_table(booking(name="Lee Example", time="18:00"), {})
    assert [r["name"] for r in rows(sink)] == ["Dana Example", "Lee Example"]


def test_party_at_the_limit_is_accepted(agent, sink):
    acts = actions(agent.book_table(booking(party_size=config.MAX_PARTY), {}))
    assert find(acts, "change_step") == ["confirmed"]


# --- handler: rejections keep the call in take_booking -----------------------

@pytest.mark.parametrize("overrides, phrase", [
    ({"party_size": config.MAX_PARTY + 1}, "at most"),
    ({"party_size": 0}, "at least one"),
    ({"party_size": "lots"}, "must be a number"),
    ({"date": next_weekday("monday")}, "closed on Mondays"),
    ({"time": "16:30"}, "we seat from"),                 # before opening
    ({"time": "22:30"}, "we seat from"),                 # after last seating (23:00 - 60)
    ({"date": (date.today() - timedelta(days=1)).isoformat()}, "in the past"),
    ({"date": (date.today() + timedelta(days=config.BOOKING_WINDOW_DAYS + 7)).isoformat()},
     "days ahead"),
    ({"date": "next friday"}, "YYYY-MM-DD"),
    ({"time": "7pm"}, "HH:MM"),
    ({"phone": "555"}, "phone number"),
    ({"name": "  "}, "need a name"),
])
def test_rejected_request_does_not_advance_or_write(agent, sink, overrides, phrase):
    result = agent.book_table(booking(**overrides), {})
    assert actions(result) == []          # no change_step, no global_data
    assert phrase in result.to_dict()["response"]
    assert rows(sink) == []


def test_today_is_injected_per_request():
    copy = ReservationAgent()
    add_today({}, {}, {}, copy)
    assert copy._global_data["today"] == date.today().isoformat()


# --- governance: read the SWML exactly as swaig-test dumps it ---------------

def swaig_test_bin() -> str:
    local = Path(sys.executable).with_name("swaig-test")
    return str(local) if local.exists() else (shutil.which("swaig-test") or "swaig-test")


@pytest.fixture(scope="module")
def swml():
    out = subprocess.run(
        [swaig_test_bin(), str(RECIPE / "app.py"), "--dump-swml", "--raw"],
        capture_output=True, text=True, check=True, cwd=RECIPE,
    ).stdout
    return json.loads(out)


def ai_of(swml_doc):
    return next(v["ai"] for v in swml_doc["sections"]["main"] if "ai" in v)


def steps_of(swml_doc):
    return {s["name"]: s for s in ai_of(swml_doc)["prompt"]["contexts"]["default"]["steps"]}


def test_governance_confirmed_has_no_functions(swml):
    assert steps_of(swml)["confirmed"]["functions"] == []


def test_governance_confirmed_is_the_end_with_no_next_step(swml):
    confirmed = steps_of(swml)["confirmed"]
    assert confirmed["valid_steps"] == [] and confirmed["end"] is True


def test_governance_take_booking_exposes_only_book_table(swml):
    step = steps_of(swml)["take_booking"]
    assert step["functions"] == ["book_table"]
    assert step["valid_steps"] == []      # no next_step tool: only the handler moves the call


def test_governance_book_table_is_the_only_tool(swml):
    assert [f["function"] for f in ai_of(swml)["SWAIG"]["functions"]] == ["book_table"]
