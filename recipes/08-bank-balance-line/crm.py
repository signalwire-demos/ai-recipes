"""Mock core banking, backed by data/accounts.json. Replace verify() with your identity provider."""
import json
import threading
from datetime import datetime, timezone

import config

_dispute_lock = threading.Lock()  # handlers run in a thread pool: count and append as one step


def _accounts() -> list[dict]:
    return json.loads(config.ACCOUNTS_FILE.read_text())["accounts"]


def verify(account_number: str, date_of_birth: str) -> dict | None:
    """Return the account when both factors match, else None."""
    for acct in _accounts():
        if acct["account_number"] == account_number and acct["date_of_birth"] == date_of_birth:
            return acct
    return None


def get(account_id: str) -> dict | None:
    return next((a for a in _accounts() if a["id"] == account_id), None)


def open_dispute(account_id: str, transaction_id: str, reason: str) -> str:
    config.DISPUTES_FILE.parent.mkdir(parents=True, exist_ok=True)
    path = config.DISPUTES_FILE
    with _dispute_lock:
        count = len(path.read_text().splitlines()) if path.exists() else 0
        ref = f"D-{count + 1:04d}"
        with path.open("a") as f:
            f.write(json.dumps({"ref": ref, "account_id": account_id, "transaction_id": transaction_id,
                                "reason": reason, "opened": datetime.now(timezone.utc).isoformat()}) + "\n")
    return ref
