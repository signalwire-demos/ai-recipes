"""Tests: each handler directly, the same handlers over MCP JSON-RPC, and governance.

MCP calls go through Starlette's TestClient against agent.get_app(), the same
FastAPI app `python app.py` serves, so /mcp auth and routing are the real ones.
"""
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

os.environ["SWML_BASIC_AUTH_USER"] = "tester"
os.environ["SWML_BASIC_AUTH_PASSWORD"] = "test-pass"
os.environ["MCP_TOKEN"] = "mcp-test-token"

RECIPE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RECIPE))

import config  # noqa: E402
from app import PhoneAgent, callback_window_text  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

AUTH = ("tester", "test-pass")                         # SWML basic auth
MCP = {"Authorization": "Bearer mcp-test-token"}       # /mcp's own credential
# Values the caller gives on the phone. account_id comes from global_data, never the caller.
CALLER_SUPPLIED = [("lookup_customer", "phone"), ("book_callback", "phone"), ("book_callback", "when"),
                   ("book_callback", "reason")]
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


def rpc(client, method, params=None, headers=MCP, auth=None):
    body = {"jsonrpc": "2.0", "id": 1, "method": method}
    if params is not None:
        body["params"] = params
    return client.post("/mcp", json=body, headers=headers, auth=auth)


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
    result = agent.book_callback({"account_id": "acme-1003", "phone": "555-555-0103", "when": FUTURE_SLOT,
                                  "reason": "IP"}, {})
    assert "Booked a callback for Priya Shah" in result.to_dict()["response"]
    rows = [json.loads(line) for line in callbacks_file.read_text().splitlines()]
    assert rows == [{"account_id": "ACME-1003", "when": FUTURE_SLOT, "reason": "IP"}]
    assert find(actions(result), "set_global_data")[0]["callback"]["account_id"] == "ACME-1003"


DANA = {"account_id": "ACME-1001", "phone": "+15555550101"}


@pytest.mark.parametrize("args, expect", [
    ({"account_id": "ACME-9999", "phone": "+15555550101", "when": FUTURE_SLOT}, "no account"),
    ({"account_id": "ACME-1001", "when": FUTURE_SLOT}, "no account"),                         # no phone
    ({"account_id": "ACME-1001", "phone": "+15555550102", "when": FUTURE_SLOT}, "no account"),  # Sam's phone
    ({**DANA, "when": "next tuesday"}, "YYYY-MM-DD HH:MM"),
    ({**DANA, "when": "2030-01-05 10:00"}, "weekdays"),   # Saturday
    ({**DANA, "when": "2030-01-07 18:00"}, "weekdays"),   # after hours
    ({**DANA, "when": "2001-01-08 10:00"}, "future"),     # past
])
def test_book_callback_rejections_write_nothing(agent, callbacks_file, args, expect):
    assert expect in agent.book_callback(args, {}).to_dict()["response"]
    assert not callbacks_file.exists()


def test_voice_books_for_the_looked_up_account_not_the_model_arg(agent, callbacks_file):
    # On a call, lookup_customer put the account in global_data; a different id in args is ignored.
    raw = {"global_data": {"account_id": "ACME-1002", "name": "Sam Okafor", "plan": "Fiber 1000"}}
    result = agent.book_callback({"account_id": "ACME-1001", "when": FUTURE_SLOT}, raw)
    assert "Sam Okafor" in result.to_dict()["response"]
    assert json.loads(callbacks_file.read_text())["account_id"] == "ACME-1002"


def test_transfer_to_human_connects(agent):
    result = agent.transfer_to_human({}, {})
    swml = find(actions(result), "SWML")[0]
    assert json.dumps(swml).count(config.HUMAN_NUMBER) == 1


# --- MCP: JSON-RPC against the real /mcp route ------------------------------

def test_mcp_requires_its_own_token(client):
    assert rpc(client, "tools/list", headers={}).status_code == 401
    assert rpc(client, "tools/list", headers={"Authorization": "Bearer wrong"}).status_code == 401
    # The SWML basic-auth credential (the one in the number's webhook URL) doesn't open /mcp.
    assert rpc(client, "tools/list", headers={}, auth=AUTH).status_code == 401


def test_mcp_token_does_not_open_the_swml_route(client):
    assert client.post("/", json={}, headers=MCP).status_code == 401
    assert client.post("/", json={}, auth=AUTH).status_code == 200


def test_mcp_with_no_token_configured_refuses_everything(client, monkeypatch):
    monkeypatch.setattr(config, "MCP_TOKEN", "")
    assert rpc(client, "tools/list", headers={"Authorization": "Bearer "}).status_code == 401
    assert rpc(client, "tools/list", headers={}).status_code == 401


def test_mcp_initialize(client):
    result = rpc(client, "initialize", {"protocolVersion": "2025-06-18"}).json()["result"]
    assert result["capabilities"] == {"tools": {}}
    assert result["serverInfo"]["name"] == "acme-support"


def test_mcp_tools_list_is_the_allowlist(client):
    tools = rpc(client, "tools/list").json()["result"]["tools"]
    assert sorted(t["name"] for t in tools) == sorted(config.MCP_TOOLS)
    book = next(t for t in tools if t["name"] == "book_callback")
    assert book["inputSchema"]["required"] == ["account_id", "phone", "when"]


@pytest.mark.parametrize("name, arguments", [
    ("lookup_customer", {"phone": "555 555 0103"}),
    ("lookup_customer", {"phone": "nope"}),
    ("book_callback", {"account_id": "ACME-1002", "phone": "555 555 0102", "when": "2030-01-05 10:00"}),
    ("book_callback", {"account_id": "ACME-1002", "phone": "555 555 0101", "when": FUTURE_SLOT}),
])
def test_mcp_call_runs_the_same_handler_as_swaig(agent, client, name, arguments):
    direct = getattr(agent, name)(arguments, {}).to_dict()["response"]
    over_mcp = mcp_call(client, name, arguments)["result"]
    assert over_mcp["isError"] is False
    assert over_mcp["content"] == [{"type": "text", "text": direct}]


def test_mcp_book_callback_needs_the_accounts_phone(client, callbacks_file):
    # An account id guessed in sequence isn't enough over MCP.
    for guess in ("ACME-1002", "ACME-1003"):
        reply = mcp_call(client, "book_callback", {"account_id": guess, "phone": "+15555550101", "when": FUTURE_SLOT})
        assert "no account" in reply["result"]["content"][0]["text"]
    assert not callbacks_file.exists()


def test_mcp_book_callback_writes_the_same_file(client, callbacks_file):
    text = mcp_call(client, "book_callback", {**DANA, "when": FUTURE_SLOT})
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


def test_governance_tool_schemas_are_typed_and_ask(swml):
    props = {f["function"]: f["parameters"]["properties"] for f in ai_of(swml)["SWAIG"]["functions"]}
    when, phone = props["book_callback"]["when"], props["lookup_customer"]["phone"]
    assert re.fullmatch(when["pattern"], FUTURE_SLOT)
    for loose in ("next tuesday", "2030-01-07 2:30", "2030-01-07"):
        assert not re.fullmatch(when["pattern"], loose), loose
    assert "24-hour" in when["description"] and "never assume today" in when["description"]
    for ok in ("5555550101", "15555550101", "+15555550101"):
        assert re.fullmatch(phone["pattern"], ok), ok
    assert not re.fullmatch(phone["pattern"], "(555) 555-0101")
    assert "never use the caller ID" in phone["description"]
    for tool, name in CALLER_SUPPLIED:
        desc = props[tool][name]["description"].lower()
        assert "ask" in desc, f"{tool}.{name}: the description must tell the model to ask"
    assert "lookup_customer" in props["book_callback"]["account_id"]["description"]


def test_governance_help_step_states_the_window_and_asks_for_the_slot(swml):
    text = next(s for s in ai_of(swml)["prompt"]["contexts"]["default"]["steps"] if s["name"] == "help")["text"]
    start, end = config.CALLBACK_HOURS
    assert callback_window_text() == f"Callbacks run Monday to Friday, {start}:00 to {end}:00 local time."
    assert text.startswith(callback_window_text())
    assert "ask for the day and then the time, one at a time" in text
    assert "never assume today or pick a slot yourself" in text


def test_governance_mcp_serves_the_same_schemas_as_voice(client, swml):
    over_mcp = {t["name"]: t["inputSchema"] for t in rpc(client, "tools/list").json()["result"]["tools"]}
    voice = {f["function"]: f["parameters"] for f in ai_of(swml)["SWAIG"]["functions"]}
    for name in config.MCP_TOOLS:
        assert over_mcp[name] == voice[name], name   # same patterns and "ask" text on both channels
