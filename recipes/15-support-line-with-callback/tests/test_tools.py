"""Handler tests call the SWAIG handlers directly and assert on FunctionResult actions.
Governance tests read the SWML exactly as swaig-test dumps it, per route.
"""
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest
import pytz

RECIPE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RECIPE))

import callback_worker  # noqa: E402
import config  # noqa: E402
import rota  # noqa: E402
import store  # noqa: E402
from app import CallbackAgent, SupportAgent  # noqa: E402

HUMAN, FROM, CALLER = "+15550142", "+15550143", "+15550100"
TICKET = {"issue": "router drops wifi nightly", "summary": "Since Tuesday. Already rebooted twice."}


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CALLBACKS_FILE", tmp_path / "callbacks.json")
    monkeypatch.setattr(config, "HUMAN_NUMBER", HUMAN)
    monkeypatch.setattr(config, "FROM_NUMBER", FROM)
    monkeypatch.setattr(config, "AVAILABILITY", "busy")


@pytest.fixture(scope="module")
def support():
    return SupportAgent()


@pytest.fixture(scope="module")
def callback():
    return CallbackAgent()


def raw(gd=None):
    return {"global_data": gd or {}, "call_id": "call-abc", "caller_id_num": CALLER}


def actions(result):
    return result.to_dict().get("action", [])


def find(acts, key):
    return [a[key] for a in acts if key in a]


def connect_verb(acts):
    return find(acts, "SWML")[0]["sections"]["main"][0]["connect"]


# --- availability ------------------------------------------------------------

def at(local: str) -> datetime:
    return pytz.timezone("America/Chicago").localize(datetime.fromisoformat(local))


def test_rota(monkeypatch):
    monkeypatch.setattr(config, "AVAILABILITY", "rota")
    assert rota.human_available(at("2026-10-28T10:00"))       # Wednesday, Dana on shift
    assert not rota.human_available(at("2026-10-28T18:00"))   # after hours
    assert not rota.human_available(at("2026-10-31T11:00"))   # Saturday, Lee is busy


# --- request_human -----------------------------------------------------------

def test_available_human_path_transfers_directly(support, monkeypatch):
    monkeypatch.setattr(config, "AVAILABILITY", "free")
    acts = actions(support.request_human(TICKET, raw()))
    assert connect_verb(acts) == {"to": HUMAN, "from": FROM}
    assert not find(acts, "change_step")
    assert store.load_all() == {}


def test_busy_path_stores_ticket_and_moves_to_offer_callback(support):
    acts = actions(support.request_human(TICKET, raw()))
    assert find(acts, "set_global_data") == [{"ticket": TICKET}]
    assert find(acts, "change_step") == ["offer_callback"]
    assert not find(acts, "SWML")


def test_request_human_needs_an_issue(support):
    assert actions(support.request_human({"issue": " "}, raw())) == []


# --- schedule_callback -------------------------------------------------------

def test_callback_record_holds_handler_written_context(support):
    result = support.schedule_callback({"preferred_time": "today after 4pm"}, raw({"ticket": TICKET}))
    [rec] = store.load_all().values()
    assert rec["number"] == CALLER                     # from the call, not from the model
    assert rec["issue"] == TICKET["issue"] and rec["summary"] == TICKET["summary"]
    assert rec["preferred_time"] == "today after 4pm" and rec["status"] == "pending"
    assert find(actions(result), "hangup")


def test_schedule_callback_without_triage_writes_nothing(support):
    support.schedule_callback({"preferred_time": "noon"}, raw())
    assert store.load_all() == {}


# --- worker ------------------------------------------------------------------

class FakeCalling:
    def __init__(self):
        self.calls = []

    def dial(self, **kwargs):
        self.calls.append(kwargs)
        return {"id": f"call-{len(self.calls)}"}


class FakeClient:
    def __init__(self):
        self.calling = FakeCalling()


def test_worker_dials_pending_into_callback_route(monkeypatch):
    monkeypatch.setattr(config, "PUBLIC_URL", "https://example.ngrok.app")
    monkeypatch.setenv("SWML_BASIC_AUTH_USER", "u")
    monkeypatch.setenv("SWML_BASIC_AUTH_PASSWORD", "p")
    rec = store.create(CALLER, TICKET["issue"], TICKET["summary"], "today after 4pm")
    client = FakeClient()
    assert callback_worker.sweep(client) == [rec["id"]]
    assert client.calling.calls == [{"from_": FROM, "to": CALLER,
                                     "url": "https://u:p@example.ngrok.app/callback?id=CB-0001"}]
    assert store.get(rec["id"])["status"] == "dialing"
    assert callback_worker.sweep(client) == []   # not dialed twice


# --- the return call ---------------------------------------------------------

def test_dynamic_config_injects_the_saved_context():
    rec = store.create(CALLER, TICKET["issue"], TICKET["summary"], "today after 4pm")
    class Probe:
        def set_global_data(self, data):
            self.data = data

    probe = Probe()
    CallbackAgent.load_context({"id": rec["id"]}, {}, {}, probe)
    assert probe.data == {"callback_id": "CB-0001", "issue": TICKET["issue"],
                          "summary": TICKET["summary"], "preferred_time": "today after 4pm"}
    assert "number" not in probe.data        # the phone number stays out of the model's context
    CallbackAgent.load_context({"id": "CB-9999"}, {}, {}, probe)
    assert probe.data["callback_id"] is None


def test_connect_human_marks_record_and_transfers(callback):
    rec = store.create(CALLER, TICKET["issue"], TICKET["summary"], "noon")
    acts = actions(callback.connect_human({}, raw({"callback_id": rec["id"]})))
    assert connect_verb(acts) == {"to": HUMAN, "from": FROM}
    assert store.get(rec["id"])["status"] == "connected"


# --- governance: the SWML swaig-test dumps ------------------------------------

def swaig_test_bin() -> str:
    local = Path(sys.executable).with_name("swaig-test")
    return str(local) if local.exists() else (shutil.which("swaig-test") or "swaig-test")


def dump(agent_class, query=None, env=None):
    cmd = [swaig_test_bin(), str(RECIPE / "app.py"), "--agent-class", agent_class, "--dump-swml", "--raw"]
    if query:
        cmd += ["--query-params", json.dumps(query)]
    out = subprocess.run(cmd, capture_output=True, text=True, check=True, cwd=RECIPE,
                         env={**os.environ, **(env or {})}).stdout
    return next(v["ai"] for v in json.loads(out)["sections"]["main"] if "ai" in v)


def steps_of(ai):
    return {s["name"]: s for s in ai["prompt"]["contexts"]["default"]["steps"]}


def test_governance_support_steps():
    steps = steps_of(dump("SupportAgent"))
    assert steps["triage"]["functions"] == ["request_human"]
    assert steps["offer_callback"]["functions"] == ["schedule_callback"]
    assert all(s["valid_steps"] == [] for s in steps.values())


def test_governance_return_call_global_data_comes_from_the_store(tmp_path):
    path = tmp_path / "callbacks.json"
    path.write_text(json.dumps({"CB-0007": {
        "id": "CB-0007", "number": CALLER, "issue": "no dial tone", "summary": "Since noon.",
        "preferred_time": "after 5pm", "status": "dialing", "created_at": "x", "call_id": "c"}}))
    ai = dump("CallbackAgent", {"id": "CB-0007"}, {"CALLBACKS_FILE": str(path)})
    assert ai["global_data"] == {"callback_id": "CB-0007", "issue": "no dial tone",
                                 "summary": "Since noon.", "preferred_time": "after 5pm"}
    assert steps_of(ai)["returning"]["functions"] == ["connect_human"]
    assert [f["function"] for f in ai["SWAIG"]["functions"]] == ["connect_human"]
