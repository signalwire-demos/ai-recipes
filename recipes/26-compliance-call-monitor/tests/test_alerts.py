"""Alert delivery: SMS through the REST API (asserted, live SMS pending 10DLC), webhook, log."""
import json

import httpx

from alerts import AlertSender
from rules import Alert

ALERT = Alert("c0ffee00-0000-4000-8000-000000000263", "recording-disclosure", 1793000030.0, 1793000033.0)


class FakeMessages:
    def __init__(self):
        self.sent = []

    def create(self, **kwargs):
        self.sent.append(kwargs)
        return {"id": "msg-1"}


class FakeClient:
    def __init__(self):
        self.messages = FakeMessages()


def test_sms_alert_carries_call_id_and_deadline(tmp_path):
    client = FakeClient()
    sender = AlertSender("+15550100199", "+15550100100", tmp_path / "a.jsonl", sms_client_factory=lambda: client)
    assert sender.send(ALERT) == "sms"
    [msg] = client.messages.sent
    assert msg["to"] == "+15550100199" and msg["from_"] == "+15550100100"
    assert ALERT.call_id in msg["body"] and "2026-10-26 07:33:50 UTC" in msg["body"]
    logged = json.loads((tmp_path / "a.jsonl").read_text())
    assert logged["channel"] == "sms" and logged["rule_id"] == "recording-disclosure"


def test_webhook_alert_is_slack_compatible(tmp_path):
    seen = []
    transport = httpx.MockTransport(lambda req: seen.append(json.loads(req.content)) or httpx.Response(200))
    sender = AlertSender("https://hooks.example.com/T000", "", tmp_path / "a.jsonl", http=httpx.Client(transport=transport))
    assert sender.send(ALERT) == "webhook"
    assert seen[0]["text"].startswith("Compliance alert") and seen[0]["call_id"] == ALERT.call_id


def test_empty_target_logs_only_and_failures_never_raise(tmp_path):
    assert AlertSender("", "", tmp_path / "a.jsonl").send(ALERT) == "log"

    def boom():
        raise RuntimeError("no credentials")
    assert AlertSender("+15550100199", "", tmp_path / "a.jsonl", sms_client_factory=boom).send(ALERT) == "sms"
    assert len((tmp_path / "a.jsonl").read_text().splitlines()) == 2
