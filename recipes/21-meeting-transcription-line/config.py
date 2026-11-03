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
# Where transcripts are delivered. TranscriptStore in consumer.py writes one JSONL file
# per call here; swap the class for a database or queue writer.
TRANSCRIPT_DIR = HERE / "data" / "runtime" / "transcripts"

GREETING = "This meeting line is transcribed. Go ahead and start speaking."
LANGUAGE_CODE = "en-US"
SPEECH_ENGINE = "deepgram"                   # deepgram | google
DIRECTION = ["remote-caller", "local-caller"]  # remote-caller = the person who dialed in
MAX_CALL_SECONDS = 600                       # dictation mode: how long the line stays open

# Optional second party. Set MEETING_BRIDGE_NUMBER in .env to connect the caller to it
# (both legs are transcribed). Empty = dictation mode: the caller talks, the line listens.
BRIDGE_TO = os.environ.get("MEETING_BRIDGE_NUMBER", "")
BRIDGE_FROM = os.environ.get("MEETING_BRIDGE_FROM", os.environ.get("OUTBOUND_2", ""))

# Where the platform POSTs transcript events. Empty = PUBLIC_URL + /transcript, with the
# basic-auth credentials in the URL (the documented user:pass@host form).
TRANSCRIPT_WEBHOOK_URL = os.environ.get("TRANSCRIPT_WEBHOOK_URL", "")
TRANSCRIPT_PATH = "/transcript"
PUBLIC_URL = os.environ.get("PUBLIC_URL", "")
# Optional: Dashboard > API > Signing Key. When set, POST /transcript also needs a valid
# X-SignalWire-Signature (unverified on a live live_transcribe call; see the README).
SIGNING_KEY = os.environ.get("SIGNALWIRE_SIGNING_KEY", "")

# Read-only viewer login for captions screens and transcript viewers. It can read one call
# it names (/calls/<id>, /events?call_id=<id>) and nothing else: no POST /transcript, no
# /calls listing, no all-calls stream. Unset (or equal to the SWML basic auth) = no viewer
# login; only the SWML basic auth can read.
VIEWER_USER = os.environ.get("VIEWER_USER", "")
VIEWER_PASSWORD = os.environ.get("VIEWER_PASSWORD", "")

# --- Server ---------------------------------------------------------------
PORT = int(os.environ.get("PORT", "3000"))
ROUTE = "/"
SSE_KEEPALIVE_SECONDS = 15
SSE_QUEUE_MAX = 256                          # a subscriber this many segments behind is dropped
