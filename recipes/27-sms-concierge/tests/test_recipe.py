"""Shared tools (concierge.py) behave identically from both entry points; the /sms
webhook drives the AI Chat service with the same agent's URL; governance on the SWML."""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

RECIPE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RECIPE))

import config  # noqa: E402
from app import SmsConcierge, conversation_id  # noqa: E402
from signalwire.ai_chat import ChatInProgressError, ChatResponse  # noqa: E402

VOICE = {"call_id": "c1", "caller_id_num": "+15550142"}
CHAT = {"call_id": "sms.15550142", "conversation_type": "chat"}
GUEST = {"global_data": {"guest": {"room": "412", "name": "Alex Rivera"}}}


class FakeChat:
    """Stands in for AIChatClient: records each turn, returns a canned reply."""

    def __init__(self, reply="The pool is open 7:00 to 22:00.", exc=None):
        self.calls, self.reply, self.exc = [], reply, exc

    async def chat(self, conversation_id, message, config_url=None, **kw):
        self.calls.append({"id": conversation_id, "message": message, "config_url": config_url})
        if self.exc:
            raise self.exc
        return ChatResponse(text=self.reply, conversation_id=conversation_id)


@pytest.fixture(autouse=True)
def requests_file(tmp_path, monkeypatch):
    path = tmp_path / "requests.json"
    monkeypatch.setattr(config, "REQUESTS_FILE", path)
    return path


@pytest.fixture
def fake():
    return FakeChat()


@pytest.fixture
def agent(fake):
    return SmsConcierge(chat_client=fake)


@pytest.fixture
def client(agent):
    from fastapi.testclient import TestClient
    return TestClient(agent.get_app())


def actions(result):
    return result.to_dict().get("action", [])


def find(acts, key):
    return [a[key] for a in acts if key in a]


# --- shared tools: same result from a call and from a text conversation --------

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
def test_tool_behaves_identically_on_voice_and_text(agent, requests_file, tool, args, state):
    voice = getattr(agent, tool)(args, {**VOICE, **state}).to_dict()
    requests_file.unlink(missing_ok=True)  # same starting state for the second run
    text = getattr(agent, tool)(args, {**CHAT, **state}).to_dict()
    assert voice == text


def test_verify_sets_guest_and_opens_concierge(agent):
    acts = actions(agent.verify_guest({"room": "Room 412", "last_name": " rivera "}, VOICE))
    assert find(acts, "set_global_data") == [{"guest": {"room": "412", "name": "Alex Rivera"}}]
    assert find(acts, "change_step") == ["concierge"]


def test_verify_mismatch_does_not_advance(agent):
    assert actions(agent.verify_guest({"room": "1108", "last_name": "rivera"}, VOICE)) == []


def test_amenity_hours(agent):
    assert "Atrium" in agent.amenity_hours({"amenity": "breakfast"}, GUEST).to_dict()["response"]
    assert "Amenities:" in agent.amenity_hours({"amenity": "casino"}, GUEST).to_dict()["response"]


def test_request_uses_room_from_global_data_and_records_channel(agent, requests_file):
    agent.request_service({"service": "late checkout", "room": "1108"}, {**CHAT, **GUEST})
    [row] = json.loads(requests_file.read_text())
    assert row["room"] == "412"  # the model can't redirect the request to another room
    assert row["service"] == "late checkout" and row["channel"] == "text"


def test_request_outside_the_tool_set_is_refused(agent, requests_file):
    result = agent.request_service({"service": "a pony"}, GUEST)
    assert "only log" in result.to_dict()["response"] and not requests_file.exists()


def test_request_before_verification_is_refused(agent, requests_file):
    assert "Verify" in agent.request_service({"service": "housekeeping"}, {}).to_dict()["response"]
    assert not requests_file.exists()


# --- /sms: both inbound payload formats drive AIChatClient.chat ------------------

def test_swml_webhook_payload_chats_and_replies_with_messaging_swml(client, fake, agent):
    body = {"message": {"from": "+15550142", "to": "+15550100", "body": "When is the pool open?"}}
    r = client.post(config.SMS_ROUTE, json=body)
    assert r.json() == {"version": "1.0.0", "sections": {"main": [{"reply": fake.reply}]}}
    [turn] = fake.calls
    assert turn["id"] == "sms.15550142" and turn["message"] == "When is the pool open?"
    assert turn["config_url"] == agent.config_url()  # the same SWML a voice call gets


def test_laml_form_payload_replies_with_cxml(client, fake):
    r = client.post(config.SMS_ROUTE, data={"From": "+15550142", "To": "+15550100", "Body": "hi"})
    assert r.headers["content-type"].startswith("application/xml")
    assert f"<Message>{fake.reply}</Message>" in r.text
    assert fake.calls[0]["id"] == "sms.15550142"


def test_empty_text_is_not_sent_to_the_agent(client, fake):
    r = client.post(config.SMS_ROUTE, json={"message": {"from": "+15550142", "body": ""}})
    assert "as text" in r.text and fake.calls == []


def test_busy_conversation_gets_a_holding_reply():
    agent = SmsConcierge(chat_client=FakeChat(exc=ChatInProgressError(-32007, "busy")))
    import asyncio
    assert "still working" in asyncio.run(agent.answer("+15550142", "hello?"))


def test_signature_required_when_signing_key_set(client, monkeypatch):
    monkeypatch.setattr(config, "SIGNING_KEY", "PSK_test")
    assert client.post(config.SMS_ROUTE, data={"From": "+15550142", "Body": "hi"}).status_code == 403


def test_conversation_id_is_stable_and_safe():
    assert conversation_id("+1 (555) 0142") == conversation_id("+15550142") == "sms.15550142"


# --- governance: one agent definition, same SWML for a call and a chat config fetch

def ai_of(doc):
    return next(v["ai"] for v in doc["sections"]["main"] if "ai" in v)


def test_chat_config_fetch_gets_the_same_steps_and_tools_as_a_call(agent, client):
    auth = agent.get_basic_auth_credentials()[:2]
    voice = ai_of(client.post("/", json={"call": {"call_id": "c1", "from": "+15550142"}}, auth=auth).json())
    chat = ai_of(client.post("/", json={"conversation_type": "chat", "conversation_id": "sms.15550142",
                                        "call_id": "sms.15550142"}, auth=auth).json())
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
    assert steps["verify"]["functions"] == ["verify_guest"]
    assert steps["verify"]["valid_steps"] == []  # only the handler opens the concierge step
    assert "request_service" not in steps["verify"]["functions"]


def test_governance_concierge_tools(steps):
    assert steps["concierge"]["functions"] == ["amenity_hours", "request_service"]
    assert "verify_guest" not in steps["concierge"]["functions"]
