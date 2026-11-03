"""Mock order system, backed by data/orders.json. Replace with your CRM or OMS lookup."""
import json
import threading
from datetime import datetime, timezone

import config

_credit_lock = threading.Lock()   # handlers run in worker threads: read-check-append is one step


def verify(order_number: str, postal_code: str) -> dict | None:
    """Return the full order record when both factors match, else None."""
    orders = json.loads(config.ORDERS_FILE.read_text())["orders"]
    return next((o for o in orders if o["order_number"] == order_number and o["postal_code"] == postal_code), None)


def _credits() -> list[dict]:
    path = config.CREDITS_FILE
    return [json.loads(line) for line in path.read_text().splitlines() if line] if path.exists() else []


def issue_credit(order_id: str, amount: float, reason: str) -> tuple[str, bool]:
    """Credit an order once. Returns (ref, created); a repeat returns the first ref and writes nothing."""
    path = config.CREDITS_FILE
    with _credit_lock:
        rows = _credits()
        existing = next((c["ref"] for c in rows if c["order_id"] == order_id), None)
        if existing:
            return existing, False
        ref = f"CR-{len(rows) + 1:04d}"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as f:
            f.write(json.dumps({"ref": ref, "order_id": order_id, "amount": amount, "reason": reason,
                                "at": datetime.now(timezone.utc).isoformat()}) + "\n")
    return ref, True
