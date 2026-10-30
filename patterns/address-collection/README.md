# Address collection

**Problem.** Callers give an address in pieces, out of order, and often leave a piece out.
A model that decides on its own that "that's enough address" ships half an address.

**Snippet** ([snippet.py](snippet.py)):

```python
def check_address(parts):
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
    ...
    return result.set_response(f"Address complete: {line}.").swml_change_step(NEXT_STEP)
```

Register it with `agent.define_tool(**TOOL)` in a step that has `set_valid_steps([])`.

**Why it holds.** Every part is optional in the tool schema, so the model can call it as soon
as it hears anything. The handler merges with what's already in `global_data`, validates each
part (`CHECKS`: a house number, a two-letter state, a 5-digit ZIP), and counts an invalid part
as missing. The step change to `confirm` is only in the complete branch, and the step has no
`next_step` tool, so the model can't move on with a partial address.

**Test.** `pytest patterns/address-collection`: a partial address gives the missing list, and
the step changes only once a later call completes it.

**Used by.** #9, #19.
