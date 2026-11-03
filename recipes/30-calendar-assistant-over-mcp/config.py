"""Every knob for this recipe. "What to change first" in the README points here.

Environment loading: values come from the process environment, then this recipe's
.env, then the monorepo root .env (nearest file wins, existing env vars are never
overwritten). No python-dotenv dependency.
"""
import os
import secrets
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _load_env_files() -> None:
    for env_file in (HERE / ".env", HERE.parent.parent / ".env"):
        if not env_file.is_file():
            continue
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip("'\""))


_load_env_files()

# .env.example ships SWML_BASIC_AUTH_PASSWORD=change-me. Anyone who has read this repo knows it,
# and it guards the SWML, every tool and every route here, so never serve with it.
if os.environ.get("SWML_BASIC_AUTH_PASSWORD", "").strip() == "change-me":
    raise SystemExit("SWML_BASIC_AUTH_PASSWORD is still the .env.example placeholder: "
                     "set a long random value (python -c 'import secrets; print(secrets.token_urlsafe(24))').")

# The SDK builds its webhook URLs from SWML_PROXY_URL_BASE. Recipes use PUBLIC_URL.
if os.environ.get("PUBLIC_URL") and not os.environ.get("SWML_PROXY_URL_BASE"):
    os.environ["SWML_PROXY_URL_BASE"] = os.environ["PUBLIC_URL"].rstrip("/")

# --- Recipe knobs: change these first -------------------------------------
BUSINESS_NAME = "Example Dental"
VOICE = "rime.spore"
LANGUAGE_CODE = "en-US"

# --- Server ---------------------------------------------------------------
PORT = int(os.environ.get("PORT", "3000"))
ROUTE = "/"

# --- The calendar MCP server the agent uses ---------------------------------
# SignalWire's platform (not this process) connects to MCP_URL at the start of each call,
# lists its tools and calls them, so on a live call MCP_URL must be a public HTTPS URL.
# Default: app.py serves the reference calendar (mcp_calendar.py) itself at
# MCP_CALENDAR_PATH, so the one PUBLIC_URL tunnel covers the SWML and the MCP server.
# To use an external calendar MCP server instead, set MCP_URL (and its MCP_TOKEN) in .env;
# the built-in one is then switched off unless SERVE_REFERENCE_CALENDAR=true.
MCP_CALENDAR_PATH = "/mcp-calendar"
_BASE_URL = (os.environ.get("PUBLIC_URL") or f"http://localhost:{PORT}").rstrip("/")
MCP_URL = os.environ.get("MCP_URL") or f"{_BASE_URL}{MCP_CALENDAR_PATH}"
MCP_TOKEN = os.environ.get("MCP_TOKEN", "")
# Tokens that are never accepted: blank, and the placeholder older copies of .env.example shipped.
PLACEHOLDER_TOKENS = {"", "change-me-calendar-token"}
SERVE_REFERENCE_CALENDAR = os.environ.get(
    "SERVE_REFERENCE_CALENDAR", "false" if os.environ.get("MCP_URL") else "true").lower() == "true"
MCP_PORT = int(os.environ.get("MCP_PORT", PORT + 1))   # only for `python mcp_calendar.py` on its own
# Caller binding. Each call's SWML carries the caller's number and an HMAC of it under this key
# in its MCP headers; the calendar trusts only that, never a name the model passes. Random per
# process by default (fine when app.py serves the calendar). A separate calendar process
# (`python mcp_calendar.py`) needs the same MCP_CALLER_KEY as the agent.
MCP_CALLER_KEY = os.environ.get("MCP_CALLER_KEY") or secrets.token_hex(32)

# get_today guard. If the MCP tools never reached the call (wrong MCP_URL, server down),
# get_today is the model's only tool and it tends to call it over and over. After this many
# calls in one call, get_today says the calendar is unavailable and switches itself off.
GET_TODAY_MAX_CALLS = 3

# --- Reference calendar server (mcp_calendar.py) only ------------------------
# Each bearer token gets a tool scope. The voice agent's token can find, book and move;
# cancelling needs the admin token, so the phone agent never even sees cancel_meeting.
MCP_ADMIN_TOKEN = os.environ.get("MCP_ADMIN_TOKEN", "")
MCP_SCOPES = {
    MCP_TOKEN: ["find_free_slots", "find_my_meetings", "book_meeting", "move_meeting"],
    MCP_ADMIN_TOKEN: ["find_free_slots", "find_my_meetings", "book_meeting", "move_meeting", "cancel_meeting"],
}
OFFICE_HOURS = (9, 17)       # meetings may start 09:00 to 16:30
SLOT_MINUTES = 30
SEED_MEETINGS = [            # demo data, placed on the next business day when the server starts
    {"title": "Cleaning", "attendee": "Dana Rivera", "phone": "+15550142", "time": "10:00"},
    {"title": "Checkup", "attendee": "Sam Okafor", "phone": "+15550143", "time": "11:00"},
]   # phone: the caller ID that may list and move the meeting. Put your own phone here to test.
