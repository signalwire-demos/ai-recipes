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
VOICE = "rime.spore"
LANGUAGE_CODE = "en-US"

# The stock_quote skill, shared by both agents. mock needs no key.
MARKET_DATA_PROVIDER = os.environ.get("MARKET_DATA_PROVIDER", "mock")   # mock | alphavantage | finnhub
MARKET_DATA_API_KEY = os.environ.get("MARKET_DATA_API_KEY", "")
SKILLS_DIR = HERE / "skills"

# Agent 1: a public quote line, any ticker.
QUOTE_LINE_NAME = "Example Markets quote line"
QUOTE_LINE_ROUTE = "/"

# Agent 2: an employee stock-plan line. Same skill, different params: it can only
# quote the company's own ticker, under its own tool name.
DESK_COMPANY = "Acme Corporation"
DESK_TICKERS = ["ACME"]
DESK_TOOL_NAME = "get_company_share_price"
DESK_ROUTE = "/stock-plan"

# --- Server ---------------------------------------------------------------
PORT = int(os.environ.get("PORT", "3000"))


def skill_params(**overrides) -> dict:
    """The stock_quote params every agent starts from."""
    return {"provider": MARKET_DATA_PROVIDER, "api_key": MARKET_DATA_API_KEY, **overrides}
