"""Claim store, the adjuster briefing, and the SWML the adjuster's leg runs.

None of this is in the model's context. The model only ever sees the claim id.
"""
import json
import secrets
from datetime import datetime, timezone

import jsonschema_rs

import answers
import config

_validator = jsonschema_rs.validator_for(json.loads(config.CLAIM_SCHEMA_FILE.read_text()))
FIELDS = ("policy_number", "incident_date", "location", "description", "injuries")


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_all() -> dict:
    if not config.CLAIMS_FILE.is_file():
        return {}
    return json.loads(config.CLAIMS_FILE.read_text())


def save(claim: dict) -> dict:
    _validator.validate(claim)  # raises on a record that doesn't match data/claim.schema.json
    claims = load_all()
    claims[claim["claim_id"]] = claim
    config.CLAIMS_FILE.parent.mkdir(parents=True, exist_ok=True)
    config.CLAIMS_FILE.write_text(json.dumps(claims, indent=2))
    return claim


def get(claim_id: str) -> dict | None:
    return load_all().get(claim_id)


def create(fnol: dict, caller: str) -> dict:
    claim_id = f"CL-{len(load_all()) + 1:04d}"
    claim = {"claim_id": claim_id, "status": "awaiting_adjuster", "created_at": now(),
             "caller": caller or "unknown", "callback": None,
             "conference": f"claim-{claim_id}-{secrets.token_hex(4)}"}
    claim.update({k: fnol[k] for k in FIELDS})
    return save(claim)


def briefing(claim: dict) -> str:
    """What the adjuster hears before deciding. Built only from the claim record."""
    injuries = "Injuries were reported." if claim["injuries"] else "No injuries reported."
    return (f"New first notice of loss, claim {claim['claim_id']}, policy {claim['policy_number']}. "
            f"Incident on {answers.spoken_date(claim['incident_date'])} at {claim['location']}. "
            f"{claim['description']}. {injuries}")


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
