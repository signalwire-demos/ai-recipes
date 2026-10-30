# Phone number collection and readback

**Problem.** Callers say numbers many ways ("two one two, triple five, oh one four two",
"(212) 555-0142", "plus one..."). TTS reads "5550142" as "five million...". And a number
stored without a readback is a wrong number you find out about later.

**Snippet** ([snippet.py](snippet.py)):

```python
def to_e164(spoken):
    digits, times = "", 1
    for tok in re.findall(r"[a-z]+|\d", spoken.lower()):
        if tok in REPEAT:
            times = REPEAT[tok]
        elif tok.isdigit() or tok in WORDS:
            digits, times = digits + WORDS.get(tok, tok) * times, 1
    digits = digits[1:] if len(digits) == 11 and digits[0] == "1" else digits
    return f"+1{digits}" if len(digits) == 10 and digits[0] not in "01" else None

def record_phone(args, raw_data):
    e164 = to_e164(str(args.get("number", "")))
    ...
    if args.get("confirmed") and (raw_data.get("global_data") or {}).get("phone_pending") == e164:
        return FunctionResult("Number saved.").update_global_data({"phone": e164, "phone_pending": None})
    return FunctionResult(f"Read it back exactly as: {readback(e164)}. ...") \
        .update_global_data({"phone_pending": e164})
```

**Why it holds.** The model passes the caller's words; the handler, not the model, does the
normalizing, so filler words, "oh", "double" and "triple" all land on one E.164 value.
`readback()` returns `2 1 2, 5 5 5, 0 1 4 2`, which TTS reads digit by digit with pauses. The
number is only saved when `confirmed=true` arrives for the number that was already read back
(`phone_pending`), so passing `confirmed=true` on the first call just triggers the readback.
NANP (+1) only. Extend `to_e164` for other numbering plans.

**Test.** `pytest patterns/phone-number-readback`: nine spoken forms normalize to
`+12125550142`, and the number isn't stored without a readback first.

**Used by.** #4, #14, #15.
