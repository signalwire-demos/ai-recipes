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
BUSINESS_NAME = "Example Cloud Phones"
VOICE = "rime.spore"                     # any SignalWire TTS voice id
LANGUAGE_CODE = "en-US"
# Live call 605c901d on the platform default (gpt-4o-mini): the model said "I will record that"
# four times and called no record_* tool, so the lead landed with every field missing.
MODEL = os.environ.get("LEAD_MODEL", "gpt-4.1-mini")   # set_prompt_llm_params(model=...)

# Qualification fields. Each tool writes exactly one of these global_data keys.
FIELDS = ["budget_usd", "timeline_months", "is_decision_maker", "need"]
NEEDS = ["contact_center", "sales_dialing", "appointment_booking", "after_hours", "other"]
MAX_TIMELINE_MONTHS = 24                 # "just researching" is recorded as this

# Scoring rule: one point per condition met, then the tier by total points.
SCORE_RULES = {
    "budget_usd": lambda v: v >= 10_000,
    "timeline_months": lambda v: v <= 3,
    "is_decision_maker": lambda v: v is True,
    "need": lambda v: v in ("contact_center", "sales_dialing"),
}
TIERS = [(4, "hot"), (2, "warm"), (0, "cold")]   # (minimum points, tier), highest first

# --- CRM sink -------------------------------------------------------------
CRM_SINK = os.environ.get("CRM_SINK", "file")    # file | hubspot
LEADS_FILE = HERE / "data" / "leads.jsonl"
HUBSPOT_TOKEN = os.environ.get("HUBSPOT_TOKEN", "")
HUBSPOT_URL = "https://api.hubapi.com/crm/v3/objects/contacts"

# --- Server ---------------------------------------------------------------
PORT = int(os.environ.get("PORT", "3000"))
ROUTE = "/"
