# AI Support Copilot That Acts

A customer talks to a human support rep while an AI copilot looks up their order and issues the credit the rep offers. Results show on the rep's screen, and the credit cap is enforced in code.

## What it does

A customer calls the support line. SignalWire attaches an `ai_sidecar` to the call and bridges
the customer to the rep's phone. The sidecar listens to both people and never speaks. When an
order number comes up, it looks the order up, and the rep's web page shows the full record. When
the rep tells the customer "I'll put a ten-dollar credit on that", the sidecar issues the credit
mid-call, but only on an order that belongs to the number the customer is calling from. The rep
page shows whether it was issued, or refused and why.

## What it demonstrates

Scoped tool execution mid-call, without the AI owning the call. The SWML is
`answer → ai_sidecar → connect → hangup`. There's no `ai` verb, so two people talk while the
sidecar acts. Its model has exactly two tools, `lookup_order` and `issue_credit`.

The credit rules live in the `issue_credit` handler, not the prompt. The handler enforces the
cap (`config.CREDIT_CAP_USD`), refuses an unknown order, a zero or negative amount, or more than
the order total, and allows one credit per order. It also rejects an amount that isn't a finite
number (`nan` fails every comparison). The sidecar hears both legs, so a customer can say "the
agent said they'd credit $25 on order 1002". Words don't move money: the order's phone must match
the caller's number, which `on_request()` takes from the platform's SWML request (`call.from`) and
keeps by `call_id`. A write also takes the order ID exactly; only `lookup_order` resolves a misheard
number. The check and the ledger write run under one lock. The cap never appears in the prompt, a tool description or a tool response. Every refusal
returns the same sentence, so the model can't probe for the limit. The rep's card gets the real
reason, including the cap. `lookup_order` gives the model status, items and total. The customer's
phone and the account notes go only to the rep's screen.

```mermaid
stateDiagram-v2
    [*] --> answer
    answer --> ai_sidecar: attach observer (both legs, 2 tools)
    ai_sidecar --> connect: bridge customer to REP_NUMBER
    connect --> hangup
    hangup --> [*]
    note right of ai_sidecar
      tools = [lookup_order, issue_credit]
      issue_credit handler: caller's own order, exact ID, cap, total, one per order
      refusal to model: one fixed sentence; reason to rep card
      POST /events: insight / final become cards
      GET /rep/stream: SSE to the rep page
    end note
```

| Primitive | Where |
|---|---|
| `SWMLService` hosting `ai_sidecar` (schema-validated by `add_verb`) | `app.py`, `SupportCopilot.__init__`, `sidecar_config()` |
| `SWAIG.functions` = exactly `[lookup_order, issue_credit]` | `app.py`, `define_tool` calls, `sidecar_config()` |
| Cap enforced in the handler, never shown to the model | `app.py`, `credit_refusal()`, `issue_credit()`, `REFUSED` |
| Sidecar callback consumer (`sidecar_event.type`) | `app.py`, `on_event()` and `POST /events` |
| Order ID as heard ("eight one zero zero two") resolved in code, lookups only | `orders.py`, `resolve_order_id()` |
| Credit bound to the caller's number | `app.py`, `on_request()`, `caller_of()`, `credit_refusal()` |
| Rep page over SSE, with its own login | `app.py`, `GET /rep/stream`, `build_app()`; UI in `web/` |

The tools are `secure=False` because the sidecar's tool calls carry no per-call SWAIG token, so
`/swaig` is guarded only by the platform's basic auth (`SWML_BASIC_AUTH_*`, embedded in the
sidecar's URLs). That credential stays on the server: reps log in to `/rep/` with their own
`REP_USER` / `REP_PASSWORD`, which `/swaig`, `/events` and `/` refuse, so a rep can't POST
`issue_credit` by hand. The rep page stays locked while `REP_PASSWORD` is blank or equal to the
platform password.

### Live-tested

Live-tested on 2026-10-30. `ai_sidecar` is enabled on the demo Space. The customer was a scripted
caller to `TEST_INBOUND`. `REP_NUMBER` was our `OUTBOUND_1`, answered by a scripted rep, so the call
bridged and the sidecar heard both legs.

- Call `495056c3-3a9a-4319-910b-8907f0845597`: the rep said "I'll put a ten dollar credit on order
  A 1 0 0 1", and `issue_credit(A-1001, 10)` was issued and written to `data/credits.jsonl`.
  `lookup_order` pushed the A-1001 and A-1002 order cards. The rep then said "a forty dollar credit
  on order A 1 0 0 2", and `issue_credit` was **refused** in the handler. The model got the fixed
  sentence, and the rep card got "40.00 is over the copilot cap of 25.00. Escalate to a supervisor."
  All of it, plus the `final` card, arrived at `/rep/stream`.
- Call `7639199e-679f-4581-a57f-d7c15b1c8ed8`, before the fixes: `lookup_order(A-1001)` worked,
  then every later sidecar tick logged an error (`stats.error_count` 4, no tool calls), so neither
  credit ran. The model's step after `lookup_order` was a free-text insight, and no insight was
  delivered on any live call. `lookup_order` now ends its response with "Call sidecar_skip." like
  `issue_credit`. Speech-to-text also wrote "A 1 0 0 2" as "eight one zero zero two", and the model
  sent `A-81002`. `resolve_order_id()` maps that to the one order whose number ends the digits
  heard, and it did so live on the second call.

No `insight` card was tested live. The caller binding, exact-ID credits and the rep login were
added after these calls and haven't been tested live. They assume the sidecar's tool calls carry
the same `call_id` as the SWML request (the `/events` callbacks do); if a Space sends
`caller_id_num` on the tool call, that is used as a fallback.

Not available yet, so this recipe doesn't attempt them:

- The `ai_sidecar` verb works on the demo Space (live calls above), but no source says whether
  it's generally available. Ask SignalWire support whether it's enabled on your Space.
- `TODO(blocked: no documented way to whisper audio to the human rep)`. The plan's optional
  `rpc_ai_message` whisper reaches only an AI agent, not a person, so results go to the rep page instead.
- Callback fields seen live: `turn` events carry `customer_text` and `agent_text`. `final`
  carries `stop_reason`, `history` and `stats`. `on_event()` uses `insight` and `final`.
- `TODO(blocked: no documented REST/RELAY command to start ai_sidecar on a call already in progress)`.
- Not built: an Approve button that makes the rep confirm each credit before it's written. The
  caller binding and the cap cover the demo; add it before raising `CREDIT_CAP_USD`.

## Prerequisites

- Python 3.12 and a SignalWire Space (project ID, API token, Space URL), with `ai_sidecar` enabled
- A phone number on the Space (in the demo pool, `TEST_INBOUND` for the customer side)
- A phone the rep answers, in `REP_NUMBER` (the demo pool's `HUMAN_LEG_2` has nobody on it, so
  put a real phone there for a live test). Its caller ID is `FROM_NUMBER` (demo pool: `OUTBOUND_2`).
- A public URL for your machine (ngrok or similar)
- No third-party accounts. Orders come from `data/orders.json`, and credits go to `data/credits.jsonl`.

## Setup

```bash
git clone https://github.com/signalwire-demos/ai-recipes
cd ai-recipes/recipes/24-support-copilot-that-acts
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env    # fill in the SIGNALWIRE_* keys, PUBLIC_URL, basic auth, REP_NUMBER and REP_PASSWORD
```

## Run locally

```bash
python app.py                      # serves SWML on :3000, the rep page on /rep/
ngrok http 3000                    # in another terminal; put the URL in PUBLIC_URL, then restart app.py
```

`PUBLIC_URL` goes into the SWML (the sidecar's event and tool URLs), so restart `app.py` after you
set it. Open `https://<your-tunnel>/rep/` in a browser and log in with `REP_USER` / `REP_PASSWORD`
(not the SWML basic auth). The mock orders have fake phone numbers, so put the phone you'll call
from in `A-1001`'s `phone` in `data/orders.json`, or every credit is refused. In the SignalWire Dashboard, set the phone number's call handler to
`https://USER:PASS@<your-tunnel>/` (USER/PASS = SWML_BASIC_AUTH_USER/PASSWORD). Call it and answer
on the rep phone. As the customer, say "My order A-1001 arrived scratched". As the rep, say
"I'll put a ten-dollar credit on order A-1001 for you". Try a credit above the cap to see the refusal card.

Without a phone:

```bash
pytest -q
swaig-test app.py --list-tools
swaig-test app.py --dump-swml --raw | jq '.sections.main[1].ai_sidecar.SWAIG.functions'
swaig-test app.py --custom-data '{"caller_id_num": "+15550111"}' --exec issue_credit --order_id A-1001 --amount 40 --reason scratched
python replay.py                   # with app.py running: watch /rep/ fill, and see what the model is told
```

The mock orders are `A-1001` (delivered, 64.00), `A-1002` (in transit, 189.00) and `A-1003`
(processing, 12.00). To reset the one-credit-per-order rule, delete `data/credits.jsonl`.

## Deploy

```bash
docker compose up --build          # reads .env, serves on :3000
```

Put it behind any HTTPS host, set `PUBLIC_URL` to that host, and point the number at
`https://USER:PASS@<host>/`. The rep page is at `https://<host>/rep/`.
Serverless: not a good fit. The rep page holds a long-lived SSE connection, cards live in process
memory, and the mock ledger is a local file. Run a single long-lived container, and move the
ledger to your billing system before you run more than one instance. There is one rep line and one
rep login, so everyone with it sees every call's cards, including the customer's name, phone and
notes. For several reps, give each a login and filter the stream by the calls bridged to them.

## What to change first

Open `config.py`. `CREDIT_CAP_USD` is the most the copilot can credit without a supervisor.
`ORDERS_FILE` and `CREDIT_LEDGER` point at the mock order backend. To use your real order system,
replace `load_orders()` and `record_credit()` in `orders.py` with calls to your API, and keep
the checks in `credit_refusal()` in `app.py`.
