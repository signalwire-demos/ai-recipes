"""A small, short-lived handoff store: token -> {summary, trip, call_id, created}.

The concierge's handler writes a record and puts only the opaque token in the transfer URL.
The booking agent's dynamic config callback reads it back. No transcript is ever stored.
Swap this JSON file for Redis (SET with EX) or your database in production.
"""
import json
import secrets
import threading
import time

import config

_lock = threading.Lock()


def _read() -> dict:
    path = config.HANDOFF_FILE
    return json.loads(path.read_text()) if path.exists() else {}


def _write(records: dict) -> None:
    config.HANDOFF_FILE.parent.mkdir(parents=True, exist_ok=True)
    config.HANDOFF_FILE.write_text(json.dumps(records, indent=1))


def _fresh(record: dict) -> bool:
    return time.time() - record.get("created", 0) < config.HANDOFF_TTL_SECS


def save(record: dict) -> str:
    token = secrets.token_urlsafe(12)
    with _lock:
        records = {k: v for k, v in _read().items() if _fresh(v)}   # purge expired
        records[token] = {**record, "created": time.time()}
        _write(records)
    return token


def load(token: str | None) -> dict | None:
    if not token:
        return None
    with _lock:
        record = _read().get(token)
    return record if record and _fresh(record) else None


def update(token: str, **fields) -> None:
    with _lock:
        records = _read()
        if token in records:
            records[token].update(fields)
            _write(records)
