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
STORE_NAME = "Example Outfitters"
VOICE = "rime.spore"                     # any SignalWire TTS voice id
LANGUAGE_CODE = "en-US"
ORDERS_FILE = HERE / "data" / "orders.json"                 # mock CRM (crm.py)
CREDITS_FILE = HERE / "data" / "runtime" / "credits.jsonl"  # where auto-credits are written
MAX_VERIFY_ATTEMPTS = 3                  # failed verifications before the escalate step

# The curated slice: order fields the model may see, with the label used in the step text.
# Everything else in the record (risk_flag, prior_refunds, internal_notes, ...) stays hidden.
CURATED_FIELDS = {"status": "Status", "eta": "Estimated delivery", "items_text": "Items"}

# Refund rule, read only inside request_refund. Never put these in a prompt.
AUTO_CREDIT_LIMIT = 50.00                # orders at or under this total can be auto-credited
MAX_PRIOR_REFUNDS = 2                    # more prior refunds than this goes to a person
REFUNDABLE_STATUSES = ["delivered", "delayed"]

# Escalation: a phone or SIP address for a human. Empty = a polite goodbye and hang up.
ESCALATION_NUMBER = os.environ.get("ESCALATION_NUMBER", "")
FROM_NUMBER = os.environ.get("FROM_NUMBER") or None   # caller ID on the transfer leg

# --- Server ---------------------------------------------------------------
PORT = int(os.environ.get("PORT", "3000"))
ROUTE = "/"
