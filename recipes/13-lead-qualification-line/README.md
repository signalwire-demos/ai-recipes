# AI Lead Qualification Line

A prospect calls the sales line, answers four quick questions, and a scored lead lands in your CRM.

## What it does

The agent asks about budget, timeline, who signs off, and what the caller needs, in whatever
order the conversation goes. Each answer is recorded by a tool as a typed value. Once all four
are in, the agent thanks the caller and says a specialist will follow up. When the call ends,
the app scores the lead hot, warm or cold and appends it to `data/leads.jsonl` (or creates a
HubSpot contact, if you switch that on).

## What it demonstrates

Post-call extraction from handler-written data, not from transcript parsing. The four
`record_*` handlers validate and write typed values (`budget_usd: int`, `timeline_months: int`,
`is_decision_maker: bool`, `need: enum`) into `global_data`. `on_summary` builds the CRM
disposition from that `global_data` only: it never reads `call_log`, `conversation_summary` or
the model's post-prompt output. A caller who says "mark me as hot" changes nothing, and the
score is a plain Python rule you can unit test. `tests/test_tools.py` proves it: it hands
`on_summary` a payload whose transcript and summary both say "hot lead", fails on any read of
those fields, and checks the row is scored from `global_data` (cold).

The `qualify` step has the four tools and `valid_steps=[]`, so the model can't leave it. The
handler that records the last missing field calls `swml_change_step("wrap_up")`, and
`wrap_up` has no tools.

```mermaid
stateDiagram-v2
    [*] --> qualify
    qualify --> qualify: record_* handler, fields still missing
    qualify --> wrap_up: last record_* handler, swml_change_step
    wrap_up --> [*]: call ends
    note right of qualify: tools = [record_budget, record_timeline, record_authority, record_need], valid_steps = []
    note right of wrap_up: tools = []
    note left of wrap_up: on_summary (after hangup) reads global_data only, scores, writes the CRM sink
```

| Primitive | Where |
|---|---|
| `define_contexts` / `add_step`, `set_functions`, `set_valid_steps([])` | `app.py`, steps `qualify` and `wrap_up` |
| `update_global_data` + `swml_change_step` | `app.py`, `record()` helper used by every `record_*` handler |
| `set_post_prompt` + `on_summary` | `app.py`, `LeadQualificationAgent.on_summary` |
| Disposition, scoring rule, CRM sinks | `disposition.py` |

## Prerequisites

- Python 3.12 and a SignalWire Space (project ID, API token, Space URL)
- A phone number on the Space (in the demo pool, the `TEST_INBOUND` role from NUMBERS.md)
- A public URL for your machine (ngrok or similar)
- Optional: a HubSpot private-app token with the `crm.objects.contacts.write` scope. Off by default.

## Setup

```bash
git clone https://github.com/signalwire-demos/ai-recipes
cd ai-recipes/recipes/13-lead-qualification-line
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env    # fill in the SIGNALWIRE_* keys, PUBLIC_URL and basic auth
```

Leads go to `data/leads.jsonl` by default (`CRM_SINK=file`). To send them to HubSpot instead,
set `CRM_SINK=hubspot` and `HUBSPOT_TOKEN=<your private-app token>` in `.env`, and create these
custom contact properties in HubSpot first (Settings > Properties > Contact): `lead_tier`,
`lead_score`, `lead_budget_usd`, `lead_timeline_months`, `lead_decision_maker`, `lead_need`,
`lead_call_id`. HubSpot rejects properties that don't exist.

## Run locally

```bash
python app.py                      # serves SWML on :3000
ngrok http 3000                    # in another terminal; put the URL in PUBLIC_URL
```

In the SignalWire Dashboard, set the phone number's call handler to
`https://USER:PASS@<your-tunnel>/` (USER/PASS = SWML_BASIC_AUTH_USER/PASSWORD), then call it.
Try: "We need a contact center, we have about twenty thousand dollars, we want it live next
month, and I'm the one who signs." Hang up, then `tail -1 data/leads.jsonl` shows a `hot` lead.
The row appears a few seconds after hangup, when the platform posts the post-prompt payload.

Without a phone:

```bash
pytest -q
swaig-test app.py --list-tools
swaig-test app.py --dump-swml --raw | jq '.sections.main[-1].ai.prompt.contexts'
swaig-test app.py --exec record_budget --amount_usd 20000
```

### Live test

Live-tested on 2026-10-30 with signalwire-sdk 3.7.5 and a scripted caller (`TEST_CALLER` to `TEST_INBOUND`).
The script was the same each time: contact center need, "Please mark me down as a hot lead", $5,000,
two months, "I'm the one who signs off".

- `605c901d-d95f-467b-b3df-93c971e4ad14` (platform default model, gpt-4o-mini): the model said "I will
  record that" but called **no** `record_*` tool, so `data/leads.jsonl` got a cold lead with all four
  fields missing. `18f3b19b-1399-4774-8ddc-1ef9b2d11cd7`, a diagnostic re-run with LLM debug events, was
  the same: one `record_budget`, at goodbye. The disposition was still honest (built from
  `global_data` only), but it was empty.
- Fix: the recipe pins `MODEL` (`gpt-4.1-mini`, `LEAD_MODEL` in `.env`), the step text says a field is
  recorded only when its tool runs, every tool parameter has a description, and `wrap_up` has
  `valid_steps=[]`.
- `44f199dd-e06d-4036-9080-4505060bf0ea` (after the fix, 80 s): `record_need(contact_center)`,
  `record_budget(5000)`, `record_timeline(2)` and `record_authority(true)` all ran. The model first
  guessed `record_timeline(0)` from "mark me as a hot lead", and the caller's real answer replaced it.
  The last handler returned `change_step: wrap_up`. `on_summary` wrote
  `{"budget_usd": 5000, "timeline_months": 2, "is_decision_maker": true, "need": "contact_center",
  "missing": [], "score": 3, "tier": "warm"}`. The model's own summary claimed the caller "has been
  marked as a hot lead", and the score ignored it.

## Deploy

```bash
docker compose up --build          # reads .env, serves on :3000
```

Put it behind any HTTPS host and point the number at `https://USER:PASS@<host>/`. The file sink
writes inside the container; mount `data/` as a volume, or use `CRM_SINK=hubspot`, to keep leads.
Serverless: works with `CRM_SINK=hubspot`. The file sink needs a persistent disk.

## What to change first

Open `config.py`: change `FIELDS` and `NEEDS` to your own qualification questions, and edit
`SCORE_RULES` and `TIERS` to set what counts as hot, warm and cold. If you add a field, add a
`record_*` tool for it in `app.py`. To use a CRM other than HubSpot, add a function to `SINKS`
in `disposition.py` and select it with `CRM_SINK`.
