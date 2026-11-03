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

# .env.example ships SWML_BASIC_AUTH_PASSWORD=change-me. Anyone who has read this repo knows it,
# and it guards the SWML, every tool and every route here, so never serve with it.
if os.environ.get("SWML_BASIC_AUTH_PASSWORD", "").strip() == "change-me":
    raise SystemExit("SWML_BASIC_AUTH_PASSWORD is still the .env.example placeholder: "
                     "set a long random value (python -c 'import secrets; print(secrets.token_urlsafe(24))').")

# The SDK builds its webhook URLs from SWML_PROXY_URL_BASE. Recipes use PUBLIC_URL.
if os.environ.get("PUBLIC_URL") and not os.environ.get("SWML_PROXY_URL_BASE"):
    os.environ["SWML_PROXY_URL_BASE"] = os.environ["PUBLIC_URL"].rstrip("/")

# --- Recipe knobs: change these first -------------------------------------
BUSINESS_NAME = "Acme Fiber"
VOICE = "rime.spore"
LANGUAGE_CODE = "en-US"

# Which tools MCP clients (Claude Desktop, Claude Code, ...) can list and call.
# Everything else stays voice-only. transfer_to_human moves a live call, which
# means nothing to a chat client, so it is not on this list.
MCP_TOOLS = ["lookup_customer", "book_callback"]
# /mcp's own credential: clients send "Authorization: Bearer <MCP_TOKEN>". The SWML basic auth
# is not accepted there. Blank: /mcp answers 401 to everything.
MCP_TOKEN = os.environ.get("MCP_TOKEN", "")

CUSTOMERS_FILE = HERE / "data" / "customers.json"    # mock CRM; swap for yours
CALLBACKS_FILE = Path(os.environ.get("CALLBACKS_FILE", HERE / "data" / "runtime" / "callbacks.jsonl"))
CALLBACK_HOURS = (9, 17)          # local hours a callback may start: 09:00 to 16:59
CALLBACK_DAYS = range(0, 5)       # Monday..Friday

# Voice-only transfer target. Put a real phone in HUMAN_NUMBER for a live test.
HUMAN_NUMBER = os.environ.get("HUMAN_NUMBER") or os.environ.get("HUMAN_LEG") or "+15555550199"

# --- Server ---------------------------------------------------------------
PORT = int(os.environ.get("PORT", "3000"))
ROUTE = "/"
