"""Server-side lockout: failures count per account and per caller ID across calls, so a
redial or a forged global_data can't reset them, and verification is the server's record."""
import sys
from pathlib import Path

import pytest

RECIPE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RECIPE))

import config  # noqa: E402
import lockout  # noqa: E402
from app import BankBalanceAgent  # noqa: E402

GOOD = {"account_number": "40010101", "date_of_birth": "1985-03-14"}
WRONG_DOB = {"account_number": "40010101", "date_of_birth": "1990-01-01"}


@pytest.fixture
def agent():
    return BankBalanceAgent()


def call(n, caller="+15550100", **gd):
    return {"call_id": f"call-{n}", "caller_id_num": caller, "global_data": gd}


def step(result):
    return [a["change_step"] for a in result.to_dict().get("action", []) if "change_step" in a]


def lock_account(agent, caller="+15550100"):
    for n in range(config.MAX_VERIFY_ATTEMPTS):
        agent.verify_identity(WRONG_DOB, call(n, caller))


def test_redial_does_not_reset_the_count(agent):
    lock_account(agent)
    # New call, new call_id, forged counter: still locked, even with the right details.
    result = agent.verify_identity(GOOD, call(99, verify_failures=0))
    assert step(result) == ["escalate"] and "Too many failed attempts" in result.to_dict()["response"]
    assert "call-99" not in agent.verified


def test_account_is_locked_for_other_caller_ids_too(agent):
    lock_account(agent)
    assert step(agent.verify_identity(GOOD, call(50, caller="+15550199"))) == ["escalate"]


def test_caller_id_is_locked_across_accounts(agent):
    for n, number in enumerate(["40010102", "40019999", "40018888"]):
        agent.verify_identity({"account_number": number, "date_of_birth": "1990-01-01"}, call(n))
    assert step(agent.verify_identity(GOOD, call(9))) == ["escalate"]               # same phone
    assert step(agent.verify_identity(GOOD, call(10, caller="+15550111"))) == ["account_menu"]


def test_lockout_expires_after_the_window(agent, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(lockout.time, "monotonic", lambda: clock[0])
    lock_account(agent)
    clock[0] += config.VERIFY_LOCKOUT_SECS - 1
    assert step(agent.verify_identity(GOOD, call(20))) == ["escalate"]
    clock[0] += config.VERIFY_LOCKOUT_SECS + 1
    assert step(agent.verify_identity(GOOD, call(21))) == ["account_menu"]


def test_success_clears_the_account_count(agent):
    agent.verify_identity(WRONG_DOB, call(1))
    agent.verify_identity(GOOD, call(1))
    assert agent.lockout.failures("acct:40010101") == 0
    assert agent.lockout.failures("caller:+15550100") == 1  # still guards against account cycling


def test_verification_is_per_call_and_server_side(agent):
    agent.verify_identity(GOOD, call(1))
    assert "$2,418.07" in agent.get_balance({}, call(1)).to_dict()["response"]
    # Another call_id carrying a copy of call-1's global_data is not verified.
    forged = call(2, verified=True, customer={"id": "ACC-0101", "name": "Jordan Rivera"})
    assert agent.get_balance({}, forged).to_dict()["response"] == "The caller is not verified."


def test_verified_session_expires(agent, monkeypatch):
    import app
    clock = [1000.0]
    monkeypatch.setattr(app.time, "monotonic", lambda: clock[0])
    agent.verify_identity(GOOD, call(1))
    clock[0] += config.VERIFIED_SESSION_SECS + 1
    assert agent.get_balance({}, call(1)).to_dict()["response"] == "The caller is not verified."


def test_lockout_counts_and_prunes():
    lk = lockout.Lockout(max_failures=2, window_secs=60)
    assert lk.fail("a", "", "b") == 1 and lk.fail("a") == 2
    assert lk.locked("a") and not lk.locked("b") and lk.failures("", "b") == 1
    assert lockout.caller_key({"caller_id_num": " +1555 "}) == "caller:+1555"
    assert lockout.caller_key({}) == ""
