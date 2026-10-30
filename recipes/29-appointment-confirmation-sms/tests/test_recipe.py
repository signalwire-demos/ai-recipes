"""Handler tests (direct calls, assert on FunctionResult actions), the inbound SMS webhook
(laml_webhooks form POST), dynamic config, and governance assertions on the dumped SWML."""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

RECIPE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RECIPE))

import config  # noqa: E402
from app import ConfirmationAgent, cxml_reply, find_booking, load_bookings  # noqa: E402

SEED = [{"confirmation": "AC-1001", "phone": "+15550142", "name": "Jordan Example",
         "date": "2026-11-03", "time": "09:00"}]


@pytest.fixture(autouse=True)
def store(tmp_path, monkeypatch):
    path = tmp_path / "bookings.json"
    path.write_text(json.dumps(SEED))
    monkeypatch.setattr(config, "BOOKINGS_FILE", path)
    monkeypatch.setattr(config, "SMS_FROM", "+15550100")
    monkeypatch.setattr(config, "DIAL_FROM", "+15550101")
    return path


@pytest.fixture(scope="module")
def agent():
    return ConfirmationAgent()


def actions(result):
    return result.to_dict().get("action", [])


def find(acts, key):
    return [a[key] for a in acts if key in a]


def sms_verb(acts):
    """send_sms emits {"SWML": {... "main": [{"send_sms": {...}}]}}."""
    for swml in find(acts, "SWML"):
        for verb in swml["sections"]["main"]:
            if "send_sms" in verb:
                return verb["send_sms"]
    return None


CALLER = {"global_data": {"caller": "+15550177"}}


# --- book_appointment -----------------------------------------------------------

def test_book_sends_sms_with_all_three_fields_and_advances(agent, store):
    result = agent.book_appointment({"name": "Sam", "date": "2026-11-04", "time": "11:00"}, CALLER)
    acts = actions(result)
    sms = sms_verb(acts)
    assert sms["to_number"] == "+15550177" and sms["from_number"] == "+15550100"
    assert "2026-11-04" in sms["body"] and "11:00" in sms["body"] and "AC-1002" in sms["body"]
    assert "texted" in result.to_dict()["response"]  # the caller is told the text was sent
    assert find(acts, "change_step") == ["confirmed"]
    assert find(acts, "set_global_data")[0]["booking"]["confirmation"] == "AC-1002"
    assert load_bookings()[-1]["phone"] == "+15550177"


def test_book_rejects_a_slot_that_is_not_open(agent):
    result = agent.book_appointment({"name": "Sam", "date": "2026-11-04", "time": "23:00"}, CALLER)
    assert actions(result) == []
    assert len(load_bookings()) == 1


def test_book_rejects_a_taken_slot(agent):
    result = agent.book_appointment({"name": "Sam", "date": "2026-11-03", "time": "09:00"}, CALLER)
    assert actions(result) == [] and "taken" in result.to_dict()["response"]


# --- reschedule_appointment -----------------------------------------------------

def test_reschedule_moves_the_preloaded_booking_and_texts(agent):
    raw = {"global_data": {"caller": "+15550142", "booking": SEED[0]}}
    acts = actions(agent.reschedule_appointment({"date": "2026-11-05", "time": "13:00"}, raw))
    assert find_booking(confirmation="AC-1001")["date"] == "2026-11-05"
    sms = sms_verb(acts)
    assert sms["to_number"] == "+15550142" and "13:00" in sms["body"] and "AC-1001" in sms["body"]
    assert find(acts, "change_step") == ["confirmed"]


def test_reschedule_without_a_preloaded_booking_changes_nothing(agent):
    result = agent.reschedule_appointment({"date": "2026-11-05", "time": "13:00"}, {"global_data": {}})
    assert actions(result) == [] and load_bookings() == SEED


# --- inbound SMS webhook --------------------------------------------------------

@pytest.fixture
def client(agent):
    from fastapi.testclient import TestClient
    return TestClient(agent.get_app())


def post_sms(client, sender, body):
    form = {"MessageSid": "SM0001", "From": sender, "To": "+15550100", "Body": body}
    return client.post(config.SMS_ROUTE, data=form)  # form-encoded, like laml_webhooks


def test_inbound_reply_maps_to_booking_and_builds_the_dial(agent, client, monkeypatch):
    dialed = []
    monkeypatch.setattr(agent, "dial_back", lambda b: dialed.append(agent.dial_request(b)) or {"id": "c1"})
    r = post_sms(client, "+15550142", "Can I change it?")
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/xml")
    assert "<Message>" in r.text and "calling you now" in r.text
    [req] = dialed
    assert req["to"] == "+15550142" and req["from_"] == "+15550101"
    assert req["url"].endswith("/?booking=AC-1001")


def test_inbound_non_escalating_reply_resends_details(agent, client, monkeypatch):
    monkeypatch.setattr(agent, "dial_back", lambda b: pytest.fail("should not dial"))
    r = post_sms(client, "+15550142", "thanks!")
    assert "AC-1001" in r.text and "2026-11-03" in r.text


def test_inbound_from_unknown_number(agent):
    assert "couldn't find a booking" in agent.handle_sms("+15550199", "change it")


def test_signature_required_when_signing_key_set(client, monkeypatch):
    monkeypatch.setattr(config, "SIGNING_KEY", "PSK_test")
    assert post_sms(client, "+15550142", "hi").status_code == 403


def test_cxml_reply_escapes_text():
    assert "<Message>a &amp; b</Message>" in cxml_reply("a & b")


# --- dynamic config preloads the booking ----------------------------------------

def ai_of(swml_doc):
    return next(v["ai"] for v in swml_doc["sections"]["main"] if "ai" in v)


def test_dial_back_preloads_booking_and_starts_in_reschedule(agent, client):
    auth = agent.get_basic_auth_credentials()[:2]
    body = {"call": {"call_id": "c1", "from": "+15550101", "to": "+15550142"}}
    ai = ai_of(client.post("/?booking=AC-1001", json=body, auth=auth).json())
    assert ai["global_data"]["booking"] == SEED[0] and ai["global_data"]["caller"] == "+15550142"
    assert ai["prompt"]["contexts"]["default"]["initial_step"] == "reschedule"
    fresh = ai_of(client.post("/", json={"call": {"call_id": "c2", "from": "+15550177"}}, auth=auth).json())
    assert fresh["global_data"] == {"caller": "+15550177"}  # per-request copy: nothing leaks
    assert "initial_step" not in fresh["prompt"]["contexts"]["default"]


# --- governance: read the SWML exactly as swaig-test dumps it ---------------------

def swaig_test_bin() -> str:
    local = Path(sys.executable).with_name("swaig-test")
    return str(local) if local.exists() else (shutil.which("swaig-test") or "swaig-test")


@pytest.fixture(scope="module")
def steps():
    out = subprocess.run([swaig_test_bin(), str(RECIPE / "app.py"), "--dump-swml", "--raw"],
                         capture_output=True, text=True, check=True, cwd=RECIPE).stdout
    return {s["name"]: s for s in ai_of(json.loads(out))["prompt"]["contexts"]["default"]["steps"]}


def test_governance_each_step_has_exactly_its_tool(steps):
    assert steps["book"]["functions"] == ["book_appointment"]
    assert steps["reschedule"]["functions"] == ["reschedule_appointment"]
    assert steps["confirmed"]["functions"] == []


def test_governance_model_cannot_navigate_between_steps(steps):
    # no next_step tool: a new caller can't wander into reschedule, only handlers move the call
    assert steps["book"]["valid_steps"] == [] and steps["reschedule"]["valid_steps"] == []
