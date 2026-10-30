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
UTILITY_NAME = "Example Power & Water"
VOICE = "rime.spore"                         # any SignalWire TTS voice id
LANGUAGE_CODE = "en-US"
ACCOUNTS_FILE = HERE / "data" / "accounts.json"  # swap for your billing system

# Payment connector. Default: the mock connector this app serves at /pay (same tunnel).
# Swap in your processor's connector URL here.
PUBLIC_URL = os.environ.get("PUBLIC_URL", "http://localhost:3000").rstrip("/")
PAY_CONNECTOR_URL = os.environ.get("PAY_CONNECTOR_URL", "")   # empty = PUBLIC_URL/pay with basic auth
PAY_STATUS_URL = os.environ.get("PAY_STATUS_URL", "")         # empty = PUBLIC_URL/pay/status
PAY_MAX_ATTEMPTS = 2
PAY_SECURITY_CODE = True
PAY_POSTAL_CODE = True
PAY_CARD_TYPES = "visa mastercard amex"
RECORDING_CONTROL_ID = "main"

# Mock connector: last four digits of the card -> result. Never real cards.
# None = approve; otherwise (error_code, error_message) is returned with HTTP 402.
MOCK_CARDS = {
    "4242": None,                                                     # 4242 4242 4242 4242
    "0002": ("card_declined", "The card was declined"),                # 4000 0000 0000 0002
    "9995": ("insufficient_funds", "Card has insufficient funds"),     # 4000 0000 0000 9995
}

# --- Server ---------------------------------------------------------------
PORT = int(os.environ.get("PORT", "3000"))
ROUTE = "/"
