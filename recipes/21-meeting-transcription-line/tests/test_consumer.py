"""HTTP tests for the consumer and the SWML route, plus a live SSE read over a real socket."""
import base64
import json
import socket
import threading
import time

import httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient

import app as recipe
from consumer import TranscriptStore

CALL = "c0ffee00-0000-4000-8000-000000000021"


@pytest.fixture
def svc(monkeypatch):
    monkeypatch.setenv("SWML_BASIC_AUTH_USER", "recipe")
    monkeypatch.setenv("SWML_BASIC_AUTH_PASSWORD", "test-pass")
    return recipe.create_service()


@pytest.fixture
def store(tmp_path):
    return TranscriptStore(tmp_path)


@pytest.fixture
def auth():
    return {"Authorization": "Basic " + base64.b64encode(b"recipe:test-pass").decode()}


@pytest.fixture
def client(svc, store):
    return TestClient(recipe.create_app(svc, store))


def test_webhook_stores_and_merges(client, store, auth, meeting_events):
    counts = [client.post("/transcript", json=b, headers=auth).json()["segments"] for b in meeting_events]
    assert counts == [1, 1, 1, 1, 0]  # the conversation_log at hangup is stored raw only
    assert client.get("/calls", headers=auth).json() == {"calls": [CALL]}
    segs = client.get(f"/calls/{CALL}", headers=auth).json()["segments"]
    assert [s["speaker"] for s in segs] == ["local-caller", "local-caller", "remote-caller", "remote-caller"]
    assert all("delay_ms" in s for s in segs)
    raw = (store.root / f"{CALL}.raw.jsonl").read_text().splitlines()
    assert len(raw) == len(meeting_events)  # every raw body is kept for the payload TODO


def test_unparseable_body_is_kept_and_acknowledged(client, store, auth):
    r = client.post("/transcript", content=b"not json", headers=auth)
    assert r.status_code == 200 and r.json()["segments"] == 0
    assert (store.root / "unparsed.raw.jsonl").exists()
    assert client.get("/calls", headers=auth).json() == {"calls": []}


def test_every_consumer_route_requires_auth(client, meeting_events):
    assert client.post("/transcript", json=meeting_events[0]).status_code == 401
    assert client.get("/calls").status_code == 401
    assert client.get(f"/calls/{CALL}").status_code == 401
    assert client.get("/events").status_code == 401
    bad = {"Authorization": "Basic " + base64.b64encode(b"recipe:wrong").decode()}
    assert client.post("/transcript", json=meeting_events[0], headers=bad).status_code == 401


def test_swml_route_serves_the_document(client, auth):
    assert client.post("/", json={}).status_code == 401
    doc = client.post("/", json={}, headers=auth).json()
    assert [list(v)[0] for v in doc["sections"]["main"]][:2] == ["answer", "live_transcribe"]


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_sse_rebroadcasts_segments(svc, store, auth, meeting_events):
    port = free_port()
    server = uvicorn.Server(uvicorn.Config(recipe.create_app(svc, store), port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    base = f"http://127.0.0.1:{port}"
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    try:
        httpx.post(f"{base}/transcript", json=meeting_events[2], headers=auth)  # stored before subscribe
        with httpx.stream("GET", f"{base}/events", params={"call_id": CALL}, headers=auth, timeout=5) as r:
            assert r.headers["content-type"].startswith("text/event-stream")
            lines = r.iter_lines()
            replayed = json.loads(next(l for l in lines if l.startswith("data: "))[6:])
            assert replayed["text"].startswith("Good morning, everyone")
            httpx.post(f"{base}/transcript", json=meeting_events[3], headers=auth)  # live
            live = json.loads(next(l for l in lines if l.startswith("data: "))[6:])
            assert (live["speaker"], live["text"]) == ("remote-caller", "First item is the launch date.")
    finally:
        server.should_exit = True
