"""Handler tests, a clock fixture for the business-hours switch, and governance assertions on
the SWML that swaig-test dumps. send_sms and connect emit {"SWML": {...}} wrapping the verb;
swml_change_step() emits {"change_step": ...}.
"""
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

RECIPE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RECIPE))

import config  # noqa: E402
from app import AnsweringService, is_open, is_urgent, parse_hours  # noqa: E402

TZ = ZoneInfo(config.TZ)
WEDNESDAY_10AM = datetime(2026, 10, 28, 10, 0, tzinfo=TZ)
WEDNESDAY_10PM = datetime(2026, 10, 28, 22, 0, tzinfo=TZ)
SUNDAY_NOON = datetime(2026, 11, 1, 12, 0, tzinfo=TZ)
THANKSGIVING_10AM = datetime(2026, 11, 26, 10, 0, tzinfo=TZ)   # in data/holidays.json


def clock(at):
    return lambda: at


def acts(result):
    return result.to_dict().get("action", [])


def verbs(result):
    """The SWML verbs inside {"SWML": {...}} actions, e.g. {"send_sms": {...}}."""
    return [v for a in acts(result) if "SWML" in a for v in a["SWML"]["sections"]["main"]]


def rendered(at) -> dict:
    """Run the dynamic config callback for a call at time `at`, then render."""
    base = AnsweringService(clock=clock(at))
    copy = AnsweringService(clock=clock(at))      # stands in for the SDK's per-request copy
    base.per_call({}, {}, {}, copy)
    copy.reset_document()
    copy.add_verb("ai", {"prompt": {"text": "stub"}})   # what the SDK would add after hours
    return json.loads(copy.render_document()), copy


# --- the clock fixture switches between human SWML and AI SWML ----------------------

@pytest.mark.parametrize("at, office", [
    (WEDNESDAY_10AM, True), (WEDNESDAY_10PM, False), (SUNDAY_NOON, False), (THANKSGIVING_10AM, False),
])
def test_clock_switches_between_office_and_ai(at, office):
    doc, copy = rendered(at)
    main = [list(v)[0] for v in doc["sections"]["main"]]
    if office:
        assert main == ["connect", "hangup"]
        assert doc["sections"]["main"][0]["connect"]["to"] == config.OFFICE_NUMBER
    else:
        assert main == ["ai"]
        assert copy.swml_override is None


def test_hours_parser_and_edges():
    hours = parse_hours("mon-fri 09:00-17:00; sat 10:00-14:00")
    assert hours[0] == ("09:00", "17:00") and hours[5] == ("10:00", "14:00") and 6 not in hours
    assert is_open(datetime(2026, 10, 28, 9, 0, tzinfo=TZ), hours, [])
    assert not is_open(datetime(2026, 10, 28, 17, 0, tzinfo=TZ), hours, [])     # close is exclusive
    assert not is_open(datetime(2026, 10, 28, 9, 0, tzinfo=TZ), hours, ["2026-10-28"])


# --- the urgency rule ----------------------------------------------------------------

@pytest.mark.parametrize("text, urgent", [
    ("My basement is flooding", True),
    ("There's a gas smell in the kitchen", True),
    ("Pipe burst under the sink", True),
    ("I'd like a quote for a new water heater", False),
    ("Can someone call me about my invoice", False),
    ("Gasket question for my faucet", False),       # whole words only: "gasket" is not "gas"
])
def test_urgency_rule(text, urgent):
    assert is_urgent(text) is urgent


@pytest.fixture(scope="module")
def agent():
    return AnsweringService(clock=clock(WEDNESDAY_10PM))


DETAILS = {"name": "Pat Example", "callback_number": "5550142"}


def test_urgent_call_is_forwarded_to_on_call(agent):
    result = agent.submit_call({**DETAILS, "message": "Water heater is leaking everywhere"}, {})
    (verb,) = verbs(result)
    assert verb["connect"]["to"] == config.ONCALL_NUMBER
    assert verb["connect"]["from"] == config.FROM_NUMBER
    assert not any("change_step" in a for a in acts(result))


def test_routine_call_texts_the_owner_with_caller_details(agent):
    raw = {"caller_id_num": "+15550142"}
    result = agent.submit_call({**DETAILS, "message": "Quote for a new faucet"}, raw)
    (verb,) = verbs(result)
    sms = verb["send_sms"]
    assert sms["to_number"] == config.OWNER_NUMBER and sms["from_number"] == config.SMS_FROM
    for detail in ("Pat Example", "5550142", "+15550142", "Quote for a new faucet"):
        assert detail in sms["body"]
    assert [a["change_step"] for a in acts(result) if "change_step" in a] == ["wrap_up"]


def test_missing_details_are_asked_for(agent):
    result = agent.submit_call({"name": "Pat", "callback_number": "", "message": "hi"}, {})
    assert acts(result) == []
    assert "callback_number" in result.to_dict()["response"]


# --- governance: read the SWML exactly as swaig-test dumps it ----------------------

def dump(hours: str, tmp_path) -> dict:
    local = Path(sys.executable).with_name("swaig-test")
    exe = str(local) if local.exists() else (shutil.which("swaig-test") or "swaig-test")
    holidays = tmp_path / "holidays.json"
    holidays.write_text("[]")
    env = {**os.environ, "HOURS": hours, "HOLIDAYS_FILE": str(holidays)}
    out = subprocess.run([exe, str(RECIPE / "app.py"), "--dump-swml", "--raw"], env=env,
                         capture_output=True, text=True, check=True, cwd=RECIPE).stdout
    return json.loads(out)


def test_governance_business_hours_swml_has_no_ai(tmp_path):
    doc = dump("mon-sun 00:00-24:00", tmp_path)          # always open
    main = doc["sections"]["main"]
    assert not any("ai" in v for v in main)
    assert main[0]["connect"]["to"] == config.OFFICE_NUMBER


def test_governance_after_hours_model_cannot_route(tmp_path):
    doc = dump("mon 00:00-00:00", tmp_path)              # never open
    ai = next(v["ai"] for v in doc["sections"]["main"] if "ai" in v)
    tools = [f["function"] for f in ai["SWAIG"]["functions"]]
    assert tools == ["submit_call"]                       # no connect / SMS / forward tool
    steps = {s["name"]: s for s in ai["prompt"]["contexts"]["default"]["steps"]}
    assert steps["intake"]["functions"] == ["submit_call"] and steps["intake"]["valid_steps"] == []
    assert steps["wrap_up"]["functions"] == []
