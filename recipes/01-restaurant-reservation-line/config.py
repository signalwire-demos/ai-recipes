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
RESTAURANT_NAME = "Lantern & Vine"
VOICE = "rime.spore"                     # any SignalWire TTS voice id
LANGUAGE_CODE = "en-US"

# Seating hours per weekday, 24-hour "HH:MM". None = closed. The last seating is
# LAST_SEATING_MINUTES before close.
OPENING_HOURS = {
    "monday": None,
    "tuesday": {"open": "17:00", "close": "22:00"},
    "wednesday": {"open": "17:00", "close": "22:00"},
    "thursday": {"open": "17:00", "close": "22:00"},
    "friday": {"open": "17:00", "close": "23:00"},
    "saturday": {"open": "12:00", "close": "23:00"},
    "sunday": {"open": "12:00", "close": "21:00"},
}
LAST_SEATING_MINUTES = 60
MAX_PARTY = 8                            # bigger groups are asked to call the events team
BOOKING_WINDOW_DAYS = 60                 # how far ahead a table can be booked

# The reservation sink: a JSON list on disk. Swap save_booking() in app.py for your
# booking system's API. data/runtime/ is gitignored.
RESERVATIONS_FILE = Path(os.environ.get("RESERVATIONS_FILE", HERE / "data" / "runtime" / "reservations.json"))

# --- Server ---------------------------------------------------------------
PORT = int(os.environ.get("PORT", "3000"))
ROUTE = "/"
