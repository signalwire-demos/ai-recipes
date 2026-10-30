"""Handler tests plus governance assertions against the SWML that swaig-test dumps.

Wire names: swml_change_step() emits {"change_step": ...}, update_global_data()
emits {"set_global_data": ...}, connect() emits {"SWML": {...}}.
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
from app import BankBalanceAgent, normalize_dob  # noqa: E402

GOOD = {"account_number": "4001 0101", "date_of_birth": "March 14th, 1985"}
BAD = {"account_number": "40010101", "date_of_birth": "1990-01-01"}
VERIFIED = {"global_data": {"verified": True, "customer": {"id": "ACC-0101", "name": "Jordan Rivera"}}}


@pytest.fixture(scope="module")
def agent():
    return BankBalanceAgent()


@pytest.fixture(autouse=True)
def tmp_disputes(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DISPUTES_FILE", tmp_path / "disputes.jsonl")


def actions(result):
    return result.to_dict().get("action", [])


def find(acts, key):
    return [a[key] for a in acts if key in a]


# --- verify_identity -------------------------------------------------------

@pytest.mark.parametrize("spoken", ["1985-03-14", "03/14/1985", "March 14 1985", "14 March 1985"])
def test_normalize_dob(spoken):
    assert normalize_dob(spoken) == "1985-03-14"


def test_successful_verify_sets_global_data_and_changes_step(agent):
    acts = actions(agent.verify_identity(GOOD, {"global_data": {}}))
    assert find(acts, "set_global_data") == [
        {"verified": True, "customer": {"id": "ACC-0101", "name": "Jordan Rivera"}}
    ]
    assert find(acts, "change_step") == ["account_menu"]


def test_failed_verify_does_not_change_step(agent):
    result = agent.verify_identity(BAD, {"global_data": {}})
    acts = actions(result)
    assert find(acts, "change_step") == []
    assert find(acts, "set_global_data") == [{"verify_failures": 1}]
    assert "date of birth" not in result.to_dict()["response"]  # never says which factor was wrong


def test_second_failure_still_stays(agent):
    acts = actions(agent.verify_identity(BAD, {"global_data": {"verify_failures": 1}}))
    assert find(acts, "change_step") == []


def test_third_failure_jumps_to_escalate(agent):
    acts = actions(agent.verify_identity(BAD, {"global_data": {"verify_failures": 2}}))
    assert find(acts, "set_global_data") == [{"verify_failures": 3}]
    assert find(acts, "change_step") == ["escalate"]


def test_three_failures_in_a_row_end_in_escalate(agent):
    gd = {}
    steps = []
    for _ in range(3):
        acts = actions(agent.verify_identity({"account_number": "999", "date_of_birth": "nonsense"},
                                             {"global_data": gd}))
        gd.update(find(acts, "set_global_data")[0])
        steps += find(acts, "change_step")
    assert steps == ["escalate"]


# --- account_menu ----------------------------------------------------------

def test_account_tools_refuse_without_verification(agent):
    for call in (agent.get_balance({}, {}),
                 agent.list_transactions({}, {"global_data": {"verified": False}}),
                 agent.open_dispute({"transaction_id": "T-9001", "reason": "x"}, {})):
        assert call.to_dict()["response"] == "The caller is not verified."


def test_get_balance(agent):
    text = agent.get_balance({}, VERIFIED).to_dict()["response"]
    assert "$2,418.07" in text and "$2,533.12" in text


def test_list_transactions_caps_count(agent):
    text = agent.list_transactions({"count": 50}, VERIFIED).to_dict()["response"]
    assert text.count("T-90") == config.MAX_TRANSACTIONS
    assert "T-9001" in agent.list_transactions({}, VERIFIED).to_dict()["response"]


def test_open_dispute_writes_record(agent):
    text = agent.open_dispute({"transaction_id": "t-9005", "reason": "Not me"}, VERIFIED).to_dict()["response"]
    assert "D-0001" in text
    record = json.loads(config.DISPUTES_FILE.read_text())
    assert record["transaction_id"] == "T-9005" and record["account_id"] == "ACC-0101"


def test_open_dispute_rejects_other_accounts_transaction(agent):
    text = agent.open_dispute({"transaction_id": "T-9101", "reason": "x"}, VERIFIED).to_dict()["response"]
    assert "isn't on this account" in text
    assert not config.DISPUTES_FILE.exists()


# --- escalate --------------------------------------------------------------

def test_escalate_hangs_up_without_number(agent, monkeypatch):
    monkeypatch.setattr(config, "ESCALATION_NUMBER", "")
    acts = actions(agent.escalate_call({}, {}))
    assert find(acts, "hangup") == [True]


def test_escalate_connects_when_configured(agent, monkeypatch):
    monkeypatch.setattr(config, "ESCALATION_NUMBER", "+15550142")
    swml = find(actions(agent.escalate_call({}, {})), "SWML")[0]
    assert swml["sections"]["main"][0]["connect"]["to"] == "+15550142"


# --- governance: read the SWML exactly as swaig-test dumps it ---------------

def swaig_test_bin() -> str:
    local = Path(sys.executable).with_name("swaig-test")
    return str(local) if local.exists() else (shutil.which("swaig-test") or "swaig-test")


@pytest.fixture(scope="module")
def steps():
    out = subprocess.run(
        [swaig_test_bin(), str(RECIPE / "app.py"), "--dump-swml", "--raw"],
        capture_output=True, text=True, check=True, cwd=RECIPE,
    ).stdout
    ai = next(v["ai"] for v in json.loads(out)["sections"]["main"] if "ai" in v)
    return {s["name"]: s for s in ai["prompt"]["contexts"]["default"]["steps"]}


ACCOUNT_TOOLS = {"get_balance", "list_transactions", "open_dispute"}


def test_governance_verify_step_exposes_exactly_one_tool_and_no_navigation(steps):
    verify = steps["verify_identity"]
    assert verify["functions"] == ["verify_identity"]
    assert verify["valid_steps"] == []  # no next_step tool: only the handler moves the call


def test_governance_account_tools_exist_only_in_account_menu(steps):
    for name, step in steps.items():
        exposed = set(step["functions"]) & ACCOUNT_TOOLS
        assert exposed == (ACCOUNT_TOOLS if name == "account_menu" else set()), name


def test_governance_no_step_can_navigate_back_into_the_account_menu(steps):
    for name in ("wrap_up", "escalate"):
        assert steps[name]["valid_steps"] == []
    assert steps["escalate"]["functions"] == ["escalate_call"]
