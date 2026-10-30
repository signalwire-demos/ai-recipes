"""End to end in the app: transcript webhooks start the clock and feed the rules,
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
    return recipe.create_service()


@pytest.fixture
def monitor():
    return ComplianceMonitor(config.RULES)


def test_webhooks_feed_the_rules_and_status_route(svc, monitor, tmp_path, load_fixture):
    client = TestClient(recipe.create_app(svc, TranscriptStore(tmp_path), CollectingSender(), monitor))
    events = load_fixture("compliance-late")
    call_id = events[0]["call_info"]["call_id"]
    for body in events:
        assert client.post("/transcript", json=body, headers=AUTH).status_code == 200
    assert monitor.starts[call_id] == T0                  # channel_data.call_answer_date
    assert [a.rule_id for a in monitor.check_deadlines(T0 + 120)] == ["recording-disclosure"]
    assert client.get(f"/calls/{call_id}/compliance").status_code == 401
    rules = client.get(f"/calls/{call_id}/compliance", headers=AUTH).json()["rules"]
    assert rules == {"recording-disclosure": "late", "agent-identification": "passed"}


def test_ticker_alerts_once_on_silence(svc, monitor, tmp_path, monkeypatch):
    """Nobody says anything: the deadline still passes and one alert per rule goes out."""
    monkeypatch.setattr(config, "DEADLINE_CHECK_SECONDS", 0.05)
    sender = CollectingSender()
    monitor.start_call("silent-call", time.time() - 120)
    with TestClient(recipe.create_app(svc, TranscriptStore(tmp_path), sender, monitor)):  # runs the lifespan
        for _ in range(40):
            if len(sender.sent) >= 2:
                break
            time.sleep(0.05)
        time.sleep(0.2)  # a few more ticks: no duplicates
    assert sorted(a.rule_id for a in sender.sent) == ["agent-identification", "recording-disclosure"]
