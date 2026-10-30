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
BANK_NAME = "Example Community Bank"
VOICE = "rime.spore"                     # any SignalWire TTS voice id
LANGUAGE_CODE = "en-US"
ACCOUNTS_FILE = HERE / "data" / "accounts.json"            # mock core banking (crm.py)
DISPUTES_FILE = HERE / "data" / "runtime" / "disputes.jsonl"  # where open_dispute writes
MAX_VERIFY_ATTEMPTS = 3                  # failed verifications before the escalate step
MAX_TRANSACTIONS = 5                     # most transactions list_transactions will read out

# Escalation: a phone or SIP address for a human. Empty = a polite goodbye and hang up.
ESCALATION_NUMBER = os.environ.get("ESCALATION_NUMBER", "")
FROM_NUMBER = os.environ.get("FROM_NUMBER") or None   # caller ID on the transfer leg

# --- Server ---------------------------------------------------------------
PORT = int(os.environ.get("PORT", "3000"))
ROUTE = "/"
