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
# Captions page. Styling lives in the page's <style> block. SPEAKER_LABELS maps each
# transcribed leg to the name shown on screen; set a leg to None to hide it.
CAPTIONS_PAGE = HERE / "static" / "captions.html"
SPEAKER_LABELS = {"remote-caller": "Caller", "local-caller": "Line", "unknown": "Speaker"}
MAX_CAPTION_LINES = 200                      # older lines scroll off the page
DELAY_SLOW_MS, DELAY_LATE_MS = 1500, 3000    # delay badge turns amber, then red

# Where transcripts are delivered. TranscriptStore in consumer.py writes one JSONL file
# per call here; swap the class for a database or queue writer.
TRANSCRIPT_DIR = HERE / "data" / "runtime" / "transcripts"

GREETING = "This call is captioned live. Go ahead and start speaking."
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
