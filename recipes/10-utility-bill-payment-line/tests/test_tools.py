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
    assert pay["parameters"] == [{"name": "account_id", "value": "100101"}]
    assert find(acts, "change_step") == ["after_payment"]


def test_take_payment_without_balance_skips_pay(agent):
    for raw in ({}, {"global_data": {"account": {"balance_due": "0.00"}}}):
        acts = actions(agent.take_payment({}, raw))
        assert find(acts, "SWML") == []
        assert find(acts, "change_step") == ["wrap_up"]


def test_resume_recording_after_payment(agent, client):
    client.post("/pay/status", auth=AUTH, json={"params": {"call_id": "c-1", "for": "payment-completed"}})
    acts = actions(agent.resume_recording({}, {"call_id": "c-1"}))
    assert [v for v, _ in swml_verbs(acts)] == ["record_call"]
    assert find(acts, "set_global_data") == [{"payment": {"status_event": "payment-completed"}}]
    assert find(acts, "change_step") == ["wrap_up"]


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


def test_governance_take_payment_schema_has_no_amount(swml):
    ai = next(v["ai"] for v in swml["sections"]["main"] if "ai" in v)
    fn = next(f for f in ai["SWAIG"]["functions"] if f["function"] == "take_payment")
    assert fn["parameters"].get("properties", {}) == {}
