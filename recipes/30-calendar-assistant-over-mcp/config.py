"""Every knob for this recipe. "What to change first" in the README points here.

Environment loading: values come from the process environment, then this recipe's
.env, then the monorepo root .env (nearest file wins, existing env vars are never
overwritten). No python-dotenv dependency.
"""
import os
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
# lists its tools and calls them. On a live call MCP_URL must be a public HTTPS URL.
MCP_PORT = int(os.environ.get("MCP_PORT", PORT + 1))
MCP_URL = os.environ.get("MCP_URL") or f"http://localhost:{MCP_PORT}/mcp"
MCP_TOKEN = os.environ.get("MCP_TOKEN", "")

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
    {"title": "Cleaning", "attendee": "Dana Rivera", "time": "10:00"},
    {"title": "Checkup", "attendee": "Sam Okafor", "time": "11:00"},
]
