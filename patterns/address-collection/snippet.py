"""Address collection: the handler, not the model, decides when an address is complete.

Each call merges whatever parts the caller gave into global_data["address"] and
answers with the parts still missing. Only a complete, valid address moves the
call on, so a step with valid_steps=[] cannot be left with half an address.
"""
import re

from signalwire import FunctionResult

PARTS = ("street", "city", "region", "postal")
CHECKS = {"street": r"\d+\w* .+", "city": r"[a-z .'-]{2,}", "region": r"[a-z]{2}", "postal": r"\d{5}(-\d{4})?"}
NEXT_STEP = "confirm"


def check_address(parts: dict) -> tuple[dict, list[str]]:
    """Return (the valid parts, the names of the missing or invalid ones)."""
    clean = {k: " ".join(str(parts.get(k) or "").split()) for k in PARTS}
    clean["region"] = clean["region"].upper()
    valid = {k: v for k, v in clean.items() if re.fullmatch(CHECKS[k], v, re.I)}
    return valid, [k for k in PARTS if k not in valid]


def record_address(args, raw_data):
    saved = (raw_data.get("global_data") or {}).get("address", {})
    address, missing = check_address({**saved, **{k: v for k, v in args.items() if v}})
    result = FunctionResult().update_global_data({"address": address})
    if missing:
        return result.set_response(f"Still needed: {', '.join(missing)}. Ask only for those.")
    line = f"{address['street']}, {address['city']}, {address['region']} {address['postal']}"
    return result.set_response(f"Address complete: {line}.").swml_change_step(NEXT_STEP)


# agent.define_tool(**TOOL). Every part is optional so the caller can give them in any order.
TOOL = dict(name="record_address", handler=record_address, required=[],
            description="Record any parts of the caller's US street address that they have said.",
            parameters={k: {"type": "string", "description": d} for k, d in {
                "street": "Number and street, e.g. 123 Main St", "city": "City",
                "region": "Two-letter state, e.g. TX", "postal": "5-digit ZIP"}.items()})
