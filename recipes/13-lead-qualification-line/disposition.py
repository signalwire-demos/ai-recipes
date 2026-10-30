"""Turn handler-written global_data into a lead disposition, and send it to the CRM.

Nothing here sees the transcript or the model's summary. The only input is the
typed values the record_* handlers wrote into global_data.
"""
import json
import time
import urllib.request

import config


def score(lead: dict) -> int:
    return sum(1 for key, rule in config.SCORE_RULES.items() if key in lead and rule(lead[key]))


def tier(points: int) -> str:
    return next(name for minimum, name in config.TIERS if points >= minimum)


def build_disposition(global_data: dict, call_id: str | None = None) -> dict:
    lead = {k: global_data[k] for k in config.FIELDS if k in global_data}
    points = score(lead)
    return {
        "call_id": call_id,
        "recorded_at": int(time.time()),
        **{k: lead.get(k) for k in config.FIELDS},
        "missing": [k for k in config.FIELDS if k not in lead],
        "score": points,
        "tier": tier(points),
    }


def write_file(disposition: dict) -> None:
    config.LEADS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with config.LEADS_FILE.open("a") as f:
        f.write(json.dumps(disposition) + "\n")


def write_hubspot(disposition: dict) -> None:
    """Create a HubSpot contact. lead_* are custom contact properties (see README)."""
    properties = {
        "lifecyclestage": "lead",
        "lead_tier": disposition["tier"],
        "lead_score": disposition["score"],
        "lead_budget_usd": disposition["budget_usd"],
        "lead_timeline_months": disposition["timeline_months"],
        "lead_decision_maker": disposition["is_decision_maker"],
        "lead_need": disposition["need"],
        "lead_call_id": disposition["call_id"],
    }
    body = {"properties": {k: v for k, v in properties.items() if v is not None}}
    req = urllib.request.Request(
        config.HUBSPOT_URL, data=json.dumps(body).encode(), method="POST",
        headers={"Authorization": f"Bearer {config.HUBSPOT_TOKEN}",
                 "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        resp.read()


SINKS = {"file": write_file, "hubspot": write_hubspot}


def send(disposition: dict) -> None:
    SINKS[config.CRM_SINK](disposition)
