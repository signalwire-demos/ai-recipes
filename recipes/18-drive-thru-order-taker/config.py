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
BUSINESS_NAME = "Example Burger"
VOICE = "rime.spore"                         # any SignalWire TTS voice id
LANGUAGE_CODE = "en-US"
MENU_FILE = HERE / "data" / "menu.json"      # items, sizes, modifiers and combos (prices in cents)
STOCK_FILE = HERE / "data" / "stock.json"    # out-of-stock list + substitutes; re-read on every tool call
TAX_RATE = "0.0825"                          # sales tax as a decimal string (8.25%)
MAX_QUANTITY = 10                            # per order line
ORDERS_FILE = HERE / "data" / "runtime" / "orders.jsonl"  # confirmed orders (swap for your POS)

# --- Server ---------------------------------------------------------------
PORT = int(os.environ.get("PORT", "3000"))
ROUTE = "/"
