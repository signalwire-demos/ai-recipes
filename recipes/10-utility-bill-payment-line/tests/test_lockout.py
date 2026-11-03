"""verify_account brute force: failures count on the server per account and per caller ID,
across calls, so hanging up and redialing doesn't reset them."""
import os
import sys
from pathlib import Path

import pytest

RECIPE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RECIPE))
os.environ.setdefault("SWML_BASIC_AUTH_USER", "recipe")
os.environ.setdefault("SWML_BASIC_AUTH_PASSWORD", "test-password")

import config  # noqa: E402
import lockout  # noqa: E402
from app import BillPaymentAgent  # noqa: E402

GOOD = {"account_number": "100101", "service_zip": "74101"}
BAD = {"account_number": "100101", "service_zip": "00000"}


@pytest.fixture
def agent():
    return BillPaymentAgent()


def call(n, caller="+15550100"):
    return {"call_id": f"call-{n}", "caller_id_num": caller, "global_data": {"verify_failures": 0}}


def verified(result):
    return any("change_step" in a for a in result.to_dict().get("action", []))


def test_limit_holds_across_redials_and_caller_ids(agent):
    for n in range(config.MAX_VERIFY_FAILURES - 1):
        assert "didn't match" in agent.verify_account(BAD, call(n)).to_dict()["response"]
    assert "Too many failed attempts" in agent.verify_account(BAD, call(5)).to_dict()["response"]
    for raw in (call(6), call(7, caller="+15550199"), {}):  # redial, other phone, no caller ID
        result = agent.verify_account(GOOD, raw)
        assert not verified(result) and "Too many" in result.to_dict()["response"]


def test_caller_id_is_locked_across_accounts(agent):
    for n, number in enumerate(["100102", "999991", "999992"]):
        agent.verify_account({"account_number": number, "service_zip": "00000"}, call(n))
    assert not verified(agent.verify_account(GOOD, call(9)))
    assert verified(agent.verify_account(GOOD, call(10, caller="+15550111")))


def test_lockout_expires_and_success_clears_account(agent, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(lockout.time, "monotonic", lambda: clock[0])
    for n in range(config.MAX_VERIFY_FAILURES):
        agent.verify_account(BAD, call(n))
    assert not verified(agent.verify_account(GOOD, call(9)))
    clock[0] += config.VERIFY_LOCKOUT_SECS + 1
    agent.verify_account(BAD, call(10))
    assert verified(agent.verify_account(GOOD, call(10)))
    assert agent.lockout.failures("acct:100101") == 0
