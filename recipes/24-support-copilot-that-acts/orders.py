"""Mock order backend: data/orders.json and the credit ledger. Replace with your order API."""
import json
import re
import time

import config


def load_orders() -> dict:
    """The order backend. Replace with a call to your order API."""
    return json.loads(config.ORDERS_FILE.read_text())["orders"]


def resolve_order_id(raw) -> str:
    """The order ID as heard. Speech-to-text writes "A 1002" as "eight one zero zero two" or
    "81002" (live call 7639199e), so when there's no exact match, a unique order whose number
    ends the digits that were heard is used. Anything else is returned as given and not found.
    Lookups only: issue_credit takes the exact ID, so a misheard number never moves money."""
    order_id = str(raw or "").strip().upper()
    orders = load_orders()
    if order_id in orders:
        return order_id
    digits = re.sub(r"\D", "", order_id)
    hits = [k for k in orders if digits and len(re.sub(r"\D", "", k)) >= 4 and digits.endswith(re.sub(r"\D", "", k))]
    return hits[0] if len(hits) == 1 else order_id


def phone_digits(number) -> str:
    """A phone number for comparison: "sip:+15550111@host" and "+1 555 0111" -> "15550111"."""
    return re.sub(r"\D", "", str(number or "").split("@")[0])


def credited_orders() -> set:
    if not config.CREDIT_LEDGER.is_file():
        return set()
    return {json.loads(line)["order_id"] for line in config.CREDIT_LEDGER.read_text().splitlines() if line}


def record_credit(order_id: str, amount: float, reason: str, call_id: str) -> None:
    with config.CREDIT_LEDGER.open("a") as f:
        f.write(json.dumps({"order_id": order_id, "amount": amount, "reason": reason,
                            "call_id": call_id, "ts": time.time()}) + "\n")
