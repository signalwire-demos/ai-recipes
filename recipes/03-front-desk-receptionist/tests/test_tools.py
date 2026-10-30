"""Handler tests plus governance assertions against the SWML that swaig-test dumps."""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

RECIPE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RECIPE))

import config  # noqa: E402
from app import FrontDeskAgent  # noqa: E402

DEPTS = {d["name"]: d for d in config.DEPARTMENTS}
ALL_TOOLS = {t for d in config.DEPARTMENTS for t in d["tools"]}


@pytest.fixture(scope="module")
def agent():
    return FrontDeskAgent()


@pytest.fixture(autouse=True)
def scratch_files(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "TICKETS_FILE", tmp_path / "tickets.jsonl")
    monkeypatch.setattr(config, "REFUNDS_FILE", tmp_path / "refunds.jsonl")


def text(result):
    return result.to_dict()["response"]


# --- sales -----------------------------------------------------------------

def test_plan_price_known(agent):
    assert "$59.99" in text(agent.get_plan_price({"plan": "Plus"}, {}))


def test_plan_price_unknown_lists_plans(agent):
    assert "basic, plus, gigabit" in text(agent.get_plan_price({"plan": "platinum"}, {}))


# --- support ---------------------------------------------------------------

def test_status_outage_and_ok(agent):
    assert "degraded" in text(agent.check_service_status({"service": "internet"}, {}))
    assert "no known problems" in text(agent.check_service_status({"service": "tv"}, {}))
    assert "I can check" in text(agent.check_service_status({"service": "radio"}, {}))


def test_open_ticket_writes_row(agent):
    out = text(agent.open_ticket({"summary": "Router light is red"}, {"call_id": "c1"}))
    row = json.loads(config.TICKETS_FILE.read_text())
    assert row["summary"] == "Router light is red" and row["call_id"] == "c1"
    assert row["ticket_id"] in out


def test_open_ticket_needs_summary(agent):
    agent.open_ticket({"summary": " "}, {})
    assert not config.TICKETS_FILE.exists()


# --- billing ---------------------------------------------------------------

def test_get_invoice(agent):
    assert "$59.99, status paid" in text(agent.get_invoice({"invoice_id": "inv-1001"}, {}))
    assert "can't find" in text(agent.get_invoice({"invoice_id": "INV-9"}, {}))


@pytest.mark.parametrize("spoken", ["Inv1001", "inv 1001", "INV-1001", "1001", "I.N.V. 1001"])
def test_invoice_number_as_asr_hears_it(agent, spoken):
    # Regression: live call b9b47966 sent get_invoice("Inv1001") and got "can't find".
    assert "$59.99" in text(agent.get_invoice({"invoice_id": spoken}, {}))


def test_refund_accepts_asr_invoice_number(agent):
    assert "Refunded $59.99" in text(agent.issue_refund({"invoice_id": "Inv1001"}, {"call_id": "c1"}))
    assert json.loads(config.REFUNDS_FILE.read_text())["invoice_id"] == "INV-1001"


def test_refund_uses_record_amount_and_is_idempotent(agent):
    # The model can't pass an amount: the schema has none, and extra args are ignored.
    agent.issue_refund({"invoice_id": "INV-1001", "amount": 5000}, {"call_id": "c2"})
    rows = [json.loads(x) for x in config.REFUNDS_FILE.read_text().splitlines()]
    assert rows == [{"invoice_id": "INV-1001", "amount": 59.99, "call_id": "c2"}]
    assert "already been refunded" in text(agent.issue_refund({"invoice_id": "INV-1001"}, {}))
    assert "status refunded" in text(agent.get_invoice({"invoice_id": "INV-1001"}, {}))


def test_refund_over_limit_is_not_made(agent):
    assert "need a billing manager" in text(agent.issue_refund({"invoice_id": "INV-1002"}, {}))
    assert not config.REFUNDS_FILE.exists()


def test_refund_already_refunded_or_missing(agent):
    assert "already been refunded" in text(agent.issue_refund({"invoice_id": "INV-1003"}, {}))
    assert "no refund was made" in text(agent.issue_refund({"invoice_id": "INV-0000"}, {}))
    assert not config.REFUNDS_FILE.exists()


# --- governance: read the SWML exactly as swaig-test dumps it ---------------

def swaig_test_bin() -> str:
    local = Path(sys.executable).with_name("swaig-test")
    return str(local) if local.exists() else (shutil.which("swaig-test") or "swaig-test")


@pytest.fixture(scope="module")
def ai():
    out = subprocess.run(
        [swaig_test_bin(), str(RECIPE / "app.py"), "--dump-swml", "--raw"],
        capture_output=True, text=True, check=True, cwd=RECIPE,
    ).stdout
    return next(v["ai"] for v in json.loads(out)["sections"]["main"] if "ai" in v)


def test_governance_billing_tools_only_in_billing(ai):
    for name, ctx in ai["prompt"]["contexts"].items():
        for step in ctx["steps"]:
            if name != "billing":
                assert "issue_refund" not in step["functions"], (name, step["name"])
                assert "get_invoice" not in step["functions"], (name, step["name"])
            else:
                assert set(step["functions"]) == {"get_invoice", "issue_refund"}


def test_governance_every_step_declares_exactly_its_department_tools(ai):
    contexts = ai["prompt"]["contexts"]
    assert set(contexts) == set(DEPTS)
    for name, ctx in contexts.items():
        for step in ctx["steps"]:
            assert "functions" in step  # never inherited from the previous context
            assert step["functions"] == DEPTS[name]["tools"]
    assert contexts["default"]["steps"][0]["functions"] == []
    registered = {f["function"] for f in ai["SWAIG"]["functions"]}
    assert ALL_TOOLS <= registered


def test_governance_routes_match_declared_graph(ai):
    for name, ctx in ai["prompt"]["contexts"].items():
        assert ctx["valid_contexts"] == DEPTS[name]["routes"]
        for step in ctx["steps"]:
            assert step["valid_contexts"] == DEPTS[name]["routes"]
            assert step["valid_steps"] == []


def test_governance_departments_are_isolated_with_own_voice(ai):
    voices = {lang["name"]: lang["voice"] for lang in ai["languages"]}
    for name, ctx in ai["prompt"]["contexts"].items():
        dept = DEPTS[name]
        assert ctx["isolated"] is True
        assert ctx["enter_fillers"][config.LANGUAGE_CODE]
        assert voices[f"English-{dept['persona']}"] == dept["voice"]
        assert any(f"English-{dept['persona']}" in s["body"] for s in ctx["pom"])
    assert len(set(voices.values())) == len(DEPTS)
