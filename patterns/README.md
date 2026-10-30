# Patterns

Small, reusable building blocks that recipes refer back to. Owned by builder B9.

Each pattern lives in `patterns/<name>/` and contains:

- `snippet.py`: the mechanism, about 20 lines of core logic plus imports and a tool
  definition. Longer than that means it belongs in a recipe.
- `test_snippet.py`: a pytest that proves the mechanism (see the table).
- `README.md`: half a page. The problem, the snippet, why it holds, and which recipes use it.

Recipes **copy** the code they need rather than importing from `patterns/`, so each recipe
folder stays self-contained for a clean clone.

| Pattern | Folder | Mechanism | Test | Reused by |
|---|---|---|---|---|
| Tool calling | [`tool-calling/`](tool-calling/) | The smallest SWAIG function: typed args, a handler, and a FunctionResult that both says something and sets global_data. | Handler returns the expected actions. | #1, everything |
| Address collection | [`address-collection/`](address-collection/) | A handler validates the address parts (street, city, region, postal) and returns which are missing. The step won't advance until the result is complete. | Partial address gives the missing list. | #9, #19 |
| Phone number collection and readback | [`phone-number-readback/`](phone-number-readback/) | Normalize to E.164 in the handler. Read back in digit groups and confirm before storing. | Many spoken forms normalize to one E.164 value. | #4, #14, #15 |
| Date collection | [`date-collection/`](date-collection/) | The model passes the caller's raw phrase. The handler parses it and asks back when it's ambiguous. Standard library only. | All 5 backlog examples resolve to 1970-01-01. | #1, #12, #20 |
| Grammar filling | [`grammar-filling/`](grammar-filling/) | A generalized slot map. Any subset can arrive in any order; the handler merges and reports what's missing. | Out-of-order fills, plus a missing-slot gate. | #20, #18 |
| State machine | [`state-machine/`](state-machine/) | "Don't progress to X until Y": two steps, valid_steps=[], and only a handler can change step. | The model cannot reach X before the handler allows it. | #8, #11, #12 |

Conventions: same SDK pin as the template (`signalwire-sdk==3.7.5`), same test style
(assert on `FunctionResult.to_dict()["action"]`; see `recipes/_template/tests/test_tools.py`),
no real PII, phone numbers in the 555-01xx range.

Run all pattern tests from the repo root (CI does this in the "Repo checks" job):

```bash
python3.12 -m venv .venv && .venv/bin/pip install -r scripts/requirements.txt pytest
.venv/bin/python -m pytest -q patterns/
```

`patterns/pytest.ini` sets `--import-mode=importlib` so the six `test_snippet.py` files can
share a basename; each test puts its own folder first on `sys.path` to import its `snippet`.
