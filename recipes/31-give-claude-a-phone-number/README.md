# Give Claude a Phone Number

A support phone line whose tools are also an MCP server, so Claude can look up customers
and book callbacks with the same code the phone caller uses.

## What it does

Callers reach the Acme Fiber support line. The agent asks for the phone number on the
account, looks it up in a mock CRM (`data/customers.json`), and then offers to book a
callback or transfer the call to a person. Bookings are appended to
`data/runtime/callbacks.jsonl`.

The same agent also serves `POST /mcp`, a Model Context Protocol endpoint. Point Claude
Desktop, Claude Code or any MCP client at it and ask, for example, "Find the Acme account
for 555-555-0101 and book them a callback Monday at 10:30". Claude calls `lookup_customer`
and `book_callback`, the same handlers, the same validation, and the same bookings file the
phone line writes to.

## What it demonstrates

The agent as an MCP server, with code (not the prompt) deciding what each channel can reach.

- `enable_mcp_server()` exposes the agent's tools at `/mcp`. It has its own credential, a
  bearer token (`MCP_TOKEN`). The SWML basic auth, which sits in the number's webhook URL,
  doesn't open `/mcp`, and the token doesn't open the SWML routes. The SDK's `/mcp` route
  checks auth through `_check_basic_auth()`, so the app overrides that one method for the
  `/mcp` path only. Like `_mcp_tools()`, it's a private hook: the auth tests fail if it stops
  working after an upgrade.
- `config.MCP_TOOLS` is an allowlist. `transfer_to_human` moves a live call, so it stays
  voice-only: MCP clients can't list it, and `tools/call` refuses it (`-32602 Unknown tool`).
  The allowlist lives in one small override of `_mcp_tools()`, the method the SDK's `/mcp`
  route uses both to list and to call tools. It's a private hook in signalwire-sdk 3.7.5, so
  re-check it when you upgrade (the governance test fails if it stops working).
- An MCP client has no steps, so the handlers carry their own rules. `book_callback` refuses
  unknown accounts, past times, weekends and after-hours slots on both channels. On a call it
  books for the account `lookup_customer` put in `global_data`, whatever id the model passes.
  Over MCP there is no call state, so it also needs the phone number on that account: a
  guessed account id alone books nothing.
- `lookup_customer` returns only `account_id`, `name` and `plan`. The CRM's `internal` block
  (credit risk, churn score) never reaches the phone model or Claude.
- On the phone, steps scope the tools: `identify` has only `lookup_customer` and no
  navigation, and only its handler moves the call to `help`.

Over MCP only the handler's response text comes back. Actions such as `swml_change_step`
and `update_global_data` are call-control instructions and are dropped there, which is why
nothing call-moving belongs on the MCP list.

```mermaid
flowchart LR
    caller([Phone caller]) -->|SWAIG| identify
    subgraph voice [Voice steps]
        identify["identify<br/>tools: lookup_customer<br/>valid_steps: []"] -->|lookup handler<br/>swml_change_step| help["help<br/>tools: book_callback,<br/>transfer_to_human"]
    end
    claude([Claude / MCP client]) -->|"POST /mcp<br/>tools/list, tools/call"| allow{{"MCP_TOOLS allowlist"}}
    allow --> lookup[lookup_customer]
    allow --> book[book_callback]
    allow -. refused .-> xfer[transfer_to_human]
    identify --- lookup
    help --- book
    help --- xfer
```

| Primitive | Where |
|---|---|
| `enable_mcp_server()` | `app.py`, `PhoneAgent.__init__` |
| Separate `/mcp` credential (`_check_basic_auth` override) | `app.py`, `PhoneAgent._check_basic_auth`; token in `config.MCP_TOKEN` |
| MCP allowlist (`_mcp_tools` override) | `app.py`, `PhoneAgent._mcp_tools`; list in `config.MCP_TOOLS` |
| `define_contexts` / `set_functions` / `set_valid_steps([])` | `app.py`, steps `identify` and `help` |
| `update_global_data` + `swml_change_step` | `app.py`, `lookup_customer` |
| `connect` (voice-only) | `app.py`, `transfer_to_human` |

## Prerequisites

- Python 3.12 and a SignalWire Space (project ID, API token, Space URL)
- A phone number on the Space (in the demo pool, the `TEST_INBOUND` role from NUMBERS.md)
- A public HTTPS URL for your machine (ngrok or similar)
- An MCP client: Claude Desktop with Node.js 18+ (for the `mcp-remote` bridge), Claude
  Code, or any client that speaks MCP over HTTP
- No third-party accounts

## Setup

```bash
git clone https://github.com/signalwire-demos/ai-recipes
cd ai-recipes/recipes/31-give-claude-a-phone-number
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env    # fill in the SIGNALWIRE_* keys, PUBLIC_URL, basic auth and MCP_TOKEN
```

To test the transfer for real, put a phone you can answer in `HUMAN_NUMBER`.

Set `MCP_TOKEN` in `.env` to a long random string. MCP clients send it as
`Authorization: Bearer <MCP_TOKEN>`. Without it `/mcp` answers 401 to everything and the app
logs `mcp_disabled` at startup; the phone line works either way.

```bash
python -c "import secrets; print(secrets.token_urlsafe(24))"   # paste into MCP_TOKEN=
```

**Claude Desktop.** Desktop's Connectors settings take remote servers that are authless or
use OAuth, and they connect from Anthropic's cloud. This endpoint uses a bearer token, so use the
`mcp-remote` bridge instead. It runs on your machine as a local (stdio) server and adds the
header. Merge `examples/claude_desktop_config.json` into
`~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) or
`%APPDATA%\Claude\claude_desktop_config.json` (Windows):

```json
{
  "mcpServers": {
    "acme-support-line": {
      "command": "npx",
      "args": ["-y", "mcp-remote@0.15.2", "https://YOUR-HOST/mcp",
               "--header", "Authorization:${AUTH_HEADER}", "--transport", "http-only"],
      "env": { "AUTH_HEADER": "Bearer YOUR_MCP_TOKEN" }
    }
  }
}
```

Replace `YOUR-HOST` with your tunnel host and `YOUR_MCP_TOKEN` with your `MCP_TOKEN`. Writing it
as `Authorization:${AUTH_HEADER}` (no space, value in `env`) works around a Windows bug that
breaks spaces inside `args`. Because the bridge runs locally, `http://localhost:3000/mcp`
works too while you develop (mcp-remote allows plain HTTP only for localhost). Restart Claude
Desktop; logs are in `~/Library/Logs/Claude/mcp*.log`.

**Claude Code** speaks HTTP MCP with headers directly:

```bash
claude mcp add --transport http acme-support-line https://YOUR-HOST/mcp \
  --header "Authorization: Bearer YOUR_MCP_TOKEN"
```

## Run locally

```bash
python app.py                      # serves SWML on / and MCP on /mcp, port 3000
ngrok http 3000                    # in another terminal; put the URL in PUBLIC_URL
```

Phone: in the SignalWire Dashboard, set the number's call handler to
`https://USER:PASS@<your-tunnel>/`, call it, give 555-555-0101 as the account number, and
ask for a callback next Monday at 10:30.

Claude: with the config above, ask "Look up the Acme account for 555-555-0102 and book a
callback next Tuesday at 2pm about slow speeds." Then check that both channels wrote to the
same file:

```bash
cat data/runtime/callbacks.jsonl
```

Ask Claude to "transfer me to a human": it has no such tool, because `transfer_to_human`
isn't on `MCP_TOOLS`.

Without a phone or Claude, speak JSON-RPC with curl:

```bash
T="Authorization: Bearer $(grep ^MCP_TOKEN= .env | cut -d= -f2)"
curl -s -H "$T" localhost:3000/mcp -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | jq '.result.tools[].name'
curl -s -H "$T" localhost:3000/mcp -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"lookup_customer","arguments":{"phone":"555-555-0101"}}}'
pytest -q                          # handlers, MCP JSON-RPC via a test client, governance
swaig-test app.py --list-tools
swaig-test app.py --exec lookup_customer --phone 5555550103
```

## Deploy

```bash
docker compose up --build          # reads .env, serves on :3000, keeps bookings in a volume
```

Put it behind any HTTPS host and point the number at `https://USER:PASS@<host>/`, and your
MCP clients at `https://<host>/mcp`. The MCP endpoint is on the same public host as the voice
webhook, behind its own `MCP_TOKEN`, so use a strong token and HTTPS only. Anyone holding the
token can run `lookup_customer` for any phone number they try (there is no rate limit), so
give it only to people who may look customers up, and rotate it if it leaks.

## What to change first

Open `config.py`:

- `MCP_TOOLS`: which tools MCP clients can reach. Every tool not listed is voice-only.
  Leave call-control tools (transfers, hangups, step changes) off it.
- `CUSTOMERS_FILE`, `CALLBACK_HOURS`, `CALLBACK_DAYS`: point at your CRM and booking rules
  (or replace `load_customers()` and the bookings file in `app.py` with your systems).
- `BUSINESS_NAME`, `VOICE`, and `HUMAN_NUMBER` (in `.env`) for the voice side.
