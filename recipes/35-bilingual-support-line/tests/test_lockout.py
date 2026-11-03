"""lookup_account brute force: failures count on the server per account and per caller ID,
across calls, so redialing doesn't reset them. The answer stays language-neutral JSON."""
import json
import sys
from pathlib import Path

import pytest

RECIPE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RECIPE))

import config  # noqa: E402
import lockout  # noqa: E402
from app import BilingualSupportAgent  # noqa: E402

GOOD = {"account_number": "100234", "zip": "74101"}
BAD = {"account_number": "100234", "zip": "74199"}


@pytest.fixture
def agent():
    return BilingualSupportAgent()


def call(n, caller="+15550100"):
    return {"call_id": f"call-{n}", "caller_id_num": caller, "global_data": {}}


def answer(result):
    return json.loads(result.to_dict()["response"])


def test_limit_holds_across_redials_and_caller_ids(agent):
    for n in range(config.MAX_LOOKUP_FAILURES - 1):
        assert answer(agent.lookup_account(BAD, call(n))) == {"found": False, "reason": "no_match"}
    assert answer(agent.lookup_account(BAD, call(5))) == {"found": False, "reason": "locked_try_later"}
    for raw in (call(6), call(7, caller="+15550199"), {}):  # redial, other phone, no caller ID
        result = agent.lookup_account(GOOD, raw)
        assert answer(result) == {"found": False, "reason": "locked_try_later"}
        assert result.to_dict().get("action") is None


def test_caller_id_is_locked_across_accounts(agent):
    for n, number in enumerate(["100877", "999991", "999992"]):
        agent.lookup_account({"account_number": number, "zip": "00000"}, call(n))
    assert answer(agent.lookup_account(GOOD, call(9)))["found"] is False
    assert answer(agent.lookup_account(GOOD, call(10, caller="+15550111")))["found"] is True


def test_lockout_expires(agent, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(lockout.time, "monotonic", lambda: clock[0])
    for n in range(config.MAX_LOOKUP_FAILURES):
        agent.lookup_account(BAD, call(n))
    assert answer(agent.lookup_account(GOOD, call(9)))["found"] is False
    clock[0] += config.LOOKUP_LOCKOUT_SECS + 1
    assert answer(agent.lookup_account(GOOD, call(10)))["found"] is True
