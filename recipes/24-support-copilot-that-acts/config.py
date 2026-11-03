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

# .env.example ships SWML_BASIC_AUTH_PASSWORD=change-me. Anyone who has read this repo knows it,
# and it guards the SWML, every tool and every route here, so never serve with it.
if os.environ.get("SWML_BASIC_AUTH_PASSWORD", "").strip() == "change-me":
    raise SystemExit("SWML_BASIC_AUTH_PASSWORD is still the .env.example placeholder: "
                     "set a long random value (python -c 'import secrets; print(secrets.token_urlsafe(24))').")

# The SDK builds its webhook URLs from SWML_PROXY_URL_BASE. Recipes use PUBLIC_URL.
if os.environ.get("PUBLIC_URL") and not os.environ.get("SWML_PROXY_URL_BASE"):
    os.environ["SWML_PROXY_URL_BASE"] = os.environ["PUBLIC_URL"].rstrip("/")

# --- Recipe knobs: change these first -------------------------------------
# The credit cap. Enforced in the issue_credit handler. It is never put in the prompt,
# the tool description or any tool response, so the model can't quote it or argue
# toward it. The rep sees it on the refusal card.
CREDIT_CAP_USD = 25.00
CURRENCY = "USD"

# The order backend. The bundled mock is a JSON file; swap load_orders() in app.py for
# your order API. Issued credits are appended to the ledger (one credit per order).
ORDERS_FILE = HERE / "data" / "orders.json"
CREDIT_LEDGER = HERE / "data" / "credits.jsonl"

# The sidecar's own words. It listens, looks orders up, and issues a credit only after
# the human rep has offered one.
SIDECAR_PROMPT = (
    "You are a silent support copilot on a live call between a support rep and a customer. "
    "You never speak and never offer anything to the customer. When an order number is "
    "mentioned, call lookup_order. When the rep tells the customer a specific dollar amount they "
    "will credit, call issue_credit with the order number, that exact amount, and a short reason. "
    "If the rep offers a credit without a dollar amount, or as a percentage, do not call "
    "issue_credit; tell the rep in one line to state the amount in dollars. "
    "Otherwise give the rep one short piece of advice, or call sidecar_skip."
)
LANGUAGE_CODE = "en-US"
SIDECAR_MODEL = os.environ.get("SIDECAR_MODEL", "")      # blank = platform default
CUSTOMER_ROLE = "remote-caller"   # the leg that ends a turn: the inbound caller is the customer
HINTS = ["order number", "credit", "refund"]

# The rep's phone. The inbound call is bridged here with `connect`.
# Demo pool: HUMAN_LEG_2 (nobody answers it; put a real phone in REP_NUMBER for a live test).
REP_NUMBER = os.environ.get("REP_NUMBER") or os.environ.get("HUMAN_LEG_2") or "+15550101"
FROM_NUMBER = os.environ.get("FROM_NUMBER") or os.environ.get("OUTBOUND_2") or "+15550100"

# --- Server ---------------------------------------------------------------
PORT = int(os.environ.get("PORT", "3000"))
PUBLIC_URL = os.environ.get("PUBLIC_URL", f"http://localhost:{PORT}").rstrip("/")
WEB_DIR = HERE / "web"
# The rep page's own login, separate from SWML_BASIC_AUTH_*. That platform credential also
# opens /swaig (the sidecar's tools), so reps never get it. Blank REP_PASSWORD = page locked.
REP_USER = os.environ.get("REP_USER", "rep")
REP_PASSWORD = os.environ.get("REP_PASSWORD", "")
FEED_SIZE = 200              # cards kept in memory for the rep page
