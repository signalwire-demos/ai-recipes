"""Handler tests (assert on FunctionResult actions) plus governance assertions on the
SWML that swaig-test dumps. Wire names: swml_change_step -> change_step,
update_global_data -> set_global_data."""
import json
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

RECIPE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RECIPE))

import config  # noqa: E402
import slots  # noqa: E402
from app import AbsenceAgent  # noqa: E402

TODAY = date(2026, 10, 30)  # a Friday
FULL = {"name": "Jamie Rivera", "id": "S0142", "org_type": "school", "reason": "flu",
        "start_date": "2026-11-02", "end_date": "2026-11-03"}


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch, tmp_path):
    monkeypatch.setattr(slots, "today", lambda: TODAY)
    monkeypatch.setattr(config, "REPORTS_DIR", tmp_path / "reports")


@pytest.fixture(scope="module")
def agent():
    return AbsenceAgent()


def acts(result, key):
    return [a[key] for a in result.to_dict().get("action", []) if key in a]


def saved(result):
    return acts(result, "set_global_data")[-1]["absence"]


# --- record_slots: grammar filling ----------------------------------------

def test_out_of_order_fragments_merge_across_turns(agent):
    gd = {"absence": {}}
    turns = [{"end_date": "Tuesday", "reason": "the flu"},          # dates first, name last
             {"start_date": "Monday", "org_type": "School"},
             {"id": "s 0 1 4 2"},
             {"name": "jamie rivera"}]
    for turn in turns:
        r = agent.record_slots(turn, {"global_data": gd})
        gd = {"absence": saved(r)}
    assert gd["absence"] == {**FULL, "reason": "the flu"}
    assert acts(r, "change_step") == ["confirm"]
    assert "Jamie Rivera, ID S 0 1 4 2, school absence on 2026-11-02 through 2026-11-03" in r.to_dict()["response"]


def test_everything_in_one_breath_goes_straight_to_confirm(agent):
    r = agent.record_slots({**FULL, "start_date": "today", "end_date": "today"}, {"global_data": {}})
    assert acts(r, "change_step") == ["confirm"]
    assert "on 2026-10-30, reason" in r.to_dict()["response"]


def test_missing_slots_block_the_step_change(agent):
    r = agent.record_slots({"name": "Jamie Rivera", "start_date": "November 2"}, {"global_data": {}})
    assert acts(r, "change_step") == []
    assert saved(r) == {"name": "Jamie Rivera", "start_date": "2026-11-02"}
    assert "id; org_type; reason; end_date" in r.to_dict()["response"]


def test_ambiguous_date_is_sent_back_for_clarification(agent):
    r = agent.record_slots({"start_date": "11 2"}, {"global_data": {"absence": {}}})
    assert acts(r, "change_step") == []
    assert "start_date" not in saved(r)
    assert "start_date: did you mean November 2 or February 11?" in r.to_dict()["response"]


@pytest.mark.parametrize("words", ["eleven two", "starting eleven two"])
def test_spoken_ambiguous_date_is_sent_back_too(agent, words):
    """Live call 5b015855: speech-to-text wrote "11 2" as "eleven two"."""
    r = agent.record_slots({"start_date": words}, {"global_data": {"absence": {}}})
    assert "start_date: did you mean November 2 or February 11?" in r.to_dict()["response"]


def test_one_day_absence_comes_from_the_callers_words(agent):
    r = agent.record_slots({"start_date": "monday", "end_date": "just that day"}, {"global_data": {"absence": {}}})
    assert saved(r)["end_date"] == "2026-11-02"
    later = agent.record_slots({"end_date": "same day"}, {"global_data": {"absence": {"start_date": "2026-11-03"}}})
    assert saved(later)["end_date"] == "2026-11-03"


@pytest.mark.parametrize("name", ["son", "my son", "Jamie"])
def test_a_relationship_or_first_name_alone_is_not_a_full_name(agent, name):
    """Live call d8c935db: the model sent name="son" and it was accepted."""
    r = agent.record_slots({"name": name}, {"global_data": {"absence": {}}})
    assert "name" not in saved(r) and "first and last name" in r.to_dict()["response"]


def test_governance_call_runs_on_the_configured_model(ai):
    assert ai["prompt"]["model"] == config.MODEL == "gpt-4.1-mini"


def test_end_date_is_not_filled_in_for_the_caller():
    """Live call 5b015855: the model passed end_date = start_date before the caller gave one."""
    desc = config.SLOTS["end_date"][0]
    assert "same as start" not in desc and "Leave it out until the caller says it" in desc


def test_invalid_value_keeps_the_previous_one(agent):
    r = agent.record_slots({"org_type": "gym", "id": "12"}, {"global_data": {"absence": {"org_type": "work"}}})
    assert saved(r) == {"org_type": "work"}
    assert "org_type: choose school or work" in r.to_dict()["response"]
    assert "id: an ID is" in r.to_dict()["response"]


def test_end_before_start_is_rejected(agent):
    r = agent.record_slots({**FULL, "start_date": "Nov 5", "end_date": "Nov 3"}, {"global_data": {}})
    assert acts(r, "change_step") == []
    assert "end_date" not in saved(r)
    assert "before the first day" in r.to_dict()["response"]


def test_correction_in_confirm_updates_the_summary(agent):
    r = agent.record_slots({"reason": "a dentist appointment"}, {"global_data": {"absence": FULL}})
    assert acts(r, "change_step") == ["confirm"]
    assert "a dentist appointment" in acts(r, "set_global_data")[-1]["absence_summary"]


@pytest.mark.parametrize("phrase,expected", [
    ("1 1 70", "1970-01-01"), ("Jan 1 70", "1970-01-01"), ("January first 1970", "1970-01-01"),
    ("first of January 1970", "1970-01-01"), ("New Year's Day 1970", "1970-01-01"),
    ("tomorrow", "2026-10-31"), ("monday", "2026-11-02"), ("friday", "2026-11-06"),
    ("the third of November", "2026-11-03"), ("11/13", "2026-11-13"),
    ("November two", "2026-11-02"), ("twenty one twelve", "2026-12-21"),
    ("November second twenty twenty six", "2026-11-02"), ("thirty one december", "2026-12-31"),
])
def test_dates(phrase, expected):
    assert slots.parse_date(phrase) == (expected, None)


# --- submit_report ----------------------------------------------------------

def test_submit_writes_the_report_and_ends(agent):
    r = agent.submit_report({}, {"global_data": {"absence": FULL}})
    assert acts(r, "change_step") == ["done"]
    files = list(config.REPORTS_DIR.glob("AB-*.json"))
    assert len(files) == 1
    record = json.loads(files[0].read_text())
    assert record == {"reference": files[0].stem, **FULL}


def test_submit_refuses_a_partial_report(agent):
    r = agent.submit_report({}, {"global_data": {"absence": {"name": "Jamie Rivera"}}})
    assert acts(r, "change_step") == ["collect"]
    assert not config.REPORTS_DIR.exists()


# --- governance: the SWML exactly as swaig-test dumps it --------------------

@pytest.fixture(scope="module")
def ai():
    exe = Path(sys.executable).with_name("swaig-test")
    exe = str(exe) if exe.exists() else (shutil.which("swaig-test") or "swaig-test")
    out = subprocess.run([exe, str(RECIPE / "app.py"), "--dump-swml", "--raw"],
                         capture_output=True, text=True, check=True, cwd=RECIPE).stdout
    return next(v["ai"] for v in json.loads(out)["sections"]["main"] if "ai" in v)


@pytest.fixture(scope="module")
def steps(ai):
    return {s["name"]: s for s in ai["prompt"]["contexts"]["default"]["steps"]}


def test_governance_collect_cannot_submit_or_navigate(steps):
    assert steps["collect"]["functions"] == ["record_slots"]
    assert "submit_report" not in steps["collect"]["functions"]
    assert steps["collect"]["valid_steps"] == []


def test_governance_confirm_and_done(steps):
    assert steps["confirm"]["functions"] == ["record_slots", "submit_report"]
    assert steps["confirm"]["valid_steps"] == []
    assert steps["done"]["functions"] == []


def test_governance_every_slot_is_optional_in_the_tool_schema(ai):
    fn = next(f for f in ai["SWAIG"]["functions"] if f["function"] == "record_slots")
    assert set(fn["parameters"]["properties"]) == set(config.SLOTS)
    assert not fn["parameters"].get("required")
