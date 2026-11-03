"""find_account brute force: a match discloses the debtor's name, creditor and balance, so
failures count on the server per reference and per caller ID, across calls."""
import json
import sys
from pathlib import Path

import pytest

RECIPE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RECIPE))

import config  # noqa: E402
import lockout  # noqa: E402
from app import CollectionsAgent  # noqa: E402

GOOD = {"reference": "CA-20417", "postal_code": "74101"}
BAD = {"reference": "CA-20417", "postal_code": "00000"}


@pytest.fixture
def agent():
    return CollectionsAgent()


def call(n, caller="+15550100"):
    return {"call_id": f"call-{n}", "caller_id_num": caller, "global_data": {}}


def disclosed(result):
    body = json.dumps(result.to_dict())
    return "Alex" in body or "Example Electric" in body or "1,240" in body


def test_limit_holds_across_redials_and_caller_ids(agent):
    for n in range(config.MAX_LOOKUP_FAILURES - 1):
        assert "No account matches" in agent.find_account(BAD, call(n)).to_dict()["response"]
    assert "Too many failed attempts" in agent.find_account(BAD, call(5)).to_dict()["response"]
    for raw in (call(6), call(7, caller="+15550199"), {}):  # redial, other phone, no caller ID
        result = agent.find_account({"reference": "ca 20417", "postal_code": "74101"}, raw)
        assert "Too many" in result.to_dict()["response"]
        assert not disclosed(result) and result.to_dict().get("action") is None


def test_caller_id_is_locked_across_references(agent):
    for n, ref in enumerate(["CA00001", "CA00002", "CA00003"]):
        agent.find_account({"reference": ref, "postal_code": "74101"}, call(n))
    assert not disclosed(agent.find_account(GOOD, call(9)))
    assert disclosed(agent.find_account(GOOD, call(10, caller="+15550111")))


def test_lockout_expires(agent, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(lockout.time, "monotonic", lambda: clock[0])
    for n in range(config.MAX_LOOKUP_FAILURES):
        agent.find_account(BAD, call(n))
    assert not disclosed(agent.find_account(GOOD, call(9)))
    clock[0] += config.LOOKUP_LOCKOUT_SECS + 1
    assert disclosed(agent.find_account(GOOD, call(10)))
