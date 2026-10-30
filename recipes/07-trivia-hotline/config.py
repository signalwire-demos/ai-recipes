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
SHOW_NAME = "Ring-In Trivia"
VOICE = "rime.spore"                     # any SignalWire TTS voice id
LANGUAGE_CODE = "en-US"

# The question file: a JSON list of {"id", "question", "answers": [accepted, ...]}.
# Only the question text ever reaches the model. The answers stay on this server.
QUESTIONS_FILE = HERE / "data" / "questions.json"
ROUNDS = 5                               # questions per call; must be <= the number in the file
SHUFFLE = True                           # random question order per call

# Fuzzy matching: 0.0-1.0 similarity a spoken answer needs to count as correct
# ("shakespear" vs "shakespeare" is about 0.95). Lower is more forgiving.
FUZZY_TOLERANCE = 0.8
REVEAL_ANSWER_ON_MISS = True             # after a wrong answer, say what the right one was

# --- Server ---------------------------------------------------------------
PORT = int(os.environ.get("PORT", "3000"))
ROUTE = "/"
