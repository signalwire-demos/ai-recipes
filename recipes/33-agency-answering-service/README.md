# AI Answering Service for Agencies

One deployment answers the phone for many businesses: a caller to the dental office hears the dental office, and a caller to the HVAC company hears the HVAC company, each with its own voice, hours, tools and transfer lines.

## What it does

An agency runs one app for every client. When a call comes in, the app works out which
business was called (by the called number, or `?tenant=<id>` on the webhook URL), loads
that business's `tenants/<id>.yaml` and answers as that business. The three sample tenants
are Bright Smile Dental (appointment requests, transfer to the front desk), Northwind
Heating and Air (service requests, and emergencies connect straight to the on-call
technician at any hour) and Hale and Ortiz Law (consultation requests by practice area,
transfer to intake). A call to an unknown number gets a neutral answering service that can
only take a message.

## What it demonstrates

Per-request configuration instead of one deployment per customer. `set_dynamic_config_callback`
runs on every request, both the SWML fetch and every SWAIG call, against a per-request copy of
the agent. The callback resolves the tenant on the server and registers only that tenant's
tools, so a tool enabled for one tenant **does not exist** for another. It isn't hidden by the
prompt, it's absent from the SWML, and a SWAIG call to it gets "not found". Handlers
read the tenant, hours and transfer numbers from the YAML (bound in a closure), never from model
arguments: `transfer_call` only accepts the target names in that tenant's `transfer_targets`
(an `enum`), refuses outside office hours, and dials the number from `.env`.
`add_swaig_query_params({"tenant": id})` keeps SWAIG callbacks on the same tenant.

```mermaid
stateDiagram-v2
    [*] --> resolve: SWML request (call.to, ?tenant=)
    resolve --> dental: call.to = TENANT_1, or ?tenant=dental
    resolve --> hvac: call.to = TENANT_2, or ?tenant=hvac
    resolve --> law: call.to = TENANT_3, or ?tenant=law
    resolve --> default: no match
    dental --> [*]: transfer_call handler, connect (open hours only)
    hvac --> [*]: dispatch_technician(emergency) handler, connect on-call
    law --> [*]: transfer_call handler, connect (open hours only)
    default --> [*]: take_message, model ends the call
    note right of dental: tools = [check_hours, take_message, book_appointment, transfer_call]
    note right of hvac: tools = [check_hours, take_message, dispatch_technician]
    note right of law: tools = [check_hours, take_message, request_consultation, transfer_call]
    note right of default: tools = [take_message]
```

| Primitive | Where |
|---|---|
| `set_dynamic_config_callback` | `app.py`, `AnsweringServiceAgent.__init__` → `configure()` |
| Server-side tenant resolution (number, then `?tenant=`, then default) | `app.py`, `resolve_tenant()` |
| Per-tenant `define_tool` from a registry | `app.py`, `TOOLS` and `configure()` |
| `add_swaig_query_params` | `app.py`, `configure()` |
| `connect` to a YAML/.env number only | `app.py`, `transfer_to()` |
| Tenant config (prompt, voice, hours, tools, targets) | `tenants/*.yaml` |

## Prerequisites

- Python 3.12 and a SignalWire Space (project ID, API token, Space URL)
- One phone number is enough (route with `?tenant=`). Ideally one per tenant: in the demo pool,
  `TENANT_1`, `TENANT_2` and `TENANT_3` from NUMBERS.md
- A public URL for your machine (ngrok or similar)
- For a live transfer test, a real phone you can answer. No third-party accounts.

## Setup

```bash
git clone https://github.com/signalwire-demos/ai-recipes
cd ai-recipes/recipes/33-agency-answering-service
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env    # fill in the SIGNALWIRE_* keys, PUBLIC_URL and basic auth
```

In `.env`, set `TENANT_1`, `TENANT_2` and `TENANT_3` to the numbers that route to each tenant
(E.164, or leave them blank and use `?tenant=`). Set `DENTAL_FRONT_DESK`, `HVAC_ON_CALL` and
`LAW_INTAKE_DESK` to a phone you can answer; a blank target makes the transfer refuse politely.

## Run locally

```bash
python app.py                      # serves SWML on :3000
ngrok http 3000                    # in another terminal; put the URL in PUBLIC_URL
```

Point every tenant number's call handler at the same `https://USER:PASS@<your-tunnel>/`
(USER/PASS = SWML_BASIC_AUTH_USER/PASSWORD). With a single number, use
`https://USER:PASS@<your-tunnel>/?tenant=hvac` and change the query to switch tenants.

Without a phone:

```bash
pytest -q
swaig-test app.py --dump-swml --raw --query-params '{"tenant": "dental"}' | jq '[.sections.main[-1].ai.SWAIG.functions[].function]'
swaig-test app.py --dump-swml --raw --query-params '{"tenant": "hvac"}'   | jq '[.sections.main[-1].ai.SWAIG.functions[].function]'
TENANT_3=+15550113 swaig-test app.py --dump-swml --raw --override call.to=+15550113 | jq .sections.main[-1].ai.global_data
swaig-test app.py --query-params '{"tenant": "law"}' --exec check_hours --day friday
swaig-test app.py --query-params '{"tenant": "hvac"}' --exec book_appointment   # "not found in agent"
```

On the call, try "I'd like a cleaning next Tuesday" (dental), "My furnace is out and it's
freezing" (HVAC, emergency → on-call line), or "I need help with my mother's estate" (law).
Messages and requests land in `data/runtime/messages.jsonl`, tagged with the tenant id.

## Deploy

```bash
docker compose up --build          # reads .env, serves on :3000
```

Put it behind any HTTPS host and point every tenant number at `https://USER:PASS@<host>/`.
Tenant files are read on each request, so adding a client is copying a YAML file into
`tenants/` (or a mounted volume); no redeploy. Serverless works for the agent itself, but move
`MESSAGES_FILE` to a real store first, since function filesystems are ephemeral.

## What to change first

The tenant YAML schema is the thing to make yours: copy `tenants/dental.yaml` to
`tenants/<id>.yaml` (the file name must equal `id`), set `numbers`, `name`, `voice`, `timezone`,
`hours`, `prompt`, `tools` (names from `TOOLS` in `app.py`) and `transfer_targets`. Then open
`config.py`: `DEFAULT_TENANT` decides what an unknown caller gets, `ALLOW_TENANT_QUERY=False`
turns off `?tenant=` routing in production, and `MESSAGES_FILE` is where messages go. A new
kind of tool is one entry in `TOOLS`; it reaches only the tenants that list it.
