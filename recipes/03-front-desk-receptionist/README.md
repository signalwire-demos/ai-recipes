# AI Front Desk Receptionist

A caller reaches one front desk and is routed to sales, support or billing, each a different person with a different voice.

## What it does

Riley at the front desk asks what the caller needs and hands them to the right department.
Franklin in sales quotes plan prices. Rachael in support checks outages and opens tickets.
Dwight in billing looks up invoices and refunds them (up to a limit). Callers can move between
departments, but only along the routes the code allows, and each handoff wipes the previous
department's conversation.

## What it demonstrates

Personas that structurally cannot use each other's tools. Each department in `config.DEPARTMENTS`
becomes an isolated context (`set_isolated(True)`) whose step whitelists only that department's
tools with `set_functions`. `issue_refund` is registered on the agent, but it does not exist in
any sales, support or front-desk step, so no prompt can talk Franklin into a refund. Every step
declares `set_functions` explicitly, because a step without it inherits the previous context's
tools. `valid_contexts` is the routing graph: the model's built-in `change_context` tool only
offers the routes listed for the current department. The refund amount comes from the invoice
record, never from the model's arguments. The tests read the SWML dump and assert all of this.

```mermaid
stateDiagram-v2
    [*] --> default
    default --> sales: change_context (model)
    default --> support: change_context (model)
    default --> billing: change_context (model)
    sales --> default: change_context
    sales --> support: change_context
    support --> default: change_context
    support --> sales: change_context
    support --> billing: change_context
    billing --> default: change_context
    billing --> support: change_context
    note right of default: Riley, tools = []
    note right of sales: Franklin, tools = [get_plan_price], no route to billing
    note right of support: Rachael, tools = [check_service_status, open_ticket]
    note right of billing: Dwight, tools = [get_invoice, issue_refund]
```

| Primitive | Where |
|---|---|
| `add_context(...).set_isolated(True)` | `app.py`, one per entry in `config.DEPARTMENTS` |
| `add_language("English-<persona>", ...)` | `app.py`, one voice per department; the context's Voice section names it |
| `set_functions(dept["tools"])` | `app.py`, the `main` step of every context (front desk gets `[]`) |
| `set_valid_contexts(dept["routes"])`, `set_valid_steps([])` | `app.py`, every context and step |
| `add_enter_filler`, `add_internal_filler("change_context", ...)` | `app.py`, covers each handoff |
| Amount from the record | `app.py`, `issue_refund` reads `data/invoices.json` and `config.REFUND_LIMIT` |

## Prerequisites

- Python 3.12 and a SignalWire Space (project ID, API token, Space URL)
- A phone number on the Space (in the demo pool, the `TEST_INBOUND` role from NUMBERS.md)
- A public URL for your machine (ngrok or similar)
- No third-party accounts. Plans, outages and invoices are mock files in `data/`.

## Setup

```bash
git clone https://github.com/signalwire-demos/ai-recipes
cd ai-recipes/recipes/03-front-desk-receptionist
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env    # fill in the SIGNALWIRE_* keys, PUBLIC_URL and basic auth
```

Tickets and refunds are appended to `data/tickets.jsonl` and `data/refunds.jsonl` (git-ignored).
Delete `data/refunds.jsonl` to make the test invoices refundable again.

## Run locally

```bash
python app.py                      # serves SWML on :3000
ngrok http 3000                    # in another terminal; put the URL in PUBLIC_URL
```

In the SignalWire Dashboard, set the phone number's call handler to
`https://USER:PASS@<your-tunnel>/` (USER/PASS = SWML_BASIC_AUTH_USER/PASSWORD), then call it.
Try: "How much is the gigabit plan?", then "Can I get a refund on invoice INV-1001?" (sales has
no route to billing, so Franklin sends you back to the front desk or to support first).
`INV-1002` is over the refund limit and `INV-1003` is already refunded.

Live-tested 2026-10-30, inbound call `b9b47966-4813-4c3a-811b-543fe055920b` (146 s, scripted
caller, stereo recording on the caller leg). The platform's debug log shows `context_change`
default -> sales -> support -> billing (all `isolated: true`). Each department's replies carry its
own language tag (`English-Franklin`, `English-Rachael`, `English-Dwight`), and each one called
only its own tools: `get_plan_price`, then `check_service_status` + `open_ticket` (ticket written
to `data/tickets.jsonl`), then `get_invoice`. The recording's agent channel changes voice at each
handoff: median pitch about 230 Hz for Riley (`inworld.Sarah`), 130 to 160 Hz for Franklin
(`inworld.Mark`), 170 to 195 Hz for Rachael (`inworld.Ashley`, so that voice id loads and
speaks), and about 85 Hz for Dwight (`inworld.Blake`). No calling errors were logged. The call
also found a bug, now fixed: speech recognition handed over "Inv1001", which the old exact
`.upper()` lookup couldn't find. `invoice_key()` now normalizes it to `INV-1001`. The refund
after that fix has not been tested live.

Without a phone:

```bash
pytest -q
swaig-test app.py --list-tools
swaig-test app.py --dump-swml --raw | jq '.sections.main[-1].ai.prompt.contexts | map_values(.steps[0].functions)'
swaig-test app.py --exec get_invoice --invoice_id INV-1001
swaig-test app.py --exec issue_refund --invoice_id INV-1001
```

## Deploy

```bash
docker compose up --build          # reads .env, serves on :3000
```

Put it behind any HTTPS host and point the number at `https://USER:PASS@<host>/`.
Serverless: the agent itself is stateless, but `open_ticket` and `issue_refund` append to local
files in `data/`. Point `TICKETS_FILE` and `REFUNDS_FILE` at real systems before running it on
Lambda or Cloud Functions.

## What to change first

Open `config.py`: edit `DEPARTMENTS`. Each entry sets a department's context name, persona,
voice, role text, the tools it owns and the departments it may route to. Then set
`BUSINESS_NAME` and `REFUND_LIMIT`, and swap the files in `data/` for your own systems.
