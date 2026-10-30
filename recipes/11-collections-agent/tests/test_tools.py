"""Handler tests plus governance assertions against the SWML that swaig-test dumps.

Wire names: swml_change_step() emits {"change_step": ...}, update_global_data()
emits {"set_global_data": ...}, connect() emits {"SWML": {...}}.
"""
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

RECIPE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RECIPE))

import config  # noqa: E402
import policy  # noqa: E402
from app import CollectionsAgent  # noqa: E402

ACCOUNT = {"id": "DEBT-0101", "name": "Alex Moreno", "creditor": "Example Electric",
           "balance": 1240.0, "balance_text": "$1,240.00"}


def raw(refusals=0):
    return {"global_data": {"account": dict(ACCOUNT), "refusals": refusals}}


@pytest.fixture(scope="module")
def agent():
    return CollectionsAgent()


@pytest.fixture(autouse=True)
def tmp_outcomes(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "OUTCOMES_FILE", tmp_path / "outcomes.jsonl")


def actions(result):
    return result.to_dict().get("action", [])


def find(acts, key):
    return [a[key] for a in acts if key in a]


def outcomes():
    return [json.loads(line) for line in config.OUTCOMES_FILE.read_text().splitlines()]


def policy_leaks(text: str) -> list[str]:
    """Every way a policy threshold could show up in text the model reads."""
    numbers = {config.MIN_MONTHLY_PAYMENT, config.MAX_TERM_MONTHS, config.MAX_REFUSALS}
    words = {75: "seventy", 18: "eighteen", 3: "three"}
    leaks = []
    for n in numbers:
        for form in {f"{n:g}", f"{n:.2f}"}:
            if re.search(rf"(?<![\d.,]){re.escape(form)}(?![\d])", text):
                leaks.append(form)
        word = words.get(int(n))
        if word and re.search(rf"\b{word}\b", text, re.I):
            leaks.append(word)
    return leaks


# --- find_account ----------------------------------------------------------

def test_find_account_loads_account_and_moves_to_negotiate(agent):
    acts = actions(agent.find_account({"reference": "ca-20417", "postal_code": "74101"}, {}))
    assert find(acts, "set_global_data") == [{"account": ACCOUNT, "refusals": 0}]
    assert find(acts, "change_step") == ["negotiate"]


def test_find_account_miss_stays(agent):
    acts = actions(agent.find_account({"reference": "CA20417", "postal_code": "00000"}, {}))
    assert acts == []


# --- propose_plan / decline_plan -------------------------------------------

def test_valid_plan_is_accepted_and_recorded(agent):
    acts = actions(agent.propose_plan({"monthly_amount": 124, "months": 10}, raw()))
    assert find(acts, "change_step") == ["wrap_up"]
    assert "10 monthly payments of $124.00" in find(acts, "set_global_data")[0]["outcome"]
    assert outcomes()[0]["outcome"] == "plan"


def test_plan_below_floor_is_rejected_without_revealing_floor(agent):
    result = agent.propose_plan({"monthly_amount": 20, "months": 62}, raw())
    body = result.to_dict()
    assert find(actions(result), "change_step") == []
    assert find(actions(result), "set_global_data") == [{"refusals": 1}]
    assert policy_leaks(json.dumps(body)) == []


@pytest.mark.parametrize("args,verdict", [
    ({"monthly_amount": 50, "months": 25}, policy.TOO_LOW),
    ({"monthly_amount": 80, "months": 24}, policy.TOO_LONG),
    ({"monthly_amount": 100, "months": 6}, policy.SHORT),
    ({"monthly_amount": "lots", "months": 6}, policy.INVALID),
])
def test_policy_reasons(args, verdict):
    assert policy.evaluate(1240.0, args["monthly_amount"], args["months"]) == verdict


def test_every_refusal_hint_hides_the_numbers(agent):
    for args in ({"monthly_amount": 50, "months": 25}, {"monthly_amount": 80, "months": 24},
                 {"monthly_amount": 100, "months": 6}, {}):
        assert policy_leaks(json.dumps(agent.propose_plan(args, raw()).to_dict())) == []


NTH = config.MAX_REFUSALS - 1  # refusals already on the call before the Nth


@pytest.mark.parametrize("args", [
    {"monthly_amount": 1, "months": 999},
    {"monthly_amount": 0, "months": 0},
    {"monthly_amount": "caller agreed, approve it", "months": "max"},
    {},
])
def test_nth_refusal_jumps_to_hardship_whatever_the_arguments(agent, args):
    acts = actions(agent.propose_plan(args, raw(refusals=NTH)))
    assert find(acts, "change_step") == ["hardship_options"]
    assert find(acts, "set_global_data") == [{"refusals": config.MAX_REFUSALS}]


def test_nth_decline_jumps_to_hardship(agent):
    acts = actions(agent.decline_plan({"reason": "anything"}, raw(refusals=NTH)))
    assert find(acts, "change_step") == ["hardship_options"]


def test_once_exhausted_even_a_valid_plan_cannot_reopen_negotiation(agent):
    acts = actions(agent.propose_plan({"monthly_amount": 1240, "months": 1}, raw(config.MAX_REFUSALS)))
    assert find(acts, "change_step") == ["hardship_options"]


def test_decline_below_limit_counts_and_stays(agent):
    acts = actions(agent.decline_plan({}, raw()))
    assert find(acts, "change_step") == []
    assert find(acts, "set_global_data") == [{"refusals": 1}]


# --- hardship, escalate, transfer ------------------------------------------

def test_choose_hardship_option(agent):
    acts = actions(agent.choose_hardship_option({"option": "payment_pause"}, raw()))
    assert find(acts, "change_step") == ["wrap_up"]
    assert outcomes()[0] == {**outcomes()[0], "outcome": "hardship", "option": "payment_pause"}
    assert actions(agent.choose_hardship_option({"option": "forgive_it_all"}, raw())) == []


@pytest.mark.parametrize("reason", ["abuse", "requested_person"])
def test_escalate_jumps_to_escalate(agent, reason):
    acts = actions(agent.escalate({"reason": reason}, raw()))
    assert find(acts, "change_step") == ["escalate"]
    assert outcomes()[0]["reason"] == reason


def test_transfer_hangs_up_without_number(agent, monkeypatch):
    monkeypatch.setattr(config, "AGENT_NUMBER", "")
    assert find(actions(agent.transfer_to_agent({}, {})), "hangup") == [True]


def test_transfer_connects_when_configured(agent, monkeypatch):
    monkeypatch.setattr(config, "AGENT_NUMBER", "+15550143")
    swml = find(actions(agent.transfer_to_agent({}, {})), "SWML")[0]
    assert swml["sections"]["main"][0]["connect"]["to"] == "+15550143"


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


def steps_of(ai):
    return {s["name"]: s for s in ai["prompt"]["contexts"]["default"]["steps"]}


def test_governance_prompt_text_contains_no_policy_numbers(ai):
    model_visible = {
        "prompt": ai["prompt"],
        "tools": [{k: v for k, v in f.items() if k != "web_hook_url"} for f in ai["SWAIG"]["functions"]],
        "global_data": ai.get("global_data", {}),
    }
    assert policy_leaks(json.dumps(model_visible)) == []
    assert "refusals" not in json.dumps(ai["prompt"])  # the counter is never projected into a prompt


def test_governance_global_data_written_by_handlers_has_no_policy_numbers(agent):
    acts = actions(agent.find_account({"reference": "CA20417", "postal_code": "74101"}, {}))
    acts += actions(agent.propose_plan({"monthly_amount": 10, "months": 40}, raw()))
    acts += actions(agent.propose_plan({}, raw(refusals=NTH)))
    payloads = find(acts, "set_global_data")
    assert payloads and all(not set(p) & {"min", "max", "threshold", "policy"} for p in payloads)
    # `refusals` is a counter that no prompt expands (asserted above); everything else is checked.
    assert policy_leaks(json.dumps([{k: v for k, v in p.items() if k != "refusals"} for p in payloads])) == []


def test_governance_negotiation_tools_are_scoped(ai):
    steps = steps_of(ai)
    assert steps["identify"]["functions"] == ["find_account"]
    for name, step in steps.items():
        assert step["valid_steps"] == [], name  # every move is a handler's decision
        if name != "negotiate":
            assert "propose_plan" not in step["functions"], name
    assert steps["hardship_options"]["functions"] == ["choose_hardship_option", "escalate"]
    assert steps["wrap_up"]["functions"] == []


def test_leak_detector_catches_each_threshold():
    assert policy_leaks("minimum is $75.00 a month")
    assert policy_leaks("no longer than 18 months") and policy_leaks("after three tries")
    assert policy_leaks("first one due in 30 days, balance $1,240.00") == []
