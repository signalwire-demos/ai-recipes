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
HOTEL_NAME = "Example Harbor Hotel"
VOICE = "rime.spore"                       # voice channel only; ignored over text
LANGUAGE_CODE = "en-US"
# The tool set. Only these service requests can be logged, on any channel.
SERVICES = ("extra towels", "housekeeping", "late checkout", "wake-up call", "room service menu")

GUESTS_FILE = HERE / "data" / "guests.json"          # mock property-management system
AMENITIES_FILE = HERE / "data" / "amenities.json"
REQUESTS_FILE = Path(os.environ.get("REQUESTS_FILE", HERE / "data" / "requests.json"))

# --- Channels ---------------------------------------------------------------
PUBLIC_URL = os.environ.get("PUBLIC_URL", "")
SMS_ROUTE = "/sms"
# The URL the AI Chat service fetches this agent's SWML from. Empty: built from
# PUBLIC_URL plus the basic auth credentials, i.e. the same URL a voice call uses.
CHAT_CONFIG_URL = os.environ.get("CHAT_CONFIG_URL", "")
# AI Chat API endpoint. AIChatClient builds https://{SIGNALWIRE_SPACE}.signalwire.com/...
# from a bare space name, but .env holds the full host (example.signalwire.com), so build it here.
_space = os.environ.get("SIGNALWIRE_SPACE", "")
CHAT_API_URL = os.environ.get("CHAT_API_URL") or (
    f"https://{_space if '.' in _space else _space + '.signalwire.com'}/api/ai/chat" if _space else ""
)
SMS_CONVERSATION_PREFIX = "sms."                     # conversation id = prefix + sender digits
SIGNING_KEY = os.environ.get("SIGNALWIRE_SIGNING_KEY", "")  # optional: /sms rejects unsigned requests

# --- Server ---------------------------------------------------------------
PORT = int(os.environ.get("PORT", "3000"))
ROUTE = "/"
