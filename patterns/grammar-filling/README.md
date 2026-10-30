# Grammar filling

**Problem.** "Large deep dish, for pickup" fills three fields in one breath; another caller
gives one per turn, in a different order. An ordered gather (ask Q1, then Q2) fights the
first caller. A free-form prompt can't tell you when it's done.

**Snippet** ([snippet.py](snippet.py)):

```python
SLOTS = {"fulfillment": one_of("delivery", "pickup"),
         "size": one_of("small", "medium", "large"),
         "crust": one_of("thin", "hand tossed", "deep dish")}

def fill(saved, incoming, slots=SLOTS):
    merged, problems = dict(saved), {}
    for name, raw in incoming.items():
        if name in slots and raw not in (None, ""):
            value, problem = slots[name](" ".join(str(raw).lower().split()))
            ...  # valid -> merged[name], invalid -> problems[name]
    return merged, [s for s in slots if s not in merged], problems

def record_slots(args, raw_data, key="order", next_step="confirm", slots=SLOTS):
    merged, missing, problems = fill((raw_data.get("global_data") or {}).get(key, {}), args, slots)
    result = FunctionResult().update_global_data({key: merged})
    if missing:
        return result.set_response(f"Still missing: {...}. Ask for those only.")
    return result.set_response(f"All set: {merged}. Read it back.").swml_change_step(next_step)
```

**Why it holds.** Every slot is an optional tool parameter, so any subset can arrive in any
order. The merge lives in `global_data`, not in the model's memory. Each slot has a validator
(`one_of`, or any `raw -> (value, question)` function such as the date pattern's
`parse_date`), and a rejected value keeps the old one and is reported with its question. The
`swml_change_step` is only in the "nothing missing" branch: that's the gate. Swap `SLOTS`, and
bind `key`, `next_step` and `slots` with `functools.partial` for your own form.

**Test.** `pytest patterns/grammar-filling`: out-of-order fills merge across turns, and a
missing slot blocks the step change.

**Used by.** #20, #18.
