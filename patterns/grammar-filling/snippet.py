"""Grammar filling: a slot map the caller can fill in any order, in any number of turns.

SLOTS maps each slot to a validator: raw value in, (clean value, None) or
(None, a question) out. fill() merges a turn's values into what's already
saved. The handler stores the merge in global_data, says what is still
missing, and changes step only when nothing is.
"""
from signalwire import FunctionResult


def one_of(*choices):
    return lambda raw: (raw, None) if raw in choices else (None, f"choose {' or '.join(choices)}")


SLOTS = {"fulfillment": one_of("delivery", "pickup"),            # example: a pizza order
         "size": one_of("small", "medium", "large"),
         "crust": one_of("thin", "hand tossed", "deep dish")}


def fill(saved: dict, incoming: dict, slots=SLOTS) -> tuple[dict, list[str], dict]:
    """Return (merged slots, names still missing, {slot: question} for values that failed)."""
    merged, problems = dict(saved), {}
    for name, raw in incoming.items():
        if name in slots and raw not in (None, ""):
            value, problem = slots[name](" ".join(str(raw).lower().split()))
            if problem is None:
                merged[name] = value
            else:
                problems[name] = problem
    return merged, [s for s in slots if s not in merged], problems


def record_slots(args, raw_data, key="order", next_step="confirm", slots=SLOTS):
    merged, missing, problems = fill((raw_data.get("global_data") or {}).get(key, {}), args, slots)
    result = FunctionResult().update_global_data({key: merged})
    if missing:
        asks = [f"{s} ({problems[s]})" if s in problems else s for s in missing]
        return result.set_response(f"Still missing: {', '.join(asks)}. Ask for those only.")
    return result.set_response(f"All set: {merged}. Read it back.").swml_change_step(next_step)


TOOL = dict(name="record_slots", handler=record_slots, required=[],
            description="Record any order details the caller just gave, in any order. Omit what they didn't say.",
            parameters={s: {"type": "string", "description": s} for s in SLOTS})
