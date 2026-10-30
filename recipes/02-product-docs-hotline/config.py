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
PRODUCT_NAME = "SignalWire"
VOICE = "rime.spore"                       # any SignalWire TTS voice id
LANGUAGE_CODE = "en-US"

DOCS_DIR = HERE / "docs"                   # the folder `make index` reads
INDEX_FILE = HERE / "data" / "knowledge.swsearch"   # built by `make index`, committed

SEARCH_TOOL = "search_docs"
SEARCH_COUNT = 3                           # chunks returned per search
# Chunks whose vector similarity is below this are dropped in app.py before the model sees
# them. Measured on the sample docs: in-scope questions score 0.45-0.80, off-topic under 0.25.
SIMILARITY_THRESHOLD = 0.35
MAX_CHUNK_CHARS = 1500                     # per excerpt handed to the model
NOT_IN_DOCS = "NOT_IN_DOCS. Nothing in the docs matches that question."
REFUSAL = "That's not in the docs."        # what the agent says when the search comes back empty

# --- Server ---------------------------------------------------------------
PORT = int(os.environ.get("PORT", "3000"))
ROUTE = "/"
