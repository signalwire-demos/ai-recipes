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
BUSINESS_NAME = "Example Fiber"
ACCOUNTS_FILE = HERE / "data" / "accounts.json"   # swap for your billing/outage system

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
