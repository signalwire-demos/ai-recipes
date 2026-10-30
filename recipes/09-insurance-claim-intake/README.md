# AI Insurance Claim Intake

A caller reports an accident, and an adjuster hears a briefing and accepts before the call is bridged.

## What it does

The agent takes a first notice of loss: policy number, date, location, what happened, and
whether anyone was hurt (the date and the injuries answer are read back to confirm). Code
checks every answer: a policy number must look like `POL-0101`, the date must be a real date
in the past year, the location must be a place, and injuries must be a yes or a no. A wrong
answer is rejected with a re-ask. The caller's phone number comes from the call's caller ID,
never from a question. It files a claim record, puts the caller on hold and phones an adjuster. The adjuster hears a
spoken summary of the claim and presses 1 to take the call, which joins the caller and the
adjuster. If nobody accepts before the hold times out, the agent asks when to call back,
stores that callback promise on the claim and says goodbye.

## What it demonstrates

A screened handoff where the human is briefed before the bridge completes, and the model
never drives the handoff. It also shows that a gathered answer is still caller input. The
gather (`isolated=True`, so a question can't be answered from an earlier one) unlocks one
`check_*` tool per question, and `answers.py` decides whether the caller's words are a valid
policy number, date, place or yes/no. gather_submit has no code hook in 3.7.5, so
`submit_claim` runs the same checks on the whole record before it files anything. If one
fails, it stores which field failed (`global_data.fix_field`), returns the re-ask, and the
model passes the caller's next words back as `submit_claim(answer=...)`. Code applies that
correction to the flagged field only, so the gather never restarts. The `submit` step exposes one tool, `submit_claim`. Its handler
writes the claim record, then returns `hold(step="connected", timeout_step="callback")` and
`rpc_dial(to_number, from_number, dest_swml)`. The `dest_swml` is this app's `/brief` route,
which turns the claim record into the SWML the adjuster's leg runs: speak the briefing, wait
for a keypress, and on `1` run `execute_rpc ai_unhold` on the caller and join the claim's
conference. So the platform, not the model, decides which step the caller lands in. The
`join_adjuster` tool only exists in `connected`, and `promise_callback` only exists in `callback`.
The adjuster number, the conference name and the claim record never enter the model's context.
It sees only `global_data.claim_id`.

```mermaid
stateDiagram-v2
    [*] --> intake
    intake --> submit: gather complete (completion_action)
    submit --> on_hold: submit_claim handler, hold + rpc_dial(adjuster, /brief)
    on_hold --> connected: adjuster presses 1, their SWML runs ai_unhold
    on_hold --> callback: hold timeout (no answer or declined)
    connected --> [*]: join_adjuster handler, join_conference
    callback --> [*]: promise_callback handler, callback stored, hangup
    note right of intake: tools = [] plus one check_* tool per question
    note right of submit: tools = [submit_claim], valid_steps = []
    note right of connected: tools = [join_adjuster], valid_steps = []
    note right of callback: tools = [promise_callback], valid_steps = []
```

| Primitive | Where |
|---|---|
| `set_gather_info(isolated=True)` / `add_gather_question(confirm=True, functions=[...])` | `app.py`, step `intake` |
| Answer checks (policy format, past date, place, yes/no) | `answers.py`; per-question `check_*` tools and `submit_claim` in `app.py` |
| `set_prompt_llm_params(model=...)` | `app.py`; model name in `config.py` |
| `set_functions`, `set_valid_steps([])` | `app.py`, every step |
| `hold(step=, timeout_step=)` + `rpc_dial` | `app.py`, `submit_claim` handler |
| dest_swml: briefing, `prompt`, `switch`, `execute_rpc ai_unhold`, `join_conference` | `claims.py`, `adjuster_swml()`; served at `/brief` in `app.py` |
| `join_conference` | `app.py`, `join_adjuster` handler |
| Claim record validated against `data/claim.schema.json` | `claims.py`, `save()` |

## Prerequisites

- Python 3.12 and a SignalWire Space (project ID, API token, Space URL)
- A phone number on the Space for callers (in the demo pool, `TEST_INBOUND` from NUMBERS.md)
- An outbound-capable number for the adjuster leg's caller ID (`FROM_NUMBER`; demo pool `OUTBOUND_2`)
- A second phone that acts as the adjuster (`ADJUSTER_NUMBER`). In the demo pool it defaults
  to `HUMAN_LEG`, which nobody answers, so every call ends on the callback path. **For a live
  test, set `ADJUSTER_NUMBER` to a real phone you can pick up.**
- A public URL for your machine (ngrok or similar)
- No third-party accounts

## Setup

```bash
git clone https://github.com/signalwire-demos/ai-recipes
cd ai-recipes/recipes/09-insurance-claim-intake
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env    # fill in the SIGNALWIRE_* keys, PUBLIC_URL and basic auth
```

In `.env`, set `ADJUSTER_NUMBER` (the phone that gets the briefing) and `FROM_NUMBER` (an
outbound-capable number on your Space). Claims are written to `data/runtime/claims.json`,
which is created on the first call and is git-ignored.

## Run locally

```bash
python app.py                      # serves SWML on :3000
ngrok http 3000                    # in another terminal; put the URL in PUBLIC_URL
```

In the SignalWire Dashboard, set the phone number's call handler to
`https://USER:PASS@<your-tunnel>/` (USER/PASS = SWML_BASIC_AUTH_USER/PASSWORD), then call it.
Answer one question at a time: policy "P O L zero one zero one", then a date such as
"October twenty eighth", a place such as "Main Street and Third Avenue", what happened, and
whether anyone was hurt. When the adjuster phone rings you hear the claim summary. Press 1 to be joined to
the caller, or let it ring out (or press any other key) to see the callback path.

Without a phone:

```bash
pytest -q
swaig-test app.py --list-tools
swaig-test app.py --dump-swml --raw | jq '.sections.main[-1].ai.prompt.contexts'
swaig-test app.py --custom-data '{"global_data": {"fnol": {"policy_number": "POL-0101",
  "incident_date": "October 28", "location": "Main and 3rd",
  "description": "Rear-ended at a red light", "injuries": false}}}' --exec submit_claim
curl -u USER:PASS "http://localhost:3000/brief?claim=CL-0001&call=test"   # the adjuster's SWML
```

With `ADJUSTER_NUMBER` or `FROM_NUMBER` unset, `submit_claim` goes straight to `callback`.
Set both to see the `hold` and `rpc_dial` actions in the `--exec` output.

## Deploy

```bash
docker compose up --build          # reads .env, serves on :3000
```

Put it behind any HTTPS host and point the number at `https://USER:PASS@<host>/`.
Serverless: not suited as-is, because claims live in a local JSON file. Point `claims.py` at a
database first.

## What to change first

Open `config.py`: edit `pick_adjuster()` to route by claim type (for example, injuries to a
bodily-injury desk) instead of one `ADJUSTER_NUMBER`, and tune `HOLD_TIMEOUT`. Set
`POLICY_PREFIX` and `POLICY_DIGITS` to your policy number format and `MAX_CLAIM_AGE_DAYS` to
how far back a claim can be filed by phone. `MODEL` picks the LLM. To change the
claim fields, edit the gather questions in `app.py`, `CHECKS` in `answers.py`, `FIELDS` and
`briefing()` in `claims.py`, and `data/claim.schema.json` together.
