# AI Calendar Assistant Over MCP

A phone line that books and moves appointments using calendar tools from an MCP server.

## What it does

Callers reach Example Dental's scheduling line. The agent asks for their name, then books
a new appointment in a free slot or moves an existing one. The calendar isn't in the agent
at all. It lives behind an MCP server, and the agent points at it with one
`add_mcp_server()` call.

The recipe ships a small reference calendar MCP server, `mcp_calendar.py` (in memory, MCP
over streamable HTTP with JSON responses), so a clean clone works with no outside
accounts. `app.py` serves it from the same app and port as the agent, at `/mcp-calendar`, so
one public URL covers both the SWML and the MCP server. It offers `find_free_slots`,
`find_my_meetings`, `book_meeting`, `move_meeting` and `cancel_meeting`. Any other calendar
MCP server can replace it: set `MCP_URL` and `MCP_TOKEN`.

## What it demonstrates

Bringing MCP tools onto a live call, and deciding in code which ones the phone agent gets.

- `add_mcp_server(MCP_URL, headers={"Authorization": "Bearer <MCP_TOKEN>"})` renders
  `ai.SWAIG.mcp_servers` in the SWML. **SignalWire's platform, not your agent process,**
  connects to that URL when each call starts. It runs `initialize` and `tools/list`, adds the
  tools to the call as SWAIG functions, and sends their `tools/call` requests straight to the
  MCP server. That's why the tools don't appear in `SWAIG.functions` in a local dump, and why
  `MCP_URL` must be a public HTTPS URL on a live call. By default `MCP_URL` is
  `PUBLIC_URL + /mcp-calendar`, the reference server inside this app, so the agent's tunnel
  is enough.
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

The only local tool is `get_today`, so the model can turn "next Tuesday" into a date. It has
a guard: if the MCP tools never reach the call (a wrong `MCP_URL`, a server that's down),
`get_today` is the model's only tool, and in testing the model called it 10 times in a row.
From the second call on, `get_today` tells the model it already has the date. After
`GET_TODAY_MAX_CALLS` (3) calls, it says the calendar is unavailable, tells the model to
apologize and say goodbye, and switches itself off with `toggle_functions`. The app also logs
a warning that names `MCP_URL`.

```mermaid
sequenceDiagram
    participant C as Caller
    participant SW as SignalWire platform
    participant A as app.py (agent, /)
    participant M as mcp_calendar.py (same app, /mcp-calendar)
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
| Reference MCP server mounted in the agent | `app.py`, `self.mount(mcp_calendar.create_router(...), prefix=config.MCP_CALENDAR_PATH)` |
| Token scopes (`MCP_SCOPES`) | `config.py`; enforced in `mcp_calendar.py`, `create_router` |
| Server-side slot rules | `mcp_calendar.py`, `Calendar._check_slot` |
| Local SWAIG tool with a loop guard | `app.py`, `get_today` (`toggle_functions` after `GET_TODAY_MAX_CALLS`) |

## Prerequisites

- Python 3.12 and a SignalWire Space (project ID, API token, Space URL)
- A phone number on the Space (in the demo pool, the `TEST_INBOUND` role from NUMBERS.md)
- One public HTTPS URL for a live call (for example `ngrok http 3000`). It serves both the
  agent's SWML and the reference calendar MCP server at `/mcp-calendar`.
- No third-party accounts. Optional: a hosted calendar MCP server and its token.

## Setup

```bash
git clone https://github.com/signalwire-demos/ai-recipes
cd ai-recipes/recipes/30-calendar-assistant-over-mcp
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

In `.env`, fill in the `SIGNALWIRE_*` keys, basic auth and `PUBLIC_URL` (your tunnel), then:

- `MCP_TOKEN`: any long random string, e.g. `python -c "import secrets; print(secrets.token_urlsafe(24))"`.
  The agent sends it, and the reference server accepts it with the voice scope.
- `MCP_URL`: leave it unset to use the built-in reference calendar at `PUBLIC_URL/mcp-calendar`.
  Set it only for an external calendar MCP server (a public HTTPS URL). Setting it switches
  the built-in calendar off, unless you also set `SERVE_REFERENCE_CALENDAR=true`.
- `MCP_ADMIN_TOKEN` (optional): a second token whose scope adds `cancel_meeting`, for your own
  tools. Leave it blank to switch the admin scope off.

## Run locally

```bash
python app.py                      # terminal 1: agent SWML at / and calendar MCP at /mcp-calendar, on :3000
ngrok http 3000                    # terminal 2: put this URL in PUBLIC_URL, restart app.py
```

The agent logs a warning at startup if `MCP_URL` is `localhost` (`PUBLIC_URL` unset), because
SignalWire can't reach that. In the SignalWire Dashboard, set the number's call handler to
`https://USER:PASS@<agent-tunnel>/`, call it, say you're Dana Rivera, and ask to move your
cleaning to the afternoon. Each calendar tool call the platform makes shows up in the app log
as `POST /mcp-calendar` and a `mcp tools/call ...` line. The server seeds Dana's cleaning (10:00) and Sam Okafor's checkup
(11:00) on the next business day each time it starts, and it forgets every change when it
stops.

Without a phone, play the platform's part with curl:

```bash
T="Authorization: Bearer $(grep ^MCP_TOKEN= .env | cut -d= -f2)"
curl -s localhost:3000/mcp-calendar -H "$T" -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | jq '.result.tools[].name'
curl -s localhost:3000/mcp-calendar -H "$T" -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"find_my_meetings","arguments":{"attendee":"Dana Rivera"}}}'
swaig-test app.py --dump-swml --raw | jq '.sections.main[-1].ai.SWAIG.mcp_servers'
pytest -q                          # SWML, discovery as the platform does it, same-app route, book/move, scopes, guard
```

## Deploy

```bash
docker compose up --build          # one service on :3000: SWML at /, calendar MCP at /mcp-calendar
```

The service reads `.env`. Publish it behind HTTPS (for example `https://agent.example.com/`),
set `PUBLIC_URL` to that, and point the number at `https://USER:PASS@agent.example.com/`.
The platform then reaches the calendar at `https://agent.example.com/mcp-calendar` with the
bearer token. That route uses token auth, not basic auth. To run the reference server on its
own host instead, run `python mcp_calendar.py` (it serves `POST /mcp` on `MCP_PORT`) and set
`MCP_URL` to its public URL. The reference server keeps everything in
memory, so a restart resets the calendar. For anything real, use your own calendar MCP server.

## What to change first

Open `config.py`:

- `MCP_URL` and `MCP_TOKEN` (set them in `.env`): point at your real calendar MCP server, and
  ask its owner for a token scoped to what a phone caller should be able to do. Unset
  `MCP_URL` means the built-in reference calendar at `MCP_CALENDAR_PATH`.
- `GET_TODAY_MAX_CALLS`: how many `get_today` calls one call gets before the agent says the
  calendar is unavailable.
- `MCP_SCOPES`, `OFFICE_HOURS`, `SLOT_MINUTES`, `SEED_MEETINGS`: the reference server's scopes and
  booking rules, if you keep it.
- `BUSINESS_NAME` and `VOICE`, and the "Rules" section in `app.py` if your MCP server's tool
  names differ.
