"""Every knob for this recipe. "What to change first" in the README points here.

Environment loading: values come from the process environment, then this recipe's
.env, then the monorepo root .env (existing env vars are never overwritten). The root
file is $RECIPES_ENV_FILE if set, else <repo root>/.env, else ~/workdir/demos/.env
(a git worktree has no .env of its own). Blank values are skipped, so a .env copied
from .env.example does not hide the real value further down. No python-dotenv dependency.
"""
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _root_env_file() -> Path:
    if os.environ.get("RECIPES_ENV_FILE"):
        return Path(os.environ["RECIPES_ENV_FILE"])
    repo_env = HERE.parent.parent / ".env"
    return repo_env if repo_env.is_file() else Path.home() / "workdir" / "demos" / ".env"


def _load_env_files() -> None:
    for env_file in (HERE / ".env", _root_env_file()):
        if not env_file.is_file():
            continue
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            value = value.strip().strip("'\"")
            if value:  # KEY= (blank, as in .env.example) must not mask the root .env value
                os.environ.setdefault(key.strip(), value)


_load_env_files()

# The SDK builds its webhook URLs from SWML_PROXY_URL_BASE. Recipes use PUBLIC_URL.
if os.environ.get("PUBLIC_URL") and not os.environ.get("SWML_PROXY_URL_BASE"):
    os.environ["SWML_PROXY_URL_BASE"] = os.environ["PUBLIC_URL"].rstrip("/")

# --- Recipe knobs: change these first -------------------------------------
BUSINESS_NAME = "Example Hardware"
VOICE = "rime.spore"                     # any SignalWire TTS voice id
LANGUAGE_CODE = "en-US"
HOURS_FILE = HERE / "data" / "hours.json"  # swap for your own hours source

# --- Server ---------------------------------------------------------------
PORT = int(os.environ.get("PORT", "3000"))
ROUTE = "/"
