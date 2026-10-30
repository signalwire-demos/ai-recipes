# AI Calendar Assistant Over MCP

A phone line that books and moves appointments using calendar tools from an MCP server.

## What it does

Callers reach Example Dental's scheduling line. The agent asks for their name, then books
a new appointment in a free slot or moves an existing one. The calendar isn't in the agent
at all. It lives behind an MCP server, and the agent points at it with one
`add_mcp_server()` call.

The recipe ships a small reference calendar MCP server, `mcp_calendar.py` (in memory, MCP
over streamable HTTP with JSON responses), so a clean clone works with no outside
accounts. It runs on its own port (`PORT + 1`, so 3001 by default) and offers
`find_free_slots`, `find_my_meetings`, `book_meeting`, `move_meeting` and `cancel_meeting`.
Any other calendar MCP server can replace it: change `MCP_URL` and `MCP_TOKEN`.

## What it demonstrates

Bringing MCP tools onto a live call, and deciding in code which ones the phone agent gets.

- `add_mcp_server(MCP_URL, headers={"Authorization": "Bearer <MCP_TOKEN>"})` renders
  `ai.SWAIG.mcp_servers` in the SWML. **SignalWire's platform, not your agent process,**
  connects to that URL when each call starts. It runs `initialize` and `tools/list`, adds the
  tools to the call as SWAIG functions, and sends their `tools/call` requests straight to the
  MCP server. That's why the tools don't appear in `SWAIG.functions` in a local dump, and why
  `MCP_URL` must be a public HTTPS URL on a live call.
- The token is the scope. The reference server maps each bearer token to a tool list
  (`config.MCP_SCOPES`). The voice agent's `MCP_TOKEN` gets find, book and move.
  `cancel_meeting` needs `MCP_ADMIN_TOKEN`, so it is never even listed to the phone agent,
  and a `tools/call` for it is refused. The token travels inside the SWML document, which is
  one more reason to give it the narrowest scope that works.
- The server holds the rules and the data. Slot checks (weekdays, office hours, 30-minute
  marks, no double booking, nothing in the past) run in the server. `find_free_slots` returns
  times only, never whose meeting is in the way, and `find_my_meetings` returns only the named
  attendee's meetings.
- The prompt's "Rules" section tells the model which tool to use when (find, offer, then book
  or move). The SDK can't scope MCP tools per step: `set_functions()` refuses any name that
  isn't a locally registered tool. So the hard limits are the ones above, set by the token
  and enforced by the server.

The only local tool is `get_today`, so the model can turn "next Tuesday" into a date.

```mermaid
sequenceDiagram
    participant C as Caller
    participant SW as SignalWire platform
    participant A as app.py (agent)
    participant M as mcp_calendar.py (MCP server)
    SW->>A: POST / (fetch SWML)
    A-->>SW: SWML with SWAIG.mcp_servers = [MCP_URL + Bearer MCP_TOKEN]
    SW->>M: initialize, tools/list (Bearer MCP_TOKEN)
    M-->>SW: find_free_slots, find_my_meetings, book_meeting, move_meeting
    Note over M: cancel_meeting is outside this token's scope: not listed, not callable
    C->>SW: "Move my cleaning to Thursday afternoon"
    SW->>A: get_today (SWAIG webhook)
    SW->>M: find_my_meetings, find_free_slots, move_meeting (tools/call)
    M-->>SW: "Moved M-1001 (Cleaning) to ... 14:00."
    SW-->>C: reads back the new time
```

| Primitive | Where |
|---|---|
| `add_mcp_server(url, headers)` | `app.py`, `CalendarAgent.__init__` |
| Token scopes (`MCP_SCOPES`) | `config.py`; enforced in `mcp_calendar.py`, `create_app` |
| Server-side slot rules | `mcp_calendar.py`, `Calendar._check_slot` |
| Local SWAIG tool | `app.py`, `get_today` |

## Prerequisites

- Python 3.12 and a SignalWire Space (project ID, API token, Space URL)
- A phone number on the Space (in the demo pool, the `TEST_INBOUND` role from NUMBERS.md)
- Two public HTTPS URLs for a live call: one for the agent (port 3000) and one for the
  calendar MCP server (port 3001). Two ngrok tunnels work, or one host with two routes.
- No third-party accounts. Optional: a hosted calendar MCP server and its token.

## Setup

```bash
git clone https://github.com/signalwire-demos/ai-recipes
cd ai-recipes/recipes/30-calendar-assistant-over-mcp
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

In `.env`, fill in the `SIGNALWIRE_*` keys, basic auth and `PUBLIC_URL` (the agent's tunnel),
then:

- `MCP_TOKEN`: any long random string, e.g. `python -c "import secrets; print(secrets.token_urlsafe(24))"`.
  The agent sends it, and the reference server accepts it with the voice scope.
- `MCP_URL`: the public URL of the calendar server, ending in `/mcp`.
- `MCP_ADMIN_TOKEN` (optional): a second token whose scope adds `cancel_meeting`, for your own
  tools. Leave it blank to switch the admin scope off.

## Run locally

```bash
python mcp_calendar.py             # terminal 1: calendar MCP server on :3001
python app.py                      # terminal 2: agent SWML on :3000
ngrok http 3001                    # terminal 3: put https://<this>/mcp in MCP_URL, restart app.py
ngrok http 3000                    # terminal 4: put this URL in PUBLIC_URL
```

The agent logs a warning at startup if `MCP_URL` is `localhost`, because SignalWire can't
reach that. In the SignalWire Dashboard, set the number's call handler to
`https://USER:PASS@<agent-tunnel>/`, call it, say you're Dana Rivera, and ask to move your
cleaning to the afternoon. The server seeds Dana's cleaning (10:00) and Sam Okafor's checkup
(11:00) on the next business day each time it starts, and it forgets every change when it
stops.

Without a phone, play the platform's part with curl:

```bash
T="Authorization: Bearer $(grep ^MCP_TOKEN= .env | cut -d= -f2)"
curl -s localhost:3001/mcp -H "$T" -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | jq '.result.tools[].name'
curl -s localhost:3001/mcp -H "$T" -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"find_my_meetings","arguments":{"attendee":"Dana Rivera"}}}'
swaig-test app.py --dump-swml --raw | jq '.sections.main[-1].ai.SWAIG.mcp_servers'
pytest -q                          # SWML, discovery as the platform does it, book/move round trip, scopes
```

## Deploy

```bash
docker compose up --build          # app on :3000, calendar MCP server on :3001
```

Both services read `.env`. Publish both behind HTTPS (for example `https://agent.example.com/`
and `https://calendar.example.com/mcp`), set `MCP_URL` to the calendar's public URL, and point
the number at `https://USER:PASS@agent.example.com/`. The reference server keeps everything in
memory, so a restart resets the calendar. For anything real, use your own calendar MCP server.

## What to change first

Open `config.py`:

- `MCP_URL` and `MCP_TOKEN` (set them in `.env`): point at your real calendar MCP server, and
  ask its owner for a token scoped to what a phone caller should be able to do.
- `MCP_SCOPES`, `OFFICE_HOURS`, `SLOT_MINUTES`, `SEED_MEETINGS`: the reference server's scopes and
  booking rules, if you keep it.
- `BUSINESS_NAME` and `VOICE`, and the "Rules" section in `app.py` if your MCP server's tool
  names differ.
