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
COMPANY_NAME = "Parcel Point"
VOICE = "rime.spore"                     # any SignalWire TTS voice id
LANGUAGE_CODE = "en-US"

# The tracking API the DataMap calls. SignalWire's servers make this request, not
# this app. ${enc:args.tracking_number} is filled in (URL-encoded) by the platform.
# Default: the static mock feed in data/mock-api/, served by GitHub raw (works once
# this recipe is on main in the public repo).
MOCK_TRACKING_URL = (
    "https://raw.githubusercontent.com/signalwire-demos/ai-recipes/main/recipes/"
    "05-package-tracking-line/data/mock-api/${enc:args.tracking_number}.json"
)
TRACKING_URL = os.environ.get("TRACKING_API_URL") or MOCK_TRACKING_URL
# Optional bearer token for a real carrier API. It goes into the webhook header of the
# SWAIG function definition, never into the prompt or global_data.
TRACKING_API_KEY = os.environ.get("TRACKING_API_KEY", "")

# What the caller hears. The platform reads a webhook's JSON response from the ROOT:
# ${status} is the response's "status" field (not ${response.status}), and the call's
# arguments are under input there (${input.args.tracking_number}).
OUTPUT_TEMPLATE = (
    "Package ${input.args.tracking_number} is ${status}. ${detail} "
    "The last scan was in ${last_location} on ${last_scan}."
)
# Used when the request fails (404, timeout, an "error" key). This one reads the call
# data, so the argument is ${args.tracking_number}.
NOT_FOUND_TEMPLATE = (
    "I couldn't find tracking number ${args.tracking_number}. "
    "Ask the caller to read it again, one digit at a time."
)

# --- Server ---------------------------------------------------------------
PORT = int(os.environ.get("PORT", "3000"))
ROUTE = "/"
