"""The captions page and the stream it renders, replayed from the fixture call."""
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
import config
from consumer import TranscriptStore
from replay import restamp

AUTH = {"Authorization": "Basic " + base64.b64encode(b"recipe:test-pass").decode()}


@pytest.fixture
def svc(monkeypatch):
    monkeypatch.setenv("SWML_BASIC_AUTH_USER", "recipe")
    monkeypatch.setenv("SWML_BASIC_AUTH_PASSWORD", "test-pass")
    return recipe.create_service()


def test_captions_page_requires_auth_and_subscribes_to_sse(svc, tmp_path):
    client = TestClient(recipe.create_app(svc, TranscriptStore(tmp_path)))
    assert client.get("/captions").status_code == 401
    page = client.get("/captions", headers=AUTH)
    assert page.status_code == 200 and page.headers["content-type"].startswith("text/html")
    html = page.text
    assert 'new EventSource("/events"' in html and 'addEventListener("segment"' in html
    assert "__CAPTION_SETTINGS__" not in html
    settings = json.loads(html.split("const SETTINGS = ", 1)[1].split(";\n", 1)[0])
    assert settings["labels"] == config.SPEAKER_LABELS
    assert settings["slowMs"] == config.DELAY_SLOW_MS


def test_restamp_sets_a_measurable_delay(meeting_events):
    body = restamp(meeting_events[0], now=1793000100.0, delay_s=0.5)
    assert body["utterance"]["timestamp"] == 1793000099_500000
    assert meeting_events[0]["utterance"]["timestamp"] == 1793000003_100000  # original untouched
    assert restamp(meeting_events[-1], 1.0, 0.1) == meeting_events[-1]       # conversation_log


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_replayed_fixture_stream_carries_what_the_page_draws(svc, tmp_path, meeting_events, partial_events):
    """Replay the whole fixture call; the SSE stream must deliver partial and final segments,
    in arrival order, each with a server-measured delay the page shows."""
    port = free_port()
    server = uvicorn.Server(uvicorn.Config(recipe.create_app(svc, TranscriptStore(tmp_path)),
                                           port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    base = f"http://127.0.0.1:{port}"
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    try:
        with httpx.stream("GET", f"{base}/events", headers=AUTH, timeout=5) as r:  # all calls
            assert r.headers["content-type"].startswith("text/event-stream")
            bodies = partial_events + meeting_events       # conversation_log at the end: no event
            for body in bodies:
                httpx.post(f"{base}/transcript", json=restamp(body, time.time(), 0.4), headers=AUTH)
            lines = r.iter_lines()
            got = [json.loads(next(l for l in lines if l.startswith("data: "))[6:]) for _ in bodies[:-1]]
    finally:
        server.should_exit = True
    assert [(s["speaker"], s["is_final"], s["text"]) for s in got] == [
        (b["utterance"]["role"], b["utterance"].get("is_final", True), b["utterance"]["content"])
        for b in bodies[:-1]]
    assert sum(not s["is_final"] for s in got) == 3          # the page draws these grey
    assert all(350 <= s["delay_ms"] <= 2000 for s in got)  # 0.4 s simulated + local hop
