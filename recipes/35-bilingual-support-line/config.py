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

# .env.example ships SWML_BASIC_AUTH_PASSWORD=change-me. Anyone who has read this repo knows it,
# and it guards the SWML, every tool and every route here, so never serve with it.
if os.environ.get("SWML_BASIC_AUTH_PASSWORD", "").strip() == "change-me":
    raise SystemExit("SWML_BASIC_AUTH_PASSWORD is still the .env.example placeholder: "
                     "set a long random value (python -c 'import secrets; print(secrets.token_urlsafe(24))').")

# The SDK builds its webhook URLs from SWML_PROXY_URL_BASE. Recipes use PUBLIC_URL.
if os.environ.get("PUBLIC_URL") and not os.environ.get("SWML_PROXY_URL_BASE"):
    os.environ["SWML_PROXY_URL_BASE"] = os.environ["PUBLIC_URL"].rstrip("/")

# --- Recipe knobs: change these first -------------------------------------
BUSINESS_NAME = "Example Fiber"
ACCOUNTS_FILE = HERE / "data" / "accounts.json"   # swap for your billing/outage system
# Failed lookup_account attempts, counted per account, caller ID and call across calls (lockout.py).
# After MAX_LOOKUP_FAILURES that key is locked out until LOOKUP_LOCKOUT_SECS after the last failure.
MAX_LOOKUP_FAILURES = 3
LOOKUP_LOCKOUT_SECS = int(os.environ.get("LOOKUP_LOCKOUT_SECS", "900"))
VERIFIED_SESSION_SECS = 3600   # how long a verified call keeps access to the account tools

# One entry per language = one add_language() call. The first entry is the opening
# language. Add a language by appending one dict; nothing else changes.
LANGUAGES = [
    {
        "name": "English",
        "code": "en-US",
        "voice": "gcloud.en-US-Neural2-F",
        "speech_fillers": ["Let me see...", "Okay..."],
        "function_fillers": ["One moment while I check.", "Let me look that up."],
        "step_fillers": ["Alright.", "Okay, one second."],      # internal next_step filler
    },
    {
        "name": "Spanish",
        "code": "es",
        "voice": "gcloud.es-US-Neural2-A",
        "speech_fillers": ["A ver...", "Bueno..."],
        "function_fillers": ["Un momento, lo reviso.", "Déjeme buscarlo."],
        "step_fillers": ["Muy bien.", "Un segundo."],
    },
]

# --- Server ---------------------------------------------------------------
PORT = int(os.environ.get("PORT", "3000"))
ROUTE = "/"
