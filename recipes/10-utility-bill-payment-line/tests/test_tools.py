"""Tests for the utility bill payment line.

1. Every handler is called directly; assertions are on FunctionResult actions. Wire names:
   swml_change_step() -> "change_step", update_global_data() -> "set_global_data",
   record_call / stop_record_call / pay -> "SWML" wrapping the verb.
2. The mock connector is exercised over HTTP with FastAPI's TestClient, including a check
   that no card data reaches any log output.
3. Governance assertions run against the SWML exactly as swaig-test dumps it.
"""
import json
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

RECIPE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RECIPE))
os.environ.setdefault("SWML_BASIC_AUTH_USER", "recipe")
os.environ.setdefault("SWML_BASIC_AUTH_PASSWORD", "test-password")

from fastapi.testclient import TestClient  # noqa: E402

from app import BillPaymentAgent  # noqa: E402

AUTH = (os.environ["SWML_BASIC_AUTH_USER"], os.environ["SWML_BASIC_AUTH_PASSWORD"])
VERIFIED = {"global_data": {"account": {"id": "100101", "name": "Alex Doe", "balance_due": "84.17"}}}


@pytest.fixture
def agent():
    return BillPaymentAgent()


@pytest.fixture
def client(agent):
    return TestClient(agent.get_app())


def actions(result):
    return result.to_dict().get("action", [])


def find(acts, key):
    return [a[key] for a in acts if key in a]


def find_with(acts, key):
    return [a for a in acts if key in a]


def swml_verbs(acts):
    """Flatten SWML actions to [(verb, params), ...] in order."""
    return [(verb, p) for a in find(acts, "SWML") for v in a["sections"]["main"] for verb, p in v.items()]


# --- verify_account ---------------------------------------------------------

def test_verify_starts_recording_and_opens_bill(agent):
    acts = actions(agent.verify_account({"account_number": "100-101", "service_zip": "74101"}, {}))
    assert [v for v, _ in swml_verbs(acts)] == ["record_call"]
    assert find(acts, "set_global_data")[0]["account"]["balance_due"] == "84.17"
    assert find(acts, "change_step") == ["bill"]


@pytest.mark.parametrize("args", [{"account_number": "100101", "service_zip": "00000"},
                                  {"account_number": "999999", "service_zip": "74101"}])
def test_verify_mismatch_does_nothing(agent, args):
    assert actions(agent.verify_account(args, {})) == []


# --- take_payment -----------------------------------------------------------

def test_take_payment_stops_recording_then_pays(agent):
    verbs = swml_verbs(actions(agent.take_payment({}, VERIFIED)))
    names = [v for v, _ in verbs]
    assert names.index("stop_record_call") < names.index("pay")
    assert verbs[0] == ("stop_record_call", {"control_id": "main"})


def test_take_payment_amount_comes_from_global_data_not_model(agent):
    acts = actions(agent.take_payment({"amount": "1.00", "charge_amount": "0.01"}, VERIFIED))
    pay = dict(swml_verbs(acts))["pay"]
    assert pay["charge_amount"] == "84.17"
    assert pay["security_code"] == "true"
    assert pay["payment_connector_url"].endswith("/pay")
    assert pay["parameters"][0] == {"name": "account_id", "value": "100101"}
    assert pay["parameters"][1]["name"] == "pay_ref"


def test_take_payment_leaves_the_ai_for_pay_and_comes_back(agent):
    """Regression (live call 51fc4c83 / its retry): pay as a plain SWML action inside the AI got
    calling.error 409 "Wait for ai to finish". pay now runs in a transfer SWML, then the call
    transfers back to this agent at ?pay_ref=<ref>."""
    acts = actions(agent.take_payment({}, VERIFIED))
    names = [v for v, _ in swml_verbs(acts)]
    assert names == ["stop_record_call", "pay", "transfer"]
    swml_actions = find_with(acts, "SWML")
    assert "transfer" not in swml_actions[0]               # stop_record_call runs inside the AI
    assert swml_actions[1]["transfer"] == "true"           # pay + transfer leave the AI
    ref = dict(swml_verbs(acts))["pay"]["parameters"][1]["value"]
    dest = dict(swml_verbs(acts))["transfer"]["dest"]
    assert dest.endswith(f"/?pay_ref={ref}") and "@" in dest  # back to this agent, with basic auth
    assert find(acts, "change_step") == []
    assert agent.pending_pay[ref]["account"]["balance_due"] == "84.17"


def test_return_from_pay_opens_after_payment(agent, client):
    ref = dict(swml_verbs(actions(agent.take_payment({}, VERIFIED))))["pay"]["parameters"][1]["value"]
    def render(query):
        doc = client.post(f"/{query}", json={}, auth=AUTH).json()
        ai = next(v["ai"] for v in doc["sections"]["main"] if "ai" in v)
        return ai["prompt"]["contexts"]["default"].get("initial_step"), ai.get("global_data", {})
    step, gd = render(f"?pay_ref={ref}")
    assert step == "after_payment"
    assert gd["payment"] == {"ref": ref} and gd["account"]["id"] == "100101"
    assert render(f"?pay_ref={ref}")[0] is None   # one-time: a replayed ref starts at verify
    assert render("")[0] is None
    assert render("?pay_ref=forged")[0] is None


def test_take_payment_does_not_hand_the_model_pay_result(agent):
    """Regression (live call 51fc4c83): ai_response "The payment result is ${pay_result}" reached
    the model as "The payment result is ." before pay ran, and the model told the caller a failed
    payment (pay_result=failed) was successful. The outcome now comes only from resume_recording."""
    acts = actions(agent.take_payment({}, VERIFIED))
    swml = json.dumps(find(acts, "SWML"))
    assert "pay_result" not in swml


def test_take_payment_without_balance_skips_pay(agent):
    for raw in ({}, {"global_data": {"account": {"balance_due": "0.00"}}}):
        acts = actions(agent.take_payment({}, raw))
        assert find(acts, "SWML") == []
        assert find(acts, "change_step") == ["wrap_up"]


def pay_ref(acts):
    return dict(swml_verbs(acts))["pay"]["parameters"][1]["value"]


def test_resume_recording_without_approval_says_it_failed(agent, client):
    """Fail closed: no approved charge for this call's pay_ref means "did NOT go through"."""
    ref = pay_ref(actions(agent.take_payment({}, VERIFIED)))
    client.post("/pay/status", auth=AUTH, json={"params": {"call_id": "c-1", "for": "payment-failed"}})
    result = agent.resume_recording({}, {"call_id": "c-1", "global_data": {"payment": {"ref": ref}}})
    acts = actions(result)
    assert [v for v, _ in swml_verbs(acts)] == ["record_call"]
    assert "did NOT go through" in result.to_dict()["response"]
    assert find(acts, "set_global_data") == [{"payment": {"ref": ref, "approved": False,
                                                          "status_event": "payment-failed"}}]
    assert find(acts, "change_step") == ["wrap_up"]


@pytest.mark.parametrize("shape", ["wire", "name_value", "dict"])
def test_resume_recording_after_approved_charge(agent, client, shape):
    """"wire" is what the platform actually POSTed to /pay live (call c3722a5e): a list of
    one-key objects. That call was approved at the connector but resume_recording said it
    failed, because only the name/value form was parsed."""
    ref = pay_ref(actions(agent.take_payment({}, VERIFIED)))
    params = {"wire": [{"account_id": "100101"}, {"pay_ref": ref}],
              "name_value": [{"name": "account_id", "value": "100101"}, {"name": "pay_ref", "value": ref}],
              "dict": {"account_id": "100101", "pay_ref": ref}}[shape]
    assert charge(client, "4242424242424242", parameters=params).status_code == 200
    result = agent.resume_recording({}, {"call_id": "c-1", "global_data": {"payment": {"ref": ref}}})
    assert "went through, confirmation ch_mock_8c9d14d5" in result.to_dict()["response"]
    assert find(actions(result), "set_global_data")[0]["payment"]["approved"] is True


def test_declined_charge_is_not_approved(agent, client):
    ref = pay_ref(actions(agent.take_payment({}, VERIFIED)))
    charge(client, "4000000000000002", parameters={"pay_ref": ref})
    result = agent.resume_recording({}, {"global_data": {"payment": {"ref": ref}}})
    assert "did NOT go through" in result.to_dict()["response"]


# --- mock connector ---------------------------------------------------------

def charge(client, card, **extra):
    body = {"transaction_id": "8c9d14d5", "method": "credit-card", "cardnumber": card, "cvv": "737",
            "postal_code": "74101", "expiry_month": "12", "expiry_year": "30",
            "chargeAmount": "84.17", "currency_code": "usd", **extra}
    return client.post("/pay", json=body, auth=AUTH)


def test_connector_approves_success_card(client):
    r = charge(client, "4242424242424242")
    assert r.status_code == 200
    assert r.json() == {"charge_id": "ch_mock_8c9d14d5", "error_code": None, "error_message": None}


@pytest.mark.parametrize("card,code", [("4000000000000002", "card_declined"),
                                       ("4000000000009995", "insufficient_funds"),
                                       ("5555555555554444", "card_not_supported")])
def test_connector_declines(client, card, code):
    r = charge(client, card)
    assert r.status_code != 200
    assert r.json()["charge_id"] is None and r.json()["error_code"] == code


def test_connector_requires_auth(client):
    assert client.post("/pay", json={"cardnumber": "4242424242424242"}).status_code == 401
    assert client.post("/pay/status", json={"params": {}}).status_code == 401


def test_status_callback_drops_card_fields(agent, client):
    params = {"call_id": "c-2", "for": "payment-failed", "payment_card_number": "************0002",
              "security_code": "***", "expiration_date": "1230"}
    client.post("/pay/status", auth=AUTH, json={"params": params})
    assert agent.pay_status["c-2"] == {"for": "payment-failed", "error_type": None}


def test_no_card_data_reaches_logs(client, caplog, capsys):
    import signalwire
    signalwire.configure_logging()
    caplog.set_level(logging.DEBUG)
    logging.getLogger().setLevel(logging.DEBUG)
    cards = ["4242424242424242", "4000000000000002"]
    for card in cards:
        charge(client, card)
    client.post("/pay/status", auth=AUTH, json={"params": {
        "call_id": "c-3", "for": "payment-completed", "payment_card_number": "************4242",
        "expiration_date": "1230", "payment_card_postal_code": "74101"}})
    out = capsys.readouterr()
    logged = caplog.text + out.out + out.err
    assert "pay txn=8c9d14d5" in logged  # the connector does log, just not card data
    for secret in cards + ["737", "1230", "************4242", "4242 4242"]:
        assert secret not in logged


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


def test_governance_payment_only_after_verification(swml):
    steps = steps_of(swml)
    assert steps["verify"]["functions"] == ["verify_account"]
    assert steps["verify"]["valid_steps"] == []
    assert [n for n, s in steps.items() if "take_payment" in s["functions"]] == ["bill"]


def test_governance_after_payment_only_resumes_recording(swml):
    steps = steps_of(swml)
    assert steps["after_payment"]["functions"] == ["resume_recording"]
    assert steps["after_payment"]["valid_steps"] == []
    assert steps["wrap_up"]["functions"] == []
    assert steps["wrap_up"]["valid_steps"] == []  # no next_step tool on the last step


def test_governance_take_payment_schema_has_no_amount(swml):
    ai = next(v["ai"] for v in swml["sections"]["main"] if "ai" in v)
    fn = next(f for f in ai["SWAIG"]["functions"] if f["function"] == "take_payment")
    assert fn["parameters"].get("properties", {}) == {}


def test_status_payment_completed_counts_as_paid(agent, client):
    """With a real processor the mock's approvals are empty; the platform's status_url event is
    the evidence. Live (call c3722a5e) it arrived as calling.call.pay params.for=payment-completed."""
    ref = pay_ref(actions(agent.take_payment({}, VERIFIED)))
    client.post("/pay/status", auth=AUTH, json={"event_type": "calling.call.pay", "params": {
        "call_id": "c-9", "for": "payment-completed", "payment_card_number": "************4242"}})
    result = agent.resume_recording({}, {"call_id": "c-9", "global_data": {"payment": {"ref": ref}}})
    assert result.to_dict()["response"].startswith("Recording resumed. The payment went through.")


def test_status_for_another_call_does_not_count(agent, client):
    client.post("/pay/status", auth=AUTH, json={"params": {"call_id": "other", "for": "payment-completed"}})
    result = agent.resume_recording({}, {"call_id": "c-10", "global_data": {"payment": {"ref": "x"}}})
    assert "did NOT go through" in result.to_dict()["response"]
