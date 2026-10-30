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
# The objection playbook. The classifier is plain code: a category matches when any of
# its regexes matches the customer's words (case-insensitive). The talk tracks are shown
# to the rep only; they are never put in the sidecar's prompt or returned to its model.
COMPETITORS = ["Globex", "Initech", "Acme Voice"]
PLAYBOOK = {
    "pricing": {
        "title": "Pricing objection",
        "patterns": [r"\btoo (expensive|pricey|much)\b", r"\b(price|pricing|cost|budget)\b",
                     r"\bcheaper\b", r"\bdiscount\b"],
        "tips": ["Ask what they are comparing the price against.",
                 "Anchor on cost per resolved call, not the seat price.",
                 "Offer the annual plan before any discount."],
    },
    "timing": {
        "title": "Timing objection",
        "patterns": [r"\bnot (right )?now\b", r"\bnext (quarter|year|month)\b",
                     r"\b(call|check) back\b", r"\btoo busy\b", r"\bbad time\b"],
        "tips": ["Ask what has to happen first, and when.",
                 "Offer a pilot that starts after their deadline.",
                 "Book the follow-up on the call, with a date."],
    },
    "competitor": {
        "title": "Competitor mentioned",
        "patterns": [r"\b(competitor|other vendor|already use|already have)\b"]
                    + [rf"\b{name}\b" for name in COMPETITORS],
        "tips": ["Ask what they like about their current vendor.",
                 "Name one difference that matters to them, not five.",
                 "Offer a side-by-side on their own call recordings."],
    },
    "authority": {
        "title": "Not the decision maker",
        "patterns": [r"\b(my|the) (boss|manager|vp|cfo|ceo|team)\b",
                     r"\b(run it|check) (by|with)\b", r"\bnot my (call|decision)\b",
                     r"\b(sign[- ]off|approval|procurement)\b"],
        "tips": ["Ask who else is involved and what they care about.",
                 "Offer a 20-minute call with the decision maker.",
                 "Send a one-page summary they can forward."],
    },
}
REPEAT_AFTER_S = 60          # same category on the same call shows again only after this

# The sidecar's own words (one line of advice per customer turn, or sidecar_skip).
SIDECAR_PROMPT = (
    "You are a silent sales copilot on a live call between a sales rep and a customer. "
    "You never speak. When the customer raises a concern or objection, call flag_objection "
    "with the customer's exact words. Otherwise give the rep one short piece of advice, "
    "or call sidecar_skip if no advice is needed."
)
LANGUAGE_CODE = "en-US"
SIDECAR_MODEL = os.environ.get("SIDECAR_MODEL", "")      # blank = platform default
CUSTOMER_ROLE = "remote-caller"   # the leg that ends a turn: the inbound caller is the customer

# Sidecar callback events that carry the customer's words. Seen live (call 6d04cc81, 2026-10-30):
# each "turn" event has customer_text, agent_text and transcript_delta. Other types seen: start,
# request, tool_call, tool_result, skip, stop, final.
TRANSCRIPT_EVENT_TYPES = {"turn"}
TRANSCRIPT_FIELD = "customer_text"     # agent_text is the rep: never classified

# The rep's phone. The inbound call is bridged here with `connect`.
# Demo pool: HUMAN_LEG_2 (nobody answers it; put a real phone in REP_NUMBER for a live test).
REP_NUMBER = os.environ.get("REP_NUMBER") or os.environ.get("HUMAN_LEG_2") or "+15550101"
FROM_NUMBER = os.environ.get("FROM_NUMBER") or os.environ.get("OUTBOUND_2") or "+15550100"

# --- Server ---------------------------------------------------------------
PORT = int(os.environ.get("PORT", "3000"))
PUBLIC_URL = os.environ.get("PUBLIC_URL", f"http://localhost:{PORT}").rstrip("/")
WEB_DIR = HERE / "web"
FEED_SIZE = 200              # cards kept in memory for the rep page
