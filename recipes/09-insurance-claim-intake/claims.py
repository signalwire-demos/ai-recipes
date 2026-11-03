"""Claim store, the adjuster briefing, and the SWML the adjuster's leg runs.

None of this is in the model's context. The model only ever sees the claim id.
"""
import json
import os
import secrets
import threading
from datetime import datetime, timezone

import jsonschema_rs

import answers
import config

_validator = jsonschema_rs.validator_for(json.loads(config.CLAIM_SCHEMA_FILE.read_text()))
FIELDS = ("policy_number", "incident_date", "location", "description", "injuries")
_lock = threading.Lock()  # handlers run in a thread pool: one read-modify-write at a time


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_all() -> dict:
    if not config.CLAIMS_FILE.is_file():
        return {}
    return json.loads(config.CLAIMS_FILE.read_text())


def _put(claim: dict) -> dict:
    """Write one record. Caller holds _lock."""
    _validator.validate(claim)  # raises on a record that doesn't match data/claim.schema.json
    claims = load_all()
    claims[claim["claim_id"]] = claim
    config.CLAIMS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = config.CLAIMS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(claims, indent=2))
    os.replace(tmp, config.CLAIMS_FILE)  # readers never see half a file
    return claim


def save(claim: dict) -> dict:
    with _lock:
        return _put(claim)


def get(claim_id: str) -> dict | None:
    return load_all().get(claim_id)


def create(fnol: dict, caller: str) -> dict:
    with _lock:  # id allocation and write in one step, so two filings never share an id
        ids = [int(k.split("-")[1]) for k in load_all() if k.startswith("CL-") and k[3:].isdigit()]
        claim_id = f"CL-{max(ids, default=0) + 1:04d}"
        claim = {"claim_id": claim_id, "status": "awaiting_adjuster", "created_at": now(),
                 "caller": caller or "unknown", "callback": None,
                 "conference": f"claim-{claim_id}-{secrets.token_hex(4)}"}
        claim.update({k: fnol[k] for k in FIELDS})
        return _put(claim)


def _quoted(text: str) -> str:
    """Caller free text for the briefing: one line, capped, so it can't pose as the system."""
    text = " ".join(str(text).split()).rstrip(".")
    cap = config.BRIEFING_MAX_CHARS
    return text if len(text) <= cap else text[:cap].rsplit(" ", 1)[0] + ", and more"


def briefing(claim: dict) -> str:
    """What the adjuster hears before deciding. Built only from the claim record. The location
    and description are the caller's own words, so they are labeled as such and capped."""
    injuries = "Injuries were reported." if claim["injuries"] else "No injuries reported."
    return (f"New first notice of loss, claim {claim['claim_id']}, policy {claim['policy_number']}. "
            f"Incident on {answers.spoken_date(claim['incident_date'])}. {injuries} "
            f"In the caller's words, location: {_quoted(claim['location'])}. "
            f"What happened: {_quoted(claim['description'])}. End of the caller's words.")


def adjuster_swml(claim: dict, caller_call_id: str) -> dict:
    """The dest_swml for rpc_dial: brief the adjuster, then press ACCEPT_DIGIT to take the call.

    Accept: release the caller's hold (they land in step `connected`) and wait in the claim's
    conference. Anything else: hang up; the caller's hold times out into step `callback`.
    """
    accept = [
        {"execute_rpc": {"method": "ai_unhold", "call_id": caller_call_id, "params": {}}},
        {"join_conference": {"name": claim["conference"], "end_on_exit": True}},
    ]
    decline = [{"play": {"url": "say:Understood. The caller will get a callback."}}, {"hangup": {}}]
    return {"version": "1.0.0", "sections": {"main": [
        {"play": {"url": f"say:{briefing(claim)}"}},
        {"prompt": {"play": f"say:Press {config.ACCEPT_DIGIT} to take this caller now. "
                            "Press any other key to decline.",
                    "max_digits": 1, "initial_timeout": 10}},
        {"switch": {"variable": "prompt_value", "case": {config.ACCEPT_DIGIT: accept},
                    "default": decline}},
    ]}}
