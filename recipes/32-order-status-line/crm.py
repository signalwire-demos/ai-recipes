"""Mock order system, backed by data/orders.json. Replace with your CRM or OMS lookup."""
import json
from datetime import datetime, timezone

import config


def verify(order_number: str, postal_code: str) -> dict | None:
    """Return the full order record when both factors match, else None."""
    orders = json.loads(config.ORDERS_FILE.read_text())["orders"]
    return next((o for o in orders if o["order_number"] == order_number and o["postal_code"] == postal_code), None)


def issue_credit(order_id: str, amount: float, reason: str) -> str:
    path = config.CREDITS_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    count = len(path.read_text().splitlines()) if path.exists() else 0
    ref = f"CR-{count + 1:04d}"
    with path.open("a") as f:
        f.write(json.dumps({"ref": ref, "order_id": order_id, "amount": amount, "reason": reason,
                            "at": datetime.now(timezone.utc).isoformat()}) + "\n")
    return ref
