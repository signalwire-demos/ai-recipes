"""Handler tests, dialer filtering, and governance against the dumped SWML.

Every test works on temp copies of data/, so the committed fixtures never change.
"""
import json
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

import pytest

RECIPE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RECIPE))

import calendar_ics as cal  # noqa: E402
import config  # noqa: E402
import contacts  # noqa: E402
import dialer  # noqa: E402
from app import ReminderAgent  # noqa: E402

UTC = ZoneInfo("UTC")
RIGHT = {"global_data": {"appointment_id": "A-0101", "first_name": "Jordan"}}
SECRET_DETAILS = ["Dental cleaning", "Dr. Lee", "January", "10 AM", "2027"]


@pytest.fixture(autouse=True)
def data(tmp_path, monkeypatch):
    for name, attr in [("appointments.csv", "APPOINTMENTS_FILE"), ("dnc.txt", "DNC_FILE"),
                       ("calendar.ics", "CALENDAR_FILE")]:
        shutil.copy(RECIPE / "data" / name, tmp_path / name)
        monkeypatch.setattr(config, attr, tmp_path / name)
    return tmp_path


@pytest.fixture(scope="module")
def agent():
    return ReminderAgent()


def act(result):
    return result.to_dict().get("action", [])


def find(acts, key):
    return [a[key] for a in acts if key in a]


def text(result):
    return json.dumps(result.to_dict())


# --- confirm_identity -------------------------------------------------------

def test_right_person_gets_details_and_moves_to_manage(agent):
    acts = act(agent.confirm_identity({"is_contact": True}, RIGHT))
    assert find(acts, "set_global_data") == [{"appointment": {
        "summary": "Dental cleaning with Dr. Lee", "when": "Tuesday, January 12 at 10 AM"}}]
    assert find(acts, "change_step") == ["manage"]


@pytest.mark.parametrize("args,raw", [
    ({"is_contact": False}, RIGHT),
    ({"is_contact": "yes"}, RIGHT),                       # not a real boolean
    ({"is_contact": True}, {"global_data": {}}),           # no appointment on this call
])
def test_wrong_person_never_hears_details(agent, args, raw):
    result = agent.confirm_identity(args, raw)
    out = text(result)
    for detail in SECRET_DETAILS:
        assert detail not in out
    assert find(act(result), "set_global_data") == [] and find(act(result), "change_step") == []
    assert "hangup" in out and config.CALLBACK_NUMBER in out


# --- manage tools -----------------------------------------------------------

def test_confirm_sets_status(agent):
    acts = act(agent.confirm_appointment({}, RIGHT))
    assert cal.get_event("A-0101")["status"] == "CONFIRMED"
    assert find(acts, "change_step") == ["wrap_up"]


def test_cancel_sets_status(agent):
    agent.cancel_appointment({}, RIGHT)
    assert cal.get_event("A-0101")["status"] == "CANCELLED"


def test_reschedule_moves_event_and_keeps_length(agent):
    acts = act(agent.reschedule_appointment({"new_start": "2027-01-14 15:30"}, RIGHT))
    ev = cal.get_event("A-0101")
    assert ev["start"] == datetime(2027, 1, 14, 15, 30, tzinfo=ZoneInfo("America/New_York"))
    assert (ev["end"] - ev["start"]).seconds == 3600 and ev["status"] == "CONFIRMED"
    assert find(acts, "change_step") == ["wrap_up"]


@pytest.mark.parametrize("new_start", ["2027-01-16 10:00",   # Saturday
                                       "2027-01-14 19:00",   # after hours
                                       "2027-01-14 10:15",   # not a slot
                                       "2020-01-14 10:00",   # past
                                       "next tuesday"])
def test_reschedule_rejects_bad_slots(agent, new_start):
    before = config.CALENDAR_FILE.read_text()
    assert act(agent.reschedule_appointment({"new_start": new_start}, RIGHT)) == []
    assert config.CALENDAR_FILE.read_text() == before


def test_opt_out_writes_dnc_and_ends_call(agent):
    out = text(agent.opt_out({}, RIGHT))
    assert "+15550101" in contacts.load_dnc()
    assert "hangup" in out
    assert dialer.skip_reason(contacts.load_contacts()["A-0101"], contacts.load_dnc(),
                              datetime(2027, 1, 11, 15, tzinfo=UTC)) == "on do-not-call list"


def test_manage_tools_use_url_appointment_not_model_args(agent):
    agent.cancel_appointment({"appointment_id": "A-0104"}, RIGHT)   # model tries another id
    assert cal.get_event("A-0101")["status"] == "CANCELLED"
    assert cal.get_event("A-0104")["status"] == "TENTATIVE"


# --- dialer -----------------------------------------------------------------

def ids(contacts_list):
    return sorted(c["appointment_id"] for c in contacts_list)


def test_dialer_filters_consent_dnc_and_hours():
    call, skip = dialer.plan(datetime(2027, 1, 11, 19, 0, tzinfo=UTC))  # 14:00 NY, 09:00 HI
    assert ids(call) == ["A-0101", "A-0104", "A-0105"]
    assert dict((c["appointment_id"], r) for c, r in skip) == {
        "A-0102": "no consent", "A-0103": "on do-not-call list"}


@pytest.mark.parametrize("utc_hour,expected", [       # January: NY -5, Denver -7, Honolulu -10
    (12, []),                              # 07:00 NY: too early everywhere
    (13, ["A-0101"]),                      # 08:00 NY opens; 06:00 Denver still too early
    (15, ["A-0101", "A-0104"]),            # 10:00 NY, 08:00 Denver
    (2, ["A-0104", "A-0105"]),             # 21:00 NY closed; 19:00 Denver, 16:00 Honolulu
    (4, ["A-0105"]),                       # 21:00 Denver closed; 18:00 Honolulu
])
def test_dialer_honors_local_calling_hours(utc_hour, expected):
    call, _ = dialer.plan(datetime(2027, 1, 11, utc_hour, 0, tzinfo=UTC))
    assert ids(call) == expected


def test_dry_run_dials_nobody(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["dialer.py", "--dry-run"])
    with mock.patch("signalwire.rest.RestClient") as client:
        dialer.main()
    client.assert_not_called()
    assert "skip  A-0102" in capsys.readouterr().out


def test_dial_uses_from_number_and_agent_url(monkeypatch):
    monkeypatch.setattr(config, "FROM_NUMBER", "+15550100")
    monkeypatch.setattr(config, "PUBLIC_URL", "https://example.ngrok.app")
    monkeypatch.setattr(config, "BASIC_AUTH", ("u", "p@ss"))
    client = mock.Mock()
    client.calling.dial.return_value = {"id": "call-1"}
    assert dialer.dial(contacts.load_contacts()["A-0101"], client) == "call-1"
    client.calling.dial.assert_called_once_with(
        from_="+15550100", to="+15550101", url="https://u:p%40ss@example.ngrok.app/?appt=A-0101")


# --- governance: the SWML exactly as swaig-test dumps it ---------------------

def dump(query: dict) -> dict:
    exe = Path(sys.executable).with_name("swaig-test")
    out = subprocess.run([str(exe) if exe.exists() else "swaig-test", str(RECIPE / "app.py"),
                          "--dump-swml", "--raw", "--query-params", json.dumps(query)],
                         capture_output=True, text=True, check=True, cwd=RECIPE).stdout
    return next(v["ai"] for v in json.loads(out)["sections"]["main"] if "ai" in v)


@pytest.fixture(scope="module")
def ai():
    return dump({"appt": "A-0101"})


def test_governance_steps_and_tools(ai):
    steps = {s["name"]: s for s in ai["prompt"]["contexts"]["default"]["steps"]}
    assert steps["confirm_identity"]["functions"] == ["confirm_identity"]
    assert steps["confirm_identity"]["valid_steps"] == []
    assert sorted(steps["manage"]["functions"]) == [
        "cancel_appointment", "confirm_appointment", "opt_out", "reschedule_appointment"]
    assert steps["wrap_up"]["functions"] == []
    assert steps["wrap_up"]["valid_steps"] == []  # no next_step tool on the last step


def test_governance_no_appointment_details_before_identity(ai):
    assert ai["global_data"] == {"appointment_id": "A-0101", "first_name": "Jordan"}
    swml_text = json.dumps(ai)
    for detail in SECRET_DETAILS:
        assert detail not in swml_text


def test_call_window_is_configurable(monkeypatch):
    monkeypatch.setattr(config, "CALL_WINDOW", "09:00-17:00")
    call, _ = dialer.plan(datetime(2027, 1, 11, 13, 30, tzinfo=UTC))   # 08:30 NY
    assert call == []
