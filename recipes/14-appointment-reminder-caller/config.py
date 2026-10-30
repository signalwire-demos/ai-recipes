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
BUSINESS_NAME = "Example Family Dental"
CALLBACK_NUMBER = "555-0199"             # spoken to a wrong person instead of any detail
VOICE = "rime.spore"                     # any SignalWire TTS voice id
LANGUAGE_CODE = "en-US"

# Appointments source: who to call, their time zone, and whether they consented.
APPOINTMENTS_FILE = HERE / "data" / "appointments.csv"
DNC_FILE = HERE / "data" / "dnc.txt"     # do-not-call list, one E.164 number per line

# Calling hours, in each contact's local time. 08:00-21:00 is the TCPA default.
CALL_WINDOW = os.environ.get("CALL_WINDOW", "08:00-21:00")

# Calendar backend: ics (local file, default) or google (TODO, see README).
CALENDAR_BACKEND = os.environ.get("CALENDAR_BACKEND", "ics")
CALENDAR_FILE = HERE / "data" / "calendar.ics"

# Reschedule rules: weekdays only, slots must start within these local hours.
OPEN_WEEKDAYS = {0, 1, 2, 3, 4}          # Monday=0
OPEN_HOURS = (9, 17)                     # first and last-plus-one start hour

# --- Outbound dialing -------------------------------------------------------
FROM_NUMBER = os.environ.get("FROM_NUMBER") or os.environ.get("OUTBOUND_1", "")
PUBLIC_URL = os.environ.get("PUBLIC_URL", "").rstrip("/")
BASIC_AUTH = (os.environ.get("SWML_BASIC_AUTH_USER", ""), os.environ.get("SWML_BASIC_AUTH_PASSWORD", ""))

# --- Server ---------------------------------------------------------------
PORT = int(os.environ.get("PORT", "3000"))
ROUTE = "/"
