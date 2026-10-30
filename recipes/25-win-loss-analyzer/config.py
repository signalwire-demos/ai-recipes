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
COMPANY_NAME = "Example CRM"
VOICE = "rime.spore"                     # any SignalWire TTS voice id
LANGUAGE_CODE = "en-US"

# The extraction schema (extraction.py builds the JSON Schema and the post_prompt from these).
OUTCOMES = ["won", "lost", "no_decision"]
REASONS = ["price", "features", "integrations", "ease_of_use", "support", "security",
           "timing", "relationship"]
MAX_REASONS = 3
# Competitor names as callers say them -> the name used in the report.
COMPETITOR_ALIASES = {"acme": "Acme CRM", "acme crm": "Acme CRM", "globex": "Globex Sales",
                      "globex sales": "Globex Sales", "initech": "Initech Suite",
                      "initech suite": "Initech Suite"}
POST_PROMPT_TEMPERATURE = 0.1

# --- Storage and report ---------------------------------------------------
CALLS_FILE = Path(os.environ.get("CALLS_FILE") or HERE / "data" / "runtime" / "calls.jsonl")
FIXTURES_FILE = HERE / "data" / "fixtures" / "calls.jsonl"   # synthetic summaries
SUMMARY_SOURCE = os.environ.get("SUMMARY_SOURCE", "fixtures")  # fixtures | local | signalwire
TOP_N = 5                                # rows per ranked table in the report

# --- Server ---------------------------------------------------------------
PORT = int(os.environ.get("PORT", "3000"))
ROUTE = "/"
