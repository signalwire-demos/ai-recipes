"""Phone number collection and readback.

The handler normalizes whatever the caller said to E.164, then makes the model
read it back in digit groups. The number is only stored on a second call with
confirmed=true for the same number, so the model cannot skip the readback.
North American (+1) numbers only; extend to_e164 for other plans.
"""
import re

from signalwire import FunctionResult

WORDS = {w: str(i) for i, w in enumerate("zero one two three four five six seven eight nine".split())} | {"oh": "0"}
REPEAT = {"double": 2, "triple": 3}


def to_e164(spoken: str) -> str | None:
    """'two one two, five five five, oh one four two' -> '+12125550142'."""
    digits, times = "", 1
    for tok in re.findall(r"[a-z]+|\d", spoken.lower()):
        if tok in REPEAT:
            times = REPEAT[tok]
        elif tok.isdigit() or tok in WORDS:
            digits, times = digits + WORDS.get(tok, tok) * times, 1
    digits = digits[1:] if len(digits) == 11 and digits[0] == "1" else digits
    return f"+1{digits}" if len(digits) == 10 and digits[0] not in "01" else None


def readback(e164: str) -> str:
    """'+12125550142' -> '2 1 2, 5 5 5, 0 1 4 2' (TTS reads each digit, pausing at the commas)."""
    d = e164[2:]
    return ", ".join(" ".join(g) for g in (d[:3], d[3:6], d[6:]))


def record_phone(args, raw_data):
    e164 = to_e164(str(args.get("number", "")))
    if e164 is None:
        return FunctionResult("That isn't a full 10-digit number. Ask for it again, digit by digit.")
    if args.get("confirmed") and (raw_data.get("global_data") or {}).get("phone_pending") == e164:
        return FunctionResult("Number saved.").update_global_data({"phone": e164, "phone_pending": None})
    return (FunctionResult(f"Read it back exactly as: {readback(e164)}. If the caller says yes, "
                           "call record_phone again with the same number and confirmed true.")
            .update_global_data({"phone_pending": e164}))


TOOL = dict(name="record_phone", handler=record_phone, required=["number"],
            description="Record the caller's phone number. Call once to get a readback, then again to confirm.",
            parameters={"number": {"type": "string", "description": "The digits or words the caller said"},
                        "confirmed": {"type": "boolean", "description": "True only after the caller confirmed the readback"}})
