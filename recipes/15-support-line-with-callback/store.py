"""Callback records in data/runtime/callbacks.json, shared by the app and the worker."""
import fcntl
import json
import os
import re
from contextlib import contextmanager
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


class Refused(Exception):
    """create() won't queue this callback. str(exc) is the reason: not_dialable, duplicate, full."""


def dialable(number: str) -> bool:
    """E.164 under an allowed prefix. NANP numbers must be well formed and not premium/Caribbean.
    Anonymous, SIP URIs and short codes fail the E.164 match."""
    number = str(number or "")
    if not re.fullmatch(r"\+[1-9]\d{7,14}", number):
        return False
    if not any(number.startswith(p) for p in config.CALLBACK_ALLOWED_PREFIXES):
        return False
    if number.startswith("+1"):
        nanp = re.fullmatch(r"\+1([2-9]\d{2})([2-9]\d{2})\d{4}", number)
        return bool(nanp) and nanp[1] not in config.BLOCKED_NPAS and nanp[2] != "976"
    return True


@contextmanager
def _locked():
    """One writer at a time, across threads and across the app and worker processes."""
    config.CALLBACKS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(config.CALLBACKS_FILE.with_suffix(".lock"), "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def create(number: str, issue: str, summary: str, preferred_time: str) -> dict:
    if not dialable(number):
        raise Refused("not_dialable")
    with _locked():
        records = load_all()
        waiting = [r for r in records.values() if r["status"] == "pending"]
        if any(r["number"] == number for r in waiting):
            raise Refused("duplicate")
        if len(waiting) >= config.MAX_PENDING_CALLBACKS:
            raise Refused("full")
        n = max((int(k[3:]) for k in records if k[3:].isdigit()), default=0) + 1
        rec = {"id": f"CB-{n:04d}", "number": number, "issue": issue,
               "summary": summary, "preferred_time": preferred_time, "status": "pending",
               "created_at": now(), "call_id": None}
        records[rec["id"]] = rec
        _write(records)
    return rec


def get(record_id: str) -> dict | None:
    return load_all().get(record_id or "")


def update(record_id: str, **fields) -> dict:
    with _locked():
        records = load_all()
        records[record_id].update(fields)
        _write(records)
    return records[record_id]


def pending() -> list[dict]:
    return [r for r in load_all().values() if r["status"] == "pending"]
