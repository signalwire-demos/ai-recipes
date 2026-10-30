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
BUSINESS_NAME = "Example Family Clinic"
VOICE = "rime.spore"
LANGUAGE_CODE = "en-US"

# The confirmation text. All three fields are filled by code, never by the model.
SMS_TEMPLATE = (
    "{business}: you're booked for {date} at {time}. "
    "Confirmation {confirmation}. Reply CHANGE and we'll call you to reschedule."
)
# An inbound text containing any of these words triggers a call back into the agent.
ESCALATE_WORDS = ("change", "reschedule", "move", "call")

SLOTS_FILE = HERE / "data" / "slots.json"        # open appointment slots (mock calendar)
BOOKINGS_FILE = Path(os.environ.get("BOOKINGS_FILE", HERE / "data" / "bookings.json"))
CONFIRMATION_PREFIX = "AC-"

# --- Numbers (roles from NUMBERS.md; values come from .env) ---------------
SMS_FROM = os.environ.get("SMS_FROM") or os.environ.get("SMS_1", "")         # 10DLC-registered sender
DIAL_FROM = os.environ.get("DIAL_FROM") or os.environ.get("OUTBOUND_1", "")  # caller ID for the call back

# Optional: the Space's Signing Key. When set, /sms rejects unsigned requests.
SIGNING_KEY = os.environ.get("SIGNALWIRE_SIGNING_KEY", "")

# --- Server ---------------------------------------------------------------
PORT = int(os.environ.get("PORT", "3000"))
ROUTE = "/"
SMS_ROUTE = "/sms"
PUBLIC_URL = os.environ.get("PUBLIC_URL", "")
