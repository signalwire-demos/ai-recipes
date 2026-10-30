"""Tests: each handler directly, the same handlers over MCP JSON-RPC, and governance.

MCP calls go through Starlette's TestClient against agent.get_app(), the same
FastAPI app `python app.py` serves, so /mcp auth and routing are the real ones.
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

os.environ["SWML_BASIC_AUTH_USER"] = "tester"
os.environ["SWML_BASIC_AUTH_PASSWORD"] = "test-pass"

RECIPE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RECIPE))

import config  # noqa: E402
from app import PhoneAgent  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

AUTH = ("tester", "test-pass")
FUTURE_SLOT = "2030-01-07 10:30"   # a Monday, inside callback hours


@pytest.fixture(autouse=True)
def callbacks_file(tmp_path, monkeypatch):
    path = tmp_path / "callbacks.jsonl"
    monkeypatch.setattr(config, "CALLBACKS_FILE", path)
    return path


@pytest.fixture(scope="module")
def agent():
    return PhoneAgent()


@pytest.fixture(scope="module")
def client(agent):
    return TestClient(agent.get_app())


def actions(result):
    return result.to_dict().get("action", [])


def find(acts, key):
    return [a[key] for a in acts if key in a]


def rpc(client, method, params=None, auth=AUTH):
    body = {"jsonrpc": "2.0", "id": 1, "method": method}
    if params is not None:
        body["params"] = params
    return client.post("/mcp", json=body, auth=auth)


def mcp_call(client, name, arguments):
    return rpc(client, "tools/call", {"name": name, "arguments": arguments}).json()


# --- handlers (the SWAIG path) --------------------------------------------

def test_lookup_known_number_any_format(agent):
    result = agent.lookup_customer({"phone": "(555) 555-0101"}, {})
    acts = actions(result)
    assert find(acts, "set_global_data") == [
        {"account_id": "ACME-1001", "name": "Dana Rivera", "plan": "Fiber 500"}
    ]
    assert find(acts, "change_step") == ["help"]


def test_lookup_never_exposes_internal_fields(agent):
    payload = json.dumps(agent.lookup_customer({"phone": "+15555550102"}, {}).to_dict())
    assert "credit_risk" not in payload and "churn_score" not in payload and "high" not in payload


def test_lookup_unknown_number_stays_put(agent):
    result = agent.lookup_customer({"phone": "555-0199"}, {})
    assert actions(result) == []
    assert "No account" in result.to_dict()["response"]


def test_book_callback_writes_booking(agent, callbacks_file):
    result = agent.book_callback({"account_id": "acme-1003", "when": FUTURE_SLOT, "reason": "IP"}, {})
    assert "Booked a callback for Priya Shah" in result.to_dict()["response"]
    rows = [json.loads(line) for line in callbacks_file.read_text().splitlines()]
    assert rows == [{"account_id": "ACME-1003", "when": FUTURE_SLOT, "reason": "IP"}]
    assert find(actions(result), "set_global_data")[0]["callback"]["account_id"] == "ACME-1003"


@pytest.mark.parametrize("args, expect", [
    ({"account_id": "ACME-9999", "when": FUTURE_SLOT}, "no account"),
    ({"account_id": "ACME-1001", "when": "next tuesday"}, "YYYY-MM-DD HH:MM"),
    ({"account_id": "ACME-1001", "when": "2030-01-05 10:00"}, "weekdays"),   # Saturday
    ({"account_id": "ACME-1001", "when": "2030-01-07 18:00"}, "weekdays"),   # after hours
    ({"account_id": "ACME-1001", "when": "2001-01-08 10:00"}, "future"),     # past
])
def test_book_callback_rejections_write_nothing(agent, callbacks_file, args, expect):
    assert expect in agent.book_callback(args, {}).to_dict()["response"]
    assert not callbacks_file.exists()


def test_transfer_to_human_connects(agent):
    result = agent.transfer_to_human({}, {})
    swml = find(actions(result), "SWML")[0]
    assert json.dumps(swml).count(config.HUMAN_NUMBER) == 1


# --- MCP: JSON-RPC against the real /mcp route ------------------------------

def test_mcp_requires_basic_auth(client):
    assert rpc(client, "tools/list", auth=None).status_code == 401
    assert rpc(client, "tools/list", auth=("tester", "wrong")).status_code == 401


def test_mcp_initialize(client):
    result = rpc(client, "initialize", {"protocolVersion": "2025-06-18"}).json()["result"]
    assert result["capabilities"] == {"tools": {}}
    assert result["serverInfo"]["name"] == "acme-support"


def test_mcp_tools_list_is_the_allowlist(client):
    tools = rpc(client, "tools/list").json()["result"]["tools"]
    assert sorted(t["name"] for t in tools) == sorted(config.MCP_TOOLS)
    book = next(t for t in tools if t["name"] == "book_callback")
    assert book["inputSchema"]["required"] == ["account_id", "when"]


@pytest.mark.parametrize("name, arguments", [
    ("lookup_customer", {"phone": "555 555 0103"}),
    ("lookup_customer", {"phone": "nope"}),
    ("book_callback", {"account_id": "ACME-1002", "when": "2030-01-05 10:00"}),
])
def test_mcp_call_runs_the_same_handler_as_swaig(agent, client, name, arguments):
    direct = getattr(agent, name)(arguments, {}).to_dict()["response"]
    over_mcp = mcp_call(client, name, arguments)["result"]
    assert over_mcp["isError"] is False
    assert over_mcp["content"] == [{"type": "text", "text": direct}]


def test_mcp_book_callback_writes_the_same_file(client, callbacks_file):
    text = mcp_call(client, "book_callback", {"account_id": "ACME-1001", "when": FUTURE_SLOT})
    assert "Booked a callback for Dana Rivera" in text["result"]["content"][0]["text"]
    assert json.loads(callbacks_file.read_text())["account_id"] == "ACME-1001"


# --- governance ---------------------------------------------------------------

def test_governance_voice_only_tool_cannot_be_called_over_mcp(client):
    reply = mcp_call(client, "transfer_to_human", {})
    assert "result" not in reply
    assert reply["error"]["code"] == -32602


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


def ai_of(swml_doc):
    return next(v["ai"] for v in swml_doc["sections"]["main"] if "ai" in v)


def test_governance_voice_still_has_every_tool(swml):
    names = {f["function"] for f in ai_of(swml)["SWAIG"]["functions"]}
    assert {"lookup_customer", "book_callback", "transfer_to_human"} <= names


def test_governance_steps_scope_the_voice_tools(swml):
    steps = {s["name"]: s for s in ai_of(swml)["prompt"]["contexts"]["default"]["steps"]}
    assert steps["identify"]["functions"] == ["lookup_customer"]
    assert steps["identify"]["valid_steps"] == []
    assert "lookup_customer" not in steps["help"]["functions"]
    assert set(steps["help"]["functions"]) == {"book_callback", "transfer_to_human"}
