"""Deliver a compliance alert to the supervisor: SMS, a webhook (Slack-compatible), or a log.

ALERT_TARGET picks the path:
  +15550100123            SMS from ALERT_FROM via the SignalWire REST API (messages.create)
  https://hooks.slack...  POST {"text": ..., "call_id", "rule_id", "deadline", "detected_at"}
  (empty)                 log only
Every alert is also appended to data/runtime/alerts.jsonl.
"""
import json
import logging
from dataclasses import asdict
from pathlib import Path

import httpx

from rules import Alert

log = logging.getLogger("compliance")


def make_sms_client():
    from signalwire.rest import RestClient   # reads SIGNALWIRE_PROJECT_ID / _API_TOKEN / _SPACE
    return RestClient()


class AlertSender:
    def __init__(self, target: str, from_number: str, log_file: Path,
                 sms_client_factory=make_sms_client, http: httpx.Client | None = None):
        self.target, self.from_number, self.log_file = target.strip(), from_number, Path(log_file)
        self.sms_client_factory, self.http = sms_client_factory, http or httpx.Client(timeout=10)

    def channel(self) -> str:
        if self.target.startswith("+"):
            return "sms"
        return "webhook" if self.target.startswith(("http://", "https://")) else "log"

    def send(self, alert: Alert) -> str:
        """Send one alert. Returns the channel used. Delivery errors are logged, not raised."""
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        with self.log_file.open("a") as fh:
            fh.write(json.dumps({**asdict(alert), "channel": self.channel()}) + "\n")
        log.warning(alert.message())
        try:
            if self.channel() == "sms":
                self.sms_client_factory().messages.create(
                    to=self.target, from_=self.from_number, body=alert.message())
            elif self.channel() == "webhook":
                self.http.post(self.target, json={"text": alert.message(), **asdict(alert)}).raise_for_status()
        except Exception as exc:  # an alert path must never take the consumer down
            log.error("alert delivery failed (%s): %s", self.channel(), exc)
        return self.channel()
