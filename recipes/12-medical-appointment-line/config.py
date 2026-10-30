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
CLINIC_NAME = "Example Family Clinic"

# The disclosure is spoken word for word in the consent step. Bump the version every time
# the wording changes: the version lands in every audit record, so you can prove which
# wording each caller heard.
DISCLOSURE_VERSION = "2026-10-v1"
DISCLOSURE_TEXT = (
    f"Before we start: this call may be recorded so {CLINIC_NAME} can confirm your booking "
    "and improve our service. Do you agree to the call being recorded?"
)

VOICE = "rime.spore"                         # any SignalWire TTS voice id
LANGUAGE_CODE = "en-US"
SLOTS_FILE = HERE / "data" / "slots.json"    # swap for your scheduling backend
AUDIT_FILE = Path(os.environ.get("AUDIT_FILE", HERE / "data" / "audit.jsonl"))
RECORDING_FORMAT = "mp3"                     # wav | mp3 | mp4

# --- Server ---------------------------------------------------------------
PORT = int(os.environ.get("PORT", "3000"))
ROUTE = "/"
