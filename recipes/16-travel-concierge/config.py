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
AGENCY_NAME = "Example Travel"
CONCIERGE_VOICE = "rime.spore"               # any SignalWire TTS voice id
BOOKING_VOICE = "rime.spore"                  # use a different voice to make the handoff audible
LANGUAGE_CODE = "en-US"
DESTINATIONS_FILE = HERE / "data" / "destinations.json"   # mock inventory: swap for your GDS / API
MAX_TRAVELERS = 6

# Handoff store: the concierge's handler writes a summary + trip state here, keyed by an opaque
# token that travels in the transfer URL (?h=...). The booking agent reads it back.
HANDOFF_FILE = Path(os.environ.get("HANDOFF_FILE") or HERE / "data" / "runtime" / "handoffs.json")
HANDOFF_TTL_SECS = 30 * 60                   # records older than this are ignored and purged
BOOKINGS_FILE = HERE / "data" / "runtime" / "bookings.jsonl"

# --- Server ---------------------------------------------------------------
PUBLIC_URL = os.environ.get("PUBLIC_URL", "http://localhost:3000").rstrip("/")
PORT = int(os.environ.get("PORT", "3000"))
CONCIERGE_ROUTE = "/concierge"
BOOKING_ROUTE = "/booking"
