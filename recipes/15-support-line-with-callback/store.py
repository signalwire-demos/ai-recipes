"""Callback records in data/runtime/callbacks.json, shared by the app and the worker."""
import json
import os
from datetime import datetime, timezone

import config


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_all() -> dict:
    if not config.CALLBACKS_FILE.is_file():
        return {}
    return json.loads(config.CALLBACKS_FILE.read_text())


def _write(records: dict) -> None:
    config.CALLBACKS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = config.CALLBACKS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(records, indent=2))
    os.replace(tmp, config.CALLBACKS_FILE)  # atomic: the worker never reads half a file


def create(number: str, issue: str, summary: str, preferred_time: str) -> dict:
    records = load_all()
    rec = {"id": f"CB-{len(records) + 1:04d}", "number": number, "issue": issue,
           "summary": summary, "preferred_time": preferred_time, "status": "pending",
           "created_at": now(), "call_id": None}
    records[rec["id"]] = rec
    _write(records)
    return rec


def get(record_id: str) -> dict | None:
    return load_all().get(record_id or "")


def update(record_id: str, **fields) -> dict:
    records = load_all()
    records[record_id].update(fields)
    _write(records)
    return records[record_id]


def pending() -> list[dict]:
    return [r for r in load_all().values() if r["status"] == "pending"]
