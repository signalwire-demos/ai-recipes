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
BRAND_NAME = "Example Dental"
SURVEY_NAME = "Patient Visit Survey"
VOICE = "rime.spore"                     # any SignalWire TTS voice id
LANGUAGE_CODE = "en-US"
INTRODUCTION = (f"Hi, this is {BRAND_NAME} calling about your recent visit. "
                "Do you have one minute for four quick questions?")
CONCLUSION = "Thank you, that's everything. Have a great day."

# SurveyAgent question format. type: rating | multiple_choice | yes_no | open_ended.
QUESTIONS = [
    {"id": "likely_to_recommend", "type": "rating", "scale": 10,
     "text": f"On a scale of 1 to 10, how likely are you to recommend {BRAND_NAME} to a friend?"},
    {"id": "best_part", "type": "multiple_choice",
     "options": ["scheduling", "staff", "price", "wait time"],
     "text": "What did you like most: scheduling, staff, price, or wait time?"},
    {"id": "issue_resolved", "type": "yes_no",
     "text": "Was the reason for your visit taken care of?"},
    {"id": "comments", "type": "open_ended", "required": False,
     "text": "Is there anything else you'd like us to know?"},
]

# Scoring rule (score_results.py): NPS-style on one rating question.
NPS_QUESTION = "likely_to_recommend"
PROMOTER_MIN = 9      # ratings >= this are promoters
DETRACTOR_MAX = 6     # ratings <= this are detractors; the rest are passives

RESULTS_FILE = HERE / "data" / "results.jsonl"   # one row per validated answer

# --- Outbound kickoff (call_customer.py) ------------------------------------
FROM_NUMBER = os.environ.get("FROM_NUMBER") or os.environ.get("OUTBOUND_1", "")
CUSTOMER_NUMBER = os.environ.get("CUSTOMER_NUMBER", "")
CUSTOMER_ID_PATTERN = r"^[A-Za-z0-9-]{1,32}$"   # ?customer=<id> on the dial URL

# --- Server ---------------------------------------------------------------
PORT = int(os.environ.get("PORT", "3000"))
ROUTE = "/"
