"""Access split: the platform login writes and lists, the viewer login only reads one named call.
Plus the optional webhook signature and the bounded SSE queues."""
import asyncio
import base64
import hashlib
import hmac
import json
import socket
import threading
import time

import httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient

import app as recipe
import config
from adapter import Segment
from consumer import Broker, TranscriptStore

CALL = "c0ffee00-0000-4000-8000-000000000021"


def basic(user, password):
    return {"Authorization": "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()}


PLATFORM, VIEWER = basic("recipe", "test-pass"), basic("screen", "view-pass")


@pytest.fixture
def svc(monkeypatch):
    monkeypatch.setenv("SWML_BASIC_AUTH_USER", "recipe")
    monkeypatch.setenv("SWML_BASIC_AUTH_PASSWORD", "test-pass")
    monkeypatch.setattr(config, "VIEWER_USER", "screen")
    monkeypatch.setattr(config, "VIEWER_PASSWORD", "view-pass")
    monkeypatch.setattr(config, "PUBLIC_URL", "https://example.ngrok.app")
    monkeypatch.setattr(config, "TRANSCRIPT_WEBHOOK_URL", "")
    monkeypatch.setattr(config, "SIGNING_KEY", "")
    return recipe.create_service()


@pytest.fixture
def store(tmp_path):
    return TranscriptStore(tmp_path)


@pytest.fixture
def client(svc, store):
    return TestClient(recipe.create_app(svc, store))


def test_viewer_cannot_post_fake_segments(client, store, meeting_events):
    r = client.post("/transcript", json=meeting_events[2], headers=VIEWER)
    assert r.status_code == 403
    assert list(store.root.iterdir()) == []  # nothing stored, nothing broadcast


def test_viewer_reads_one_named_call_only(client, meeting_events):
    client.post("/transcript", json=meeting_events[2], headers=PLATFORM)
    segs = client.get(f"/calls/{CALL}", headers=VIEWER).json()["segments"]
    assert segs[0]["text"].startswith("Good morning")
    assert client.get("/calls", headers=VIEWER).status_code == 403      # no listing of every call
    assert client.get("/events", headers=VIEWER).status_code == 403     # no all-calls firehose
    assert client.get("/calls", headers=PLATFORM).json() == {"calls": [CALL]}


def test_viewer_login_off_when_unset_or_same_as_platform(svc, store, monkeypatch):
    monkeypatch.setattr(config, "VIEWER_PASSWORD", "")
    client = TestClient(recipe.create_app(svc, store))
    assert client.get(f"/calls/{CALL}", headers=VIEWER).status_code == 401
    assert client.get(f"/calls/{CALL}", headers=basic("screen", "")).status_code == 401
    monkeypatch.setattr(config, "VIEWER_USER", "recipe")
    monkeypatch.setattr(config, "VIEWER_PASSWORD", "test-pass")
    platform, viewer = recipe.auth_checkers(svc)
    assert platform({"authorization": PLATFORM["Authorization"]}) and not viewer({"authorization": PLATFORM["Authorization"]})


def test_signing_key_requires_a_valid_signature(svc, store, monkeypatch, meeting_events):
    monkeypatch.setattr(config, "SIGNING_KEY", "test-signing-key")
    client = TestClient(recipe.create_app(svc, store))
    raw = json.dumps(meeting_events[2])
    url = "https://example.ngrok.app/transcript"  # the webhook URL without its user:pass@
    good = hmac.new(b"test-signing-key", (url + raw).encode(), hashlib.sha1).hexdigest()
    hdr = {**PLATFORM, "Content-Type": "application/json"}
    assert client.post("/transcript", content=raw, headers=hdr).status_code == 403
    assert client.post("/transcript", content=raw, headers={**hdr, "X-SignalWire-Signature": "0" * 40}).status_code == 403
    assert client.post("/transcript", content=raw, headers={**hdr, "X-SignalWire-Signature": good}).status_code == 200
    assert client.post("/transcript", content=raw, headers={**VIEWER, "X-SignalWire-Signature": good}).status_code == 403


def seg(call_id, text="hi"):
    return Segment(call_id=call_id, speaker="remote-caller", text=text, is_final=True, ts=1.0, received_at=1.0)


def test_slow_sse_subscriber_is_dropped_not_buffered_forever():
    async def run():
        broker = Broker(maxsize=2)
        stream = broker.stream(CALL, keepalive=5)
        task = asyncio.ensure_future(stream.__anext__())  # subscribes, then waits on the queue
        await asyncio.sleep(0)
        broker.publish(seg("other-call"))                 # filtered out before queuing
        broker.publish(seg(CALL, "first"))
        first = await task
        for i in range(5):                                # never read: the queue fills up
            broker.publish(seg(CALL, str(i)))
        assert broker.queues == {}                        # dropped at the first overflow
        rest = [chunk async for chunk in stream]
        return first, rest
    first, rest = asyncio.run(run())
    assert '"text": "first"' in first and len(rest) == 1  # one queued segment, then the stream ends


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_viewer_streams_a_named_call(svc, store, meeting_events):
    port = free_port()
    server = uvicorn.Server(uvicorn.Config(recipe.create_app(svc, store), port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    base = f"http://127.0.0.1:{port}"
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    try:
        with httpx.stream("GET", f"{base}/events", params={"call_id": CALL}, headers=VIEWER, timeout=5) as r:
            assert r.status_code == 200
            httpx.post(f"{base}/transcript", json=meeting_events[3], headers=PLATFORM)
            live = json.loads(next(l for l in r.iter_lines() if l.startswith("data: "))[6:])
            assert live["text"] == "First item is the launch date."
    finally:
        server.should_exit = True
