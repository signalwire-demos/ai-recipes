"""Tests for the sales copilot.

1. The classifier against fixture transcripts (data/transcripts.json).
2. The flag_objection handler and the sidecar event consumer, called directly.
3. The rep page: static files, auth, and the SSE card stream.
4. Governance, against the SWML that swaig-test dumps: the sidecar listens to both legs,
   has exactly one tool, and nothing from the playbook's talk tracks is in its prompt.
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

RECIPE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RECIPE))

import config  # noqa: E402
from app import SalesCopilot, build_app, classify  # noqa: E402

FIXTURES = json.loads((RECIPE / "data" / "transcripts.json").read_text())["calls"]
CUSTOMER_LINES = [(c["name"], l) for c in FIXTURES for l in c["lines"] if l["speaker"] == "customer"]


@pytest.fixture
def svc():
    return SalesCopilot()


@pytest.fixture
def client(svc):
    return TestClient(build_app(svc)), svc.get_basic_auth_credentials()


def stream(client):
    http, auth = client
    text = http.get("/rep/stream?once=1", auth=auth).text
    return [json.loads(line[6:]) for line in text.splitlines() if line.startswith("data: ")]


# --- classifier ---------------------------------------------------------------

@pytest.mark.parametrize("name,line", CUSTOMER_LINES, ids=[f"{n}:{l['text'][:24]}" for n, l in CUSTOMER_LINES])
def test_classifier_fixtures(name, line):
    assert sorted(classify(line["text"])) == sorted(line["expect"])


def test_classifier_handles_empty_text():
    assert classify("") == [] and classify(None) == []


# --- flag_objection handler -------------------------------------------------

def test_flag_objection_pushes_playbook_card(svc):
    result = svc.flag_objection({"customer_quote": "That's too expensive"}, {"call_id": "c1"})
    cards = svc.feed.since(0)
    assert [c["category"] for c in cards] == ["pricing"]
    assert cards[0]["tips"] == config.PLAYBOOK["pricing"]["tips"]
    assert cards[0]["quote"] == "That's too expensive" and cards[0]["source"] == "sidecar"
    assert result.to_dict()["response"].startswith("The rep has the playbook card")


def test_flag_objection_response_never_contains_talk_track(svc):
    response = svc.flag_objection({"customer_quote": "We use Globex and it's cheaper"}, {"call_id": "c1"})
    text = response.to_dict()["response"]
    for spec in config.PLAYBOOK.values():
        assert not any(tip in text for tip in spec["tips"])


def test_flag_objection_no_match_pushes_nothing(svc):
    result = svc.flag_objection({"customer_quote": "How does routing work?"}, {"call_id": "c1"})
    assert svc.feed.since(0) == []
    assert "not a playbook objection" in result.to_dict()["response"]


def test_same_objection_on_same_call_is_not_repeated(svc):
    svc.flag_objection({"customer_quote": "too expensive"}, {"call_id": "c1"})
    svc.flag_objection({"customer_quote": "the price is high"}, {"call_id": "c1"})
    svc.flag_objection({"customer_quote": "the price is high"}, {"call_id": "c2"})
    assert [(c["call_id"], c["category"]) for c in svc.feed.since(0)] == [("c1", "pricing"), ("c2", "pricing")]


# --- sidecar event consumer ---------------------------------------------------

def event(kind, **fields):
    return {"call_info": {"call_id": "call-1"}, "sidecar_event": {"type": kind, "ts": 1, "tick_id": 1, **fields}}


def test_insight_event_becomes_card(svc):
    cards = svc.on_event(event("insight", raw="Ask about their timeline.", iter=0, total_iters=1))
    assert cards[0]["kind"] == "insight" and cards[0]["text"] == "Ask about their timeline."
    assert cards[0]["call_id"] == "call-1"


def test_final_event_becomes_card(svc):
    assert svc.on_event(event("final", stop_reason="transcribe_close"))[0]["text"] == "transcribe_close"


def test_transcript_event_runs_classifier(svc):
    cards = svc.on_event(event("transcription", text="I need sign-off from procurement"))
    assert [c["category"] for c in cards] == ["authority"] and cards[0]["source"] == "transcript"


def test_unknown_or_top_level_events_are_ignored(svc):
    assert svc.on_event({"type": "insight", "raw": "top-level, not under sidecar_event"}) == []
    assert svc.on_event(event("say", text="too expensive")) == []
    assert svc.feed.since(0) == []


# --- rep page and card stream -----------------------------------------------

def test_rep_page_and_events_need_basic_auth(client):
    http, auth = client
    assert http.get("/rep/").status_code == 401
    assert http.post("/events", json={}).status_code == 401
    page = http.get("/rep/", auth=auth)
    assert page.status_code == 200 and 'src="rep.js"' in page.text
    assert "new EventSource(\"stream\")" in http.get("/rep/rep.js", auth=auth).text


def test_card_stream_renders_events_in_order(client):
    http, auth = client
    http.post("/events", auth=auth, json=event("insight", raw="Mirror their words."))
    http.post("/swaig", auth=auth, json={"function": "flag_objection", "call_id": "call-1",
                                          "argument": {"parsed": [{"customer_quote": "not right now"}]}})
    cards = stream(client)
    assert [c["kind"] for c in cards] == ["insight", "objection"]
    assert cards[1]["category"] == "timing" and [c["id"] for c in cards] == [1, 2]
    assert http.get("/rep/stream?once=1", auth=auth, headers={"Last-Event-ID": "1"}).text.count("data: ") == 1


def test_swml_is_served_behind_auth(client):
    http, auth = client
    assert http.post("/").status_code == 401
    assert "ai_sidecar" in http.post("/", auth=auth).text


# --- governance: read the SWML exactly as swaig-test dumps it ---------------

def swaig_test_bin() -> str:
    local = Path(sys.executable).with_name("swaig-test")
    return str(local) if local.exists() else (shutil.which("swaig-test") or "swaig-test")


@pytest.fixture(scope="module")
def swml():
    out = subprocess.run([swaig_test_bin(), str(RECIPE / "app.py"), "--dump-swml", "--raw"],
                         capture_output=True, text=True, check=True, cwd=RECIPE).stdout
    return json.loads(out)


def verb(doc, name):
    return next(v[name] for v in doc["sections"]["main"] if name in v)


def test_governance_sidecar_rides_the_call_it_does_not_own(swml):
    names = [next(iter(v)) for v in swml["sections"]["main"]]
    assert names == ["answer", "ai_sidecar", "connect", "hangup"]   # attached before the bridge
    assert "ai" not in names                                         # no agent owns the call
    side = verb(swml, "ai_sidecar")
    assert sorted(side["direction"]) == ["local-caller", "remote-caller"]   # both legs
    assert side["url"].endswith("/events")


def test_governance_sidecar_has_exactly_one_tool(swml):
    side = verb(swml, "ai_sidecar")
    assert [f["function"] for f in side["SWAIG"]["functions"]] == ["flag_objection"]
    assert side["SWAIG"]["defaults"]["web_hook_url"].endswith("/swaig")


def test_governance_model_never_sees_the_playbook(swml):
    dumped = json.dumps(swml)
    for spec in config.PLAYBOOK.values():
        for tip in spec["tips"]:
            assert tip not in dumped
