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
            value = value.strip().strip("'\"")
            if value:  # a blank line in the recipe .env must not hide the root .env value
                os.environ.setdefault(key.strip(), value)


_load_env_files()

# The SDK builds its webhook URLs from SWML_PROXY_URL_BASE. Recipes use PUBLIC_URL.
if os.environ.get("PUBLIC_URL") and not os.environ.get("SWML_PROXY_URL_BASE"):
    os.environ["SWML_PROXY_URL_BASE"] = os.environ["PUBLIC_URL"].rstrip("/")

# --- Recipe knobs: change these first -------------------------------------
TENANTS_DIR = HERE / "tenants"            # one YAML per tenant, re-read on every request
ALLOW_TENANT_QUERY = True                 # ?tenant=<id> when the called number matches none
MESSAGES_FILE = Path(os.environ.get("MESSAGES_FILE", HERE / "data" / "runtime" / "messages.jsonl"))  # per-tenant log

# Unknown or missing tenant: a neutral answering service that can only take a message.
DEFAULT_TENANT = {
    "id": "default",
    "name": "the answering service",
    "voice": "gcloud.en-US-Neural2-F",
    "timezone": "America/Chicago",
    "hours": {},
    "prompt": "You answer the phone for a business that is not available right now. "
              "Do not guess which business it is. Offer to take a message.",
    "tools": ["take_message"],
    "transfer_targets": {},
}

# --- Server ---------------------------------------------------------------
PORT = int(os.environ.get("PORT", "3000"))
ROUTE = "/"
