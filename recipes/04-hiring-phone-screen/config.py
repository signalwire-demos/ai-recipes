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
COMPANY_NAME = "Example Logistics"
ROLE_TITLE = "warehouse shift lead"
VOICE = "rime.spore"                     # any SignalWire TTS voice id
LANGUAGE_CODE = "en-US"

# The screen, in order. Each entry is passed straight to add_gather_question().
# type: string | integer | number | boolean. confirm=True makes the agent read the
# answer back and get a yes before it is saved (use it on answers that are easy to mishear).
QUESTIONS = [
    {"key": "work_authorized", "type": "boolean", "confirm": True,
     "question": "Are you legally authorized to work in the United States?"},
    {"key": "years_experience", "type": "integer",
     "question": "How many years of warehouse or logistics experience do you have?"},
    {"key": "earliest_start", "type": "string", "confirm": True,
     "question": "What is the earliest date you could start?"},
    {"key": "salary_range", "type": "string",
     "question": "What hourly pay range are you looking for?"},
    {"key": "why_this_role", "type": "string",
     "question": "In a sentence or two, why are you interested in this role?"},
]
CANDIDATE_ID_PATTERN = r"^[A-Za-z0-9-]{1,32}$"   # ?candidate=<id> on the dial URL
OUTPUT_KEY = "screen"                       # answers land in global_data[OUTPUT_KEY]
CANDIDATES_DIR = HERE / "data" / "candidates"  # one <candidate_id>.json per screen

# --- Outbound kickoff (call_candidate.py) ----------------------------------
FROM_NUMBER = os.environ.get("FROM_NUMBER") or os.environ.get("OUTBOUND_1", "")
CANDIDATE_NUMBER = os.environ.get("CANDIDATE_NUMBER", "")

# --- Server ---------------------------------------------------------------
PORT = int(os.environ.get("PORT", "3000"))
ROUTE = "/"
