"""Shared tools (concierge.py) behave identically from voice and web chat; the widget's
wire flow against the gateway with a mock chat endpoint; governance on the SWML."""
import json
import shutil
import subprocess
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

RECIPE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RECIPE))

import config  # noqa: E402
from app import WebConcierge  # noqa: E402
from signalwire.ai_chat import ChatLog, ConversationInfo  # noqa: E402

VOICE = {"call_id": "c1", "caller_id_num": "+15550142"}
CHAT = {"call_id": "chat-abc", "conversation_type": "chat"}
GUEST = {"global_data": {"guest": {"room": "412", "name": "Alex Rivera"}}}
ORIGIN = "http://localhost:3128"


class MockChatEndpoint:
    """Stands in for AIChatClient (the AI Chat service) behind ChatGateway."""

    def __init__(self):
        self.turns, self.created = [], []

    async def create_conversation(self, conversation_id, config_url, timeout=None, user_metadata=None, **kw):
        self.created.append({"id": conversation_id, "config_url": config_url})
        return ConversationInfo(id=conversation_id, status="created", initial_message="Hi! Room number and last name?")

    @asynccontextmanager
    async def raw_post(self, method, params):
        self.turns.append({"method": method, **params})
        body = b'  {"jsonrpc": "2.0", "result": {"response": "Verified. How can I help?"}, "id": "r1"}'

        class Content:
            async def iter_any(self):
                yield body

        yield type("Resp", (), {"content": Content()})()

    async def log(self, conversation_id):
        return ChatLog(messages=[{"role": "system", "content": "SECRET PROMPT"},
                                 {"role": "assistant", "content": "Hi!", "timestamp": 1.0e6}])

    async def end(self, conversation_id):
        return True


@pytest.fixture(autouse=True)
def requests_file(tmp_path, monkeypatch):
    path = tmp_path / "requests.json"
    monkeypatch.setattr(config, "REQUESTS_FILE", path)
    return path


@pytest.fixture
def mock():
    return MockChatEndpoint()


@pytest.fixture
def agent(mock):
    return WebConcierge(chat_client=mock)


@pytest.fixture
def client(agent):
    from fastapi.testclient import TestClient
    return TestClient(agent.get_app())


def widget(client, agent, body, key=None, origin=ORIGIN):
    headers = {"Authorization": f"Bearer {key or agent.gateway.key}", "Origin": origin}
    return client.post(config.CHAT_ROUTE + "/", json=body, headers=headers)


def actions(result):
    return result.to_dict().get("action", [])


# --- shared tools: same result from a call and from the web chat ---------------

CASES = [
    ("verify_guest", {"room": "412", "last_name": "Rivera"}, {}),
    ("verify_guest", {"room": "412", "last_name": "Smith"}, {}),
    ("amenity_hours", {"amenity": "Pool"}, GUEST),
    ("amenity_hours", {"amenity": "casino"}, GUEST),
    ("request_service", {"service": "extra towels"}, GUEST),
    ("request_service", {"service": "a pony"}, GUEST),
    ("request_service", {"service": "housekeeping"}, {}),
]


@pytest.mark.parametrize("tool,args,state", CASES)
def test_tool_behaves_identically_on_voice_and_web(agent, requests_file, tool, args, state):
    voice = getattr(agent, tool)(args, {**VOICE, **state}).to_dict()
    requests_file.unlink(missing_ok=True)
    web = getattr(agent, tool)(args, {**CHAT, **state}).to_dict()
    assert voice == web


def test_verify_opens_concierge(agent):
    acts = actions(agent.verify_guest({"room": "412", "last_name": "rivera"}, CHAT))
    assert {"change_step": "concierge"} in acts


def test_request_uses_room_from_global_data(agent, requests_file):
    agent.request_service({"service": "wake-up call", "room": "1108"}, {**CHAT, **GUEST})
    [row] = json.loads(requests_file.read_text())
    assert row["room"] == "412" and row["channel"] == "text"


def test_amenity_lookup(agent):
    assert "Atrium" in agent.amenity_hours({"amenity": "breakfast"}, GUEST).to_dict()["response"]


# --- widget smoke test: the page, its config, and the gateway flow ------------

def test_site_serves_page_widget_and_config(client, agent):
    page = client.get(config.SITE_ROUTE + "/")
    assert page.status_code == 200 and 'src="widget.js"' in page.text and 'src="widget-config.js"' in page.text
    js = client.get(config.SITE_ROUTE + "/widget.js")
    assert "X-Chat-Handle" in js.text and "Bearer" in js.text
    cfg = client.get(config.SITE_ROUTE + "/widget-config.js").text
    settings = json.loads(cfg.split("=", 1)[1].strip().rstrip(";"))
    assert settings["key"] == agent.gateway.key and settings["endpoint"] == config.CHAT_ROUTE + "/"
    assert settings["position"] == config.WIDGET["position"]
    assert "SIGNALWIRE" not in cfg and "config_url" not in cfg  # nothing secret reaches the page


def test_widget_flow_start_chat_log_end(client, agent, mock):
    start = widget(client, agent, {"method": "start"})
    assert start.json()["greeting"].startswith("Hi!")
    handle = start.headers["X-Chat-Handle"]

    turn = widget(client, agent, {"handle": handle, "message": "Room 412, Rivera"})
    assert json.loads(turn.text)["result"]["response"] == "Verified. How can I help?"
    assert mock.turns[-1]["message"] == "Room 412, Rivera"
    assert mock.turns[-1]["id"] == mock.created[0]["id"]  # same conversation from the handle

    history = widget(client, agent, {"method": "log", "handle": handle}).json()
    assert [m["role"] for m in history["messages"]] == ["assistant"]  # system prompt filtered out
    assert widget(client, agent, {"method": "end", "handle": handle}).json() == {"status": "ended"}


def test_browser_cannot_choose_the_agent(client, agent, mock):
    widget(client, agent, {"message": "hi", "config_url": "https://evil.example/swml"})
    assert mock.turns[-1]["config_url"] == agent.config_url()  # pinned to this agent's SWML URL


def test_wrong_key_and_foreign_origin_are_refused(client, agent, mock):
    assert widget(client, agent, {"message": "hi"}, key="pk_wrong").status_code in (401, 403)
    assert widget(client, agent, {"message": "hi"}, origin="https://other.example").status_code == 403
    assert mock.turns == []


def test_service_error_on_start_is_a_json_502(client, agent, mock):
    from signalwire.ai_chat import AIChatError

    async def fail(*a, **kw):
        raise AIChatError(-32008, "Configuration validation failed")
    mock.create_conversation = fail
    r = widget(client, agent, {"method": "start"})
    assert r.status_code == 502 and r.json() == {"error": "chat service error"}


def test_without_credentials_voice_still_works_and_chat_says_why(monkeypatch):
    monkeypatch.delenv("SIGNALWIRE_PROJECT_ID", raising=False)
    bare = WebConcierge()
    assert bare.gateway is None
    from fastapi.testclient import TestClient
    r = TestClient(bare.get_app()).post(config.CHAT_ROUTE + "/", json={"message": "hi"})
    assert r.status_code == 503 and "not configured" in r.json()["error"]


# --- governance: one agent definition, same SWML for a call and a chat config fetch

def ai_of(doc):
    return next(v["ai"] for v in doc["sections"]["main"] if "ai" in v)


def test_chat_config_fetch_gets_the_same_steps_and_tools_as_a_call(agent, client):
    auth = agent.get_basic_auth_credentials()[:2]
    voice = ai_of(client.post("/", json={"call": {"call_id": "c1", "from": "+15550142"}}, auth=auth).json())
    chat = ai_of(client.post("/", json={"conversation_type": "chat", "conversation_id": "chat-abc",
                                        "call_id": "chat-abc"}, auth=auth).json())
    assert chat["prompt"]["contexts"] == voice["prompt"]["contexts"]
    names = lambda ai: sorted(f["function"] for f in ai["SWAIG"]["functions"])  # noqa: E731
    assert names(chat) == names(voice) == ["amenity_hours", "request_service", "verify_guest"]


def swaig_test_bin() -> str:
    local = Path(sys.executable).with_name("swaig-test")
    return str(local) if local.exists() else (shutil.which("swaig-test") or "swaig-test")


@pytest.fixture(scope="module")
def steps():
    out = subprocess.run([swaig_test_bin(), str(RECIPE / "app.py"), "--dump-swml", "--raw"],
                         capture_output=True, text=True, check=True, cwd=RECIPE).stdout
    return {s["name"]: s for s in ai_of(json.loads(out))["prompt"]["contexts"]["default"]["steps"]}


def test_governance_only_verify_guest_before_verification(steps):
    assert steps["verify"]["functions"] == ["verify_guest"] and steps["verify"]["valid_steps"] == []


def test_governance_concierge_tools(steps):
    assert steps["concierge"]["functions"] == ["amenity_hours", "request_service"]
