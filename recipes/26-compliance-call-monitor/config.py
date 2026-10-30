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
# Required phrases and deadlines. Each rule passes when ANY of its phrases is heard (in a
# final segment, case and punctuation ignored) within `within_seconds` of the call start.
# `speaker` limits it to one leg ("local-caller" = your side, "remote-caller" = the person
# who dialed in); None = either leg.
RULES = [
    {"id": "recording-disclosure", "within_seconds": 30, "speaker": None,
     "phrases": ["this call is recorded", "this call may be recorded", "this call is being recorded"]},
    {"id": "agent-identification", "within_seconds": 45, "speaker": None,
     "phrases": ["my name is", "you are speaking with", "you're speaking with"]},
]
# Who gets alerted: a phone number (SMS) or an https URL (webhook, Slack-compatible).
# Empty = log only. Every alert is also written to ALERT_LOG.
ALERT_TARGET = os.environ.get("ALERT_TARGET", "")
ALERT_FROM = os.environ.get("ALERT_FROM", os.environ.get("SMS_1", ""))
ALERT_LOG = HERE / "data" / "runtime" / "alerts.jsonl"
ALERT_GRACE_SECONDS = 3        # wait this long past a deadline for in-flight transcript events
DEADLINE_CHECK_SECONDS = 1

# Where transcripts are stored (one JSONL file per call, see TranscriptStore in consumer.py).
TRANSCRIPT_DIR = HERE / "data" / "runtime" / "transcripts"

GREETING = "Connecting your call."
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

# --- Server ---------------------------------------------------------------
PORT = int(os.environ.get("PORT", "3000"))
ROUTE = "/"
SSE_KEEPALIVE_SECONDS = 15
