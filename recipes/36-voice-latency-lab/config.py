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
BUSINESS_NAME = "Example Hardware"
HOURS_FILE = HERE / "data" / "hours.json"

# The configuration matrix. Each entry changes ONLY the LLM model and the TTS voice;
# the prompt, tools and turn settings are identical, so the comparison is fair.
# Pick one per call with ?config=<name>. The first entry is the default (the baseline).
# "known_issue" is optional, never reaches the SWML, and is printed under the report table.
GPT41_NANO_ISSUE = (
    "gpt-4.1-nano fails on some platform nodes: the REST call log shows calling_error "
    "model_not_found ('The model gpt-4.1-nano-2025-04-14 has been deprecated') on every "
    "assistant turn, then no tool call and no post-prompt. Seen on 4 of 7 live calls on "
    "2026-10-30, with both rime.spore and gcloud voices; gpt-4.1-mini never failed. "
    "A failed call shows up as 'k of N' in Calls."
)
CONFIGS = {
    "mini-rime":     {"model": "gpt-4.1-mini", "voice": "rime.spore"},
    "nano-rime":     {"model": "gpt-4.1-nano", "voice": "rime.spore", "known_issue": GPT41_NANO_ISSUE},
    "oss120b-rime":  {"model": "gpt-oss-120b", "voice": "rime.spore"},
    "mini-gcloud":   {"model": "gpt-4.1-mini", "voice": "gcloud.en-US-Neural2-F"},
}
TEMPERATURE = 0.3                      # held constant across configs

# What the scripted caller says on every lab call (same words, same pauses, every config).
CALLER_SCRIPT = [
    "Hi, are you open on Saturday?",
    "And what about Sunday?",
    "Great, thanks. That's all. Goodbye.",
]
CALLER_PAUSE_SECS = 7                  # silence after each caller line, for the agent's reply

# Where the lab keeps post-prompt payloads (one JSON per call) and reports.
RUNS_DIR = Path(os.environ.get("LAB_RUNS_DIR", HERE / "data" / "runtime" / "runs"))
REPORTS_DIR = HERE / "reports"
PAYLOAD_WAIT_SECS = 60                 # how long run_lab.py waits for a call's post-prompt

# --- Server ---------------------------------------------------------------
PORT = int(os.environ.get("PORT", "3000"))
ROUTE = "/"
