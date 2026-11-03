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
BUSINESS_NAME = "Example Broadband"
LANGUAGE_CODE = "en-US"

# Each department is one isolated context: its own persona, its own voice (a named
# add_language entry), the only tools it can call, and where it may route the caller.
# "default" is the front desk, where every call starts. It owns no tools.
DEPARTMENTS = [
    {
        "name": "default",
        "persona": "Riley",
        "voice": "inworld.Sarah",
        "role": "You are Riley at the front desk. Find out whether the caller needs "
                "sales, support or billing, then route them. Do not answer department "
                "questions yourself.",
        "tools": [],
        "routes": ["sales", "support", "billing"],
        "enter_filler": "Back at the front desk.",
    },
    {
        "name": "sales",
        "persona": "Franklin",
        "voice": "inworld.Mark",
        "role": "You are Franklin in sales. Quote plan prices with get_plan_price. "
                "You cannot see invoices or issue refunds.",
        "tools": ["get_plan_price"],
        "routes": ["default", "support"],
        "enter_filler": "Let me get you over to sales.",
    },
    {
        "name": "support",
        "persona": "Rachael",
        "voice": "inworld.Ashley",
        "role": "You are Rachael in technical support. Check outages with "
                "check_service_status and open tickets with open_ticket.",
        "tools": ["check_service_status", "open_ticket"],
        "routes": ["default", "sales", "billing"],
        "enter_filler": "Connecting you to technical support.",
    },
    {
        "name": "billing",
        "persona": "Dwight",
        "voice": "inworld.Blake",
        "role": "You are Dwight in billing. Look up invoices with get_invoice and "
                "refund them with issue_refund. Ask for the invoice number and the "
                "billing ZIP code. Before issue_refund: call get_invoice, read the "
                "amount back to the caller, and get an explicit yes.",
        "tools": ["get_invoice", "issue_refund"],
        "routes": ["default", "support"],
        "enter_filler": "Transferring you to billing.",
    },
]

REFUND_LIMIT = 100.00                          # dollars; bigger refunds go to a human
MAX_LOOKUP_FAILURES = 3                        # wrong invoice/ZIP pairs per call before lookups stop
PLANS_FILE = HERE / "data" / "plans.json"
STATUS_FILE = HERE / "data" / "service_status.json"
INVOICES_FILE = HERE / "data" / "invoices.json"
TICKETS_FILE = HERE / "data" / "tickets.jsonl"   # written at runtime
REFUNDS_FILE = HERE / "data" / "refunds.jsonl"   # written at runtime

# --- Server ---------------------------------------------------------------
PORT = int(os.environ.get("PORT", "3000"))
ROUTE = "/"
