"""Mock collections ledger, backed by data/debts.json. Outcomes append to OUTCOMES_FILE."""
import json
from datetime import datetime, timezone

import config


def find(reference: str, postal_code: str) -> dict | None:
    debts = json.loads(config.DEBTS_FILE.read_text())["debts"]
    ref = reference.replace(" ", "").replace("-", "").upper()
    return next((d for d in debts if d["reference"] == ref and d["postal_code"] == postal_code), None)


def record(debt_id: str, outcome: str, **details) -> None:
    config.OUTCOMES_FILE.parent.mkdir(parents=True, exist_ok=True)
    row = {"debt_id": debt_id, "outcome": outcome, "at": datetime.now(timezone.utc).isoformat(), **details}
    with config.OUTCOMES_FILE.open("a") as f:
        f.write(json.dumps(row) + "\n")
