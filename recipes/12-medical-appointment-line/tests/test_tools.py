"""Tests for the medical appointment line.

1. Every handler is called directly with fixture args / raw_data; assertions are on the
   FunctionResult actions. Wire names: swml_change_step() -> "change_step",
   update_global_data() -> "set_global_data", record_call() -> "SWML" wrapping record_call.
2. Governance assertions run against the SWML exactly as swaig-test dumps it.
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

RECIPE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RECIPE))

import config  # noqa: E402
from app import MedicalAppointmentAgent  # noqa: E402

SCHEDULING_TOOLS = {"find_slots", "book_slot", "hold_slot"}


@pytest.fixture
def agent():
    return MedicalAppointmentAgent()  # fresh agent per test: no slots taken


def actions(result):
    return result.to_dict().get("action", [])


def find(acts, key):
    return [a[key] for a in acts if key in a]


def swml_verbs(acts):
    return [verb for a in find(acts, "SWML") for v in a["sections"]["main"] for verb in v]


GRANTED = {"global_data": {"consent": {"granted": True}}}
DECLINED = {"global_data": {"consent": {"granted": False}}}


# --- consent gate -----------------------------------------------------------

def test_consent_granted_records_and_moves_to_schedule(agent):
    acts = actions(agent.record_consent({"answer": "yes"}, {}))
    assert swml_verbs(acts) == ["record_call"]
    assert find(acts, "change_step") == ["schedule"]
    data = find(acts, "set_global_data")[0]
    assert data["recorded"] is True
    assert data["consent"]["granted"] is True
    assert data["consent"]["disclosure_version"] == config.DISCLOSURE_VERSION
    assert data["consent"]["time"]


def test_consent_granted_starts_recording_before_step_change(agent):
    acts = actions(agent.record_consent({"answer": "yes"}, {}))
    keys = [next(iter(a)) for a in acts]
    assert keys.index("SWML") < keys.index("change_step")


def test_consent_declined_does_not_record(agent):
    acts = actions(agent.record_consent({"answer": "no"}, {}))
    assert "record_call" not in swml_verbs(acts)
    assert find(acts, "SWML") == []
    assert find(acts, "change_step") == ["schedule_limited"]
    assert find(acts, "set_global_data")[0]["recorded"] is False


@pytest.mark.parametrize("args", [{"answer": "maybe"}, {"answer": "true"}, {"answer": None}, {"answer": 1},
                                  {"answer": ""}, {}, {"granted": True}])
def test_ambiguous_consent_neither_records_nor_moves(agent, args):
    assert actions(agent.record_consent(args, {})) == []


def test_consent_no_is_case_insensitive_and_routes_to_limited(agent):
    acts = actions(agent.record_consent({"answer": " No "}, {}))
    assert find(acts, "SWML") == []
    assert find(acts, "change_step") == ["schedule_limited"]


def test_record_consent_schema_offers_an_explicit_no(swml):
    """Regression (live call 0a692691): with a boolean `granted`, the model never submitted a "no";
    it kept re-asking and told the caller the call would be recorded anyway. The answer is now an
    explicit yes/no enum, and the tool description says a no must be submitted too."""
    ai = next(v["ai"] for v in swml["sections"]["main"] if "ai" in v)
    fn = next(f for f in ai["SWAIG"]["functions"] if f["function"] == "record_consent")
    answer = fn["parameters"]["properties"]["answer"]
    assert answer["enum"] == ["yes", "no"]
    assert fn["parameters"]["required"] == ["answer"]
    assert "no" in fn["description"].lower() and "declined" in fn["description"].lower()


# --- scheduling -------------------------------------------------------------

def test_find_slots_filters_by_day(agent):
    text = agent.find_slots({"day": "monday"}, {}).to_dict()["response"]
    assert "S-0101" in text and "S-0102" in text and "S-0103" not in text


def test_find_slots_unknown_day(agent):
    result = agent.find_slots({"day": "someday"}, {})
    assert actions(result) == []
    assert "No open slots" in result.to_dict()["response"]


def test_book_slot_books_and_wraps_up(agent):
    acts = actions(agent.book_slot({"slot_id": "s-0103"}, GRANTED))
    assert find(acts, "set_global_data")[0]["booking"]["status"] == "booked"
    assert find(acts, "change_step") == ["wrap_up"]
    assert "S-0103" not in agent.find_slots({}, {}).to_dict()["response"]


def test_book_slot_refuses_without_recorded_consent(agent):
    for raw in (DECLINED, {}):
        result = agent.book_slot({"slot_id": "S-0101"}, raw)
        assert actions(result) == []
    assert "S-0101" in agent.find_slots({}, {}).to_dict()["response"]  # not taken


def test_book_slot_taken_or_unknown(agent):
    agent.book_slot({"slot_id": "S-0101"}, GRANTED)
    assert actions(agent.book_slot({"slot_id": "S-0101"}, GRANTED)) == []
    assert actions(agent.book_slot({"slot_id": "S-9999"}, GRANTED)) == []


def test_hold_slot_holds_and_wraps_up(agent):
    acts = actions(agent.hold_slot({"slot_id": "S-0104"}, DECLINED))
    assert find(acts, "set_global_data")[0]["booking"]["status"] == "held"
    assert find(acts, "change_step") == ["wrap_up"]
    assert "record_call" not in swml_verbs(acts)


# --- audit record -----------------------------------------------------------

def test_on_summary_writes_audit_with_disclosure_version(agent, tmp_path, monkeypatch):
    audit = tmp_path / "audit.jsonl"
    monkeypatch.setattr(config, "AUDIT_FILE", audit)
    gd = {"consent": {"granted": True, "time": "2026-10-30T15:00:00+00:00", "disclosure_version": "v-test"},
          "recorded": True, "booking": {"slot_id": "S-0101", "status": "booked", "summary": "Booked ..."}}
    agent.on_summary({"outcome": "booked"}, {"call_id": "c-1", "global_data": gd,
                                             "caller_id_number": "+15550142"})
    record = json.loads(audit.read_text().splitlines()[-1])
    assert record["disclosure_version"] == "v-test"
    assert record["consent_granted"] is True
    assert record["consent_time"] == "2026-10-30T15:00:00+00:00"
    assert record["booking"] == {"slot_id": "S-0101", "status": "booked"}
    assert "+15550142" not in audit.read_text()  # no caller identifiers in the audit trail


def test_on_summary_without_consent_still_audits(agent, tmp_path, monkeypatch):
    audit = tmp_path / "audit.jsonl"
    monkeypatch.setattr(config, "AUDIT_FILE", audit)
    agent.on_summary(None, {"call_id": "c-2", "global_data": {}})
    record = json.loads(audit.read_text())
    assert record["consent_granted"] is None
    assert record["recorded"] is False
    assert record["disclosure_version"] == config.DISCLOSURE_VERSION


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


def steps_of(swml_doc):
    ai = next(v["ai"] for v in swml_doc["sections"]["main"] if "ai" in v)
    return {s["name"]: s for s in ai["prompt"]["contexts"]["default"]["steps"]}


def test_governance_consent_step_has_only_record_consent(swml):
    consent = steps_of(swml)["consent"]
    assert consent["functions"] == ["record_consent"]
    assert not SCHEDULING_TOOLS & set(consent["functions"])
    assert consent["valid_steps"] == []  # no next_step tool: only the handler opens the gate


def test_governance_disclosure_is_in_consent_step_text(swml):
    assert config.DISCLOSURE_TEXT in steps_of(swml)["consent"]["text"]


def test_governance_unrecorded_path_cannot_book(swml):
    steps = steps_of(swml)
    assert "book_slot" not in steps["schedule_limited"]["functions"]
    assert "book_slot" in steps["schedule"]["functions"]
    assert steps["wrap_up"]["functions"] == []


def test_governance_nothing_records_before_consent(swml):
    verbs = [next(iter(v)) for v in swml["sections"]["main"]]
    assert "record_call" not in verbs


def test_governance_wrap_up_has_no_navigation(swml):
    """Regression (live call 5527f302): wrap_up had no valid_steps, so the model got a next_step
    tool, called next_step("next") nine times ("next not found"), and the platform flagged a loop."""
    assert steps_of(swml)["wrap_up"]["valid_steps"] == []
