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
COMPANY_NAME = "Example Mutual"
VOICE = "rime.spore"                     # any SignalWire TTS voice id
LANGUAGE_CODE = "en-US"
MODEL = os.environ.get("CLAIM_MODEL", "gpt-4.1-mini")   # set_prompt_llm_params(model=...)

# What a valid answer looks like. answers.py enforces these in code, not in the prompt.
POLICY_PREFIX = "POL"                    # policy numbers are POL-#### (spoken "P O L 0 1 0 1")
POLICY_DIGITS = 4
MAX_CLAIM_AGE_DAYS = 365                 # an incident date must be in the past year

# Who gets the screened call. Default: the demo pool's HUMAN_LEG role (nobody answers it;
# put a real phone in ADJUSTER_NUMBER for a live test). Route by claim type in pick_adjuster().
ADJUSTER_NUMBER = os.environ.get("ADJUSTER_NUMBER") or os.environ.get("HUMAN_LEG", "")
FROM_NUMBER = os.environ.get("FROM_NUMBER") or os.environ.get("OUTBOUND_2", "")
HOLD_TIMEOUT = 45                        # seconds the caller holds before the callback path
ACCEPT_DIGIT = "1"                       # what the adjuster presses to take the call


def pick_adjuster(claim: dict) -> str:
    """Routing rule. One number for every claim; branch on claim fields to route by type."""
    return ADJUSTER_NUMBER


# --- Storage --------------------------------------------------------------
CLAIMS_FILE = HERE / "data" / "runtime" / "claims.json"   # git-ignored runtime store
CLAIM_SCHEMA_FILE = HERE / "data" / "claim.schema.json"

# --- Server ---------------------------------------------------------------
PORT = int(os.environ.get("PORT", "3000"))
ROUTE = "/"
