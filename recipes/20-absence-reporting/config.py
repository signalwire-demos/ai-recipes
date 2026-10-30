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
    "name": ("First and last name of the person who will be absent",
             matches(r"(?!.*\b(my|our|his|her|son|daughter|child|kid|husband|wife|he|she)\b)"
                     r"[a-z][a-z.'-]*( [a-z.'-]+)+", "what's their first and last name?",
                     fmt=str.title)),
    "id": ("Student or employee ID, letters and digits",
           matches(r"[A-Z]{0,2}\d{4,8}", "an ID is up to two letters and 4 to 8 digits",
                   fmt=lambda v: v.replace(" ", "").replace("-", "").upper())),
    "org_type": ("Whether this is a school or a work absence", one_of("school", "work")),
    "reason": ("Why they will be absent, in a few words",
               matches(r".{3,120}", "what's the reason, in a few words?")),
    "start_date": ("First day absent, in the caller's exact words", parse_date),
    "end_date": ("Last day absent, in the caller's exact words. Leave it out until the caller says it; "
                 "for a one-day absence pass their words, e.g. 'just that day'", parse_date),
}
REPORTS_DIR = HERE / "data" / "runtime" / "reports"   # one JSON file per confirmed report

# --- Server ---------------------------------------------------------------
PORT = int(os.environ.get("PORT", "3000"))
ROUTE = "/"
