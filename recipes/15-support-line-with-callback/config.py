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
COMPANY_NAME = "Example Broadband"
VOICE = "rime.spore"                     # any SignalWire TTS voice id
LANGUAGE_CODE = "en-US"

# The human support line. Default: the demo pool's HUMAN_LEG role (nobody answers it;
# put a real phone in HUMAN_NUMBER for a live test).
HUMAN_NUMBER = os.environ.get("HUMAN_NUMBER") or os.environ.get("HUMAN_LEG", "")
# Caller ID for both outbound legs: the human transfer and the worker's return call.
FROM_NUMBER = os.environ.get("FROM_NUMBER") or os.environ.get("OUTBOUND_2", "")

# Availability: the mock rota in data/rota.json, read by rota.py. Point rota.human_available()
# at your ACD instead. AVAILABILITY=free|busy forces an answer for demos and live tests.
ROTA_FILE = HERE / "data" / "rota.json"
AVAILABILITY = os.environ.get("AVAILABILITY", "rota")

# --- Callback store and worker --------------------------------------------
CALLBACKS_FILE = Path(os.environ.get("CALLBACKS_FILE") or HERE / "data" / "runtime" / "callbacks.json")
WORKER_INTERVAL = int(os.environ.get("WORKER_INTERVAL", "30"))  # seconds between sweeps
CALLBACK_ROUTE = "/callback"             # the return call's agent; the worker dials into it
# Toll-fraud guard: the caller ID can be spoofed, so only these numbers are ever called back.
# E.164 prefixes, comma-separated (default: NANP). Inside +1, the premium 900 area code, the 976
# exchange and the Caribbean area codes that bill as international are always refused.
CALLBACK_ALLOWED_PREFIXES = [p.strip() for p in os.environ.get("CALLBACK_ALLOWED_PREFIXES", "+1").split(",") if p.strip()]
BLOCKED_NPAS = set("900 242 246 264 268 284 345 441 473 649 658 664 721 758 767 784 809 829 849 868 869 876".split())
MAX_PENDING_CALLBACKS = int(os.environ.get("MAX_PENDING_CALLBACKS", "50"))   # queue cap; one per number

# --- Server ---------------------------------------------------------------
PORT = int(os.environ.get("PORT", "3000"))
ROUTE = "/"
PUBLIC_URL = os.environ.get("PUBLIC_URL", "").rstrip("/")
