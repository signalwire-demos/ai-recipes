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
BUSINESS_NAME = "Example Plumbing"
OWNER_NAME = "the owner"
VOICE = "rime.spore"                         # any SignalWire TTS voice id
LANGUAGE_CODE = "en-US"

# Business hours, in the office time zone. HOURS: "mon-fri 09:00-17:00; sat 10:00-14:00".
TZ = os.environ.get("TZ") or "America/Chicago"     # IANA zone of the office
HOURS = os.environ.get("HOURS", "mon-fri 08:00-17:00; sat 09:00-12:00")
HOLIDAYS_FILE = Path(os.environ.get("HOLIDAYS_FILE") or HERE / "data" / "holidays.json")   # list of "YYYY-MM-DD" dates the office is closed

# Numbers. In the demo pool: HUMAN_LEG = office, HUMAN_LEG_2 = on-call, OUTBOUND_2 = caller ID
# on the forwarded leg, SMS_1 = SMS sender. Put a real phone in OFFICE_NUMBER / ONCALL_NUMBER /
# OWNER_NUMBER to hear the forward or get the text yourself.
OFFICE_NUMBER = os.environ.get("OFFICE_NUMBER") or os.environ.get("HUMAN_LEG", "+15550101")
ONCALL_NUMBER = os.environ.get("ONCALL_NUMBER") or os.environ.get("HUMAN_LEG_2", "+15550102")
OWNER_NUMBER = os.environ.get("OWNER_NUMBER") or OFFICE_NUMBER      # gets the after-hours SMS
FROM_NUMBER = os.environ.get("FROM_NUMBER") or os.environ.get("OUTBOUND_2", "+15550103")
SMS_FROM = os.environ.get("SMS_FROM") or os.environ.get("SMS_1", "+15550104")
CONNECT_TIMEOUT = 25                         # seconds to ring the office or on-call line

# The urgency rule: a message containing any of these is forwarded to on-call, not texted.
URGENT_KEYWORDS = ["emergency", "flood", "flooding", "burst", "leak", "leaking", "gas",
                   "sewage", "backing up", "no water", "no heat"]

# --- Server ---------------------------------------------------------------
PORT = int(os.environ.get("PORT", "3000"))
ROUTE = "/"
