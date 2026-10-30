"""End to end in the app: the SWML fetch starts the clock, webhooks feed the rules,
the ticker sends exactly one alert, and the status route is behind auth."""
import base64
import time

import pytest
from fastapi.testclient import TestClient

import app as recipe
import config
from consumer import TranscriptStore
from rules import ComplianceMonitor

AUTH = {"Authorization": "Basic " + base64.b64encode(b"recipe:test-pass").decode()}
T0 = 1793000000.0


class CollectingSender:
    def __init__(self):
        self.sent = []

    def send(self, alert):
        self.sent.append(alert)
        return "log"


@pytest.fixture
def svc(monkeypatch):
    monkeypatch.setenv("SWML_BASIC_AUTH_USER", "recipe")
    monkeypatch.setenv("SWML_BASIC_AUTH_PASSWORD", "test-pass")
    return recipe.create_service(ComplianceMonitor(config.RULES))


def test_swml_fetch_starts_the_clock(svc, tmp_path):
    client = TestClient(recipe.create_app(svc, TranscriptStore(tmp_path), CollectingSender()))
    before = time.time()
    assert client.post("/", json={"call": {"call_id": "call-fetch"}}, headers=AUTH).status_code == 200
    assert before <= svc.monitor.starts["call-fetch"] <= time.time()


def test_webhooks_feed_the_rules_and_status_route(svc, tmp_path, load_fixture):
    client = TestClient(recipe.create_app(svc, TranscriptStore(tmp_path), CollectingSender()))
    events = load_fixture("compliance-late")
    call_id = events[0]["call_info"]["call_id"]
    svc.monitor.start_call(call_id, T0)
    for body in events:
        assert client.post("/transcript", json=body, headers=AUTH).status_code == 200
    assert [a.rule_id for a in svc.monitor.check_deadlines(T0 + 120)] == ["recording-disclosure"]
    assert client.get(f"/calls/{call_id}/compliance").status_code == 401
    rules = client.get(f"/calls/{call_id}/compliance", headers=AUTH).json()["rules"]
    assert rules == {"recording-disclosure": "late", "agent-identification": "passed"}


def test_ticker_alerts_once_on_silence(svc, tmp_path, monkeypatch):
    """Nobody says anything: the deadline still passes and one alert per rule goes out."""
    monkeypatch.setattr(config, "DEADLINE_CHECK_SECONDS", 0.05)
    sender = CollectingSender()
    svc.monitor.start_call("silent-call", time.time() - 120)
    with TestClient(recipe.create_app(svc, TranscriptStore(tmp_path), sender)):  # runs the lifespan
        for _ in range(40):
            if len(sender.sent) >= 2:
                break
            time.sleep(0.05)
        time.sleep(0.2)  # a few more ticks: no duplicates
    assert sorted(a.rule_id for a in sender.sent) == ["agent-identification", "recording-disclosure"]
