"""Every knob for this recipe. "What to change first" in the README points here.

Environment loading: values come from the process environment, then this recipe's
.env, then the monorepo root .env (nearest file wins, existing env vars are never
overwritten). No python-dotenv dependency.
"""
import os
from pathlib import Path

from slots import matches, one_of, parse_date

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
ORG_NAME = "Example District"            # who the caller is reporting the absence to
VOICE = "rime.spore"                     # any SignalWire TTS voice id
LANGUAGE_CODE = "en-US"
# The model that runs the call. On live calls 5b015855 and d8c935db the platform default
# (gpt-4o-mini) skipped record_slots on most turns and kept re-asking for the ID.
MODEL = os.environ.get("ABSENCE_MODEL", "gpt-4.1-mini")

# The grammar: slot name -> (what the model is told it means, validator).
# A validator takes the caller's words (lowercased) and returns (value, None) or
# (None, a question to ask). Add, remove or rename slots here; the tool schema,
# the missing-slot gate and the readback all follow this dict.
SLOTS = {
    "name": ("First and last name of the person who will be absent, as the caller said it. "
             "Ask if not provided.",
             matches(r"(?!.*\b(my|our|his|her|son|daughter|child|kid|husband|wife|he|she)\b)"
                     r"[a-z][a-z.'-]*( [a-z.'-]+)+", "what's their first and last name?",
                     fmt=str.title)),
    "id": ("Student or employee ID: up to two letters then 4 to 8 digits, as the caller said it "
           "(spaces or dashes are fine). Ask if not provided.",
           matches(r"[A-Z]{0,2}\d{4,8}", "an ID is up to two letters and 4 to 8 digits",
                   fmt=lambda v: v.replace(" ", "").replace("-", "").upper())),
    "org_type": ("Whether this is a school or a work absence. Ask if not provided.",
                 one_of("school", "work")),   # the choices become the schema enum
    "reason": ("Why they will be absent, in a few words. Ask if not provided.",
               matches(r".{3,120}", "what's the reason, in a few words?")),
    "start_date": ("First day absent, in the caller's exact words. Pass exactly what the caller said "
                   "(e.g. 'next Monday', 'the fifth', 'tomorrow'); never convert to YYYY-MM-DD, never "
                   "assume today. Ask if not provided.", parse_date),
    "end_date": ("Last day absent, in the caller's exact words; never convert to YYYY-MM-DD. Leave it "
                 "out until the caller says it; for a one-day absence pass their words, e.g. 'just that "
                 "day'. Ask if not provided.", parse_date),
}
REPORTS_DIR = HERE / "data" / "runtime" / "reports"   # one JSON file per confirmed report

# --- Server ---------------------------------------------------------------
PORT = int(os.environ.get("PORT", "3000"))
ROUTE = "/"
