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
COMPANY_NAME = "Example Recovery Services"
VOICE = "rime.spore"                     # any SignalWire TTS voice id
LANGUAGE_CODE = "en-US"
DEBTS_FILE = HERE / "data" / "debts.json"                     # mock ledger (ledger.py)
OUTCOMES_FILE = HERE / "data" / "runtime" / "outcomes.jsonl"  # plans, hardship picks, escalations

# Policy thresholds. Read only by policy.py; never put them in a prompt or in global_data.
MIN_MONTHLY_PAYMENT = 75.00   # dollars; lower offers are refused
MAX_TERM_MONTHS = 18          # longest plan the policy accepts
MAX_REFUSALS = 3              # refused plans or declines before the call moves to hardship_options

# Hardship options offered once negotiation stops. Keys are what the model passes.
HARDSHIP_OFFERS = {
    "payment_pause": "Pause collection activity while the caller gets back on their feet",
    "hardship_review": "Send a hardship application for a reduced settlement",
    "counselor_referral": "Refer the caller to a free nonprofit credit counselor",
}

# Escalation: a phone or SIP address for a human agent. Empty = a polite goodbye and hang up.
AGENT_NUMBER = os.environ.get("AGENT_NUMBER", "")
FROM_NUMBER = os.environ.get("FROM_NUMBER") or None   # caller ID on the transfer leg

# --- Server ---------------------------------------------------------------
PORT = int(os.environ.get("PORT", "3000"))
ROUTE = "/"
