"""Rule engine: required phrases must be said within N seconds of the call starting.

Deterministic on purpose: plain phrase matching on FINAL segments, no model judging the
transcript. Each (call, rule) settles exactly once: `passed` when a phrase is heard in time,
`missed` when the deadline passes without one. A late disclosure does not undo a miss.

Time: a phrase counts by the time it was SPOKEN (the segment's ts), not when its webhook
arrived. Deadlines are checked by a ticker (app.py) that waits `grace` seconds past each
deadline, so a final result still in flight can settle the rule before a miss is declared.
"""
import re
import threading
from dataclasses import dataclass
from datetime import datetime, timezone

from adapter import Segment


def normalize(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9' ]+", " ", text.lower()).split())


@dataclass
class Alert:
    call_id: str
    rule_id: str
    deadline: float      # epoch seconds
    detected_at: float   # epoch seconds

    def message(self) -> str:
        when = datetime.fromtimestamp(self.deadline, timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        return (f"Compliance alert: call {self.call_id} missed '{self.rule_id}'. "
                f"Required phrase not heard by {when}.")


class ComplianceMonitor:
    def __init__(self, rules: list[dict], grace: float = 0.0):
        self.grace = grace
        self.rules = [{**r, "phrases": [normalize(p) for p in r["phrases"]]} for r in rules]
        self.starts: dict[str, float] = {}
        self.settled: dict[tuple[str, str], str] = {}   # (call_id, rule_id) -> passed | missed
        self.late: set[tuple[str, str]] = set()
        self.lock = threading.Lock()

    def start_call(self, call_id: str, started_at: float) -> None:
        with self.lock:
            self.starts.setdefault(call_id, started_at)

    def observe(self, seg: Segment) -> None:
        """Feed one segment. Only final segments said before the deadline can pass a rule."""
        self.start_call(seg.call_id, seg.ts)  # fallback clock when the SWML fetch wasn't seen
        if not seg.is_final:
            return
        text = normalize(seg.text)
        with self.lock:
            for rule in self.rules:
                key = (seg.call_id, rule["id"])
                if rule.get("speaker") and rule["speaker"] != seg.speaker:
                    continue
                if not any(p in text for p in rule["phrases"]):
                    continue
                on_time = seg.ts <= self.starts[seg.call_id] + rule["within_seconds"]
                if key not in self.settled and on_time:
                    self.settled[key] = "passed"
                elif not on_time and self.settled.get(key) != "passed":
                    self.late.add(key)  # recorded for the report, never a second alert

    def check_deadlines(self, now: float) -> list[Alert]:
        """Settle every rule whose deadline (plus grace) has passed. Returns new alerts."""
        alerts = []
        with self.lock:
            for call_id, started in self.starts.items():
                for rule in self.rules:
                    key, deadline = (call_id, rule["id"]), started + rule["within_seconds"]
                    if key not in self.settled and now > deadline + self.grace:
                        self.settled[key] = "missed"
                        alerts.append(Alert(call_id, rule["id"], deadline, now))
        return alerts

    def status(self, call_id: str) -> dict:
        with self.lock:
            return {r["id"]: ("late" if (call_id, r["id"]) in self.late
                              else self.settled.get((call_id, r["id"]), "pending")) for r in self.rules}
