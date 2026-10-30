"""Governance: read the SWML exactly as swaig-test dumps it.

The call flow is code. Transcription starts before the caller can say anything, the events
go only to our own webhook, and no `ai` verb exists: no model is in the call path.
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

RECIPE = Path(__file__).resolve().parents[1]
ENV = {"SWML_BASIC_AUTH_USER": "recipe", "SWML_BASIC_AUTH_PASSWORD": "test-pass",
       "PUBLIC_URL": "https://example.ngrok.app", "SWML_PROXY_URL_BASE": "", "TRANSCRIPT_WEBHOOK_URL": "",
       "MEETING_BRIDGE_NUMBER": ""}


def swaig_test_bin() -> str:
    local = Path(sys.executable).with_name("swaig-test")
    return str(local) if local.exists() else (shutil.which("swaig-test") or "swaig-test")


def dump(**env) -> list[dict]:
    out = subprocess.run([swaig_test_bin(), str(RECIPE / "app.py"), "--dump-swml", "--raw"],
                         env={**os.environ, **ENV, **env}, capture_output=True, text=True,
                         check=True, cwd=RECIPE).stdout
    return json.loads(out)["sections"]["main"]


def verbs(main):
    return [next(iter(v)) for v in main]


def test_no_model_in_the_call_path():
    assert "ai" not in verbs(dump()) and "ai_sidecar" not in verbs(dump())


def test_transcription_starts_before_anything_is_heard():
    main = dump()
    assert verbs(main)[:2] == ["answer", "live_transcribe"]
    start = main[1]["live_transcribe"]["action"]["start"]
    assert start["live_events"] is True
    assert sorted(start["direction"]) == ["local-caller", "remote-caller"]


def test_events_go_only_to_our_authenticated_webhook():
    start = dump()[1]["live_transcribe"]["action"]["start"]
    assert start["webhook"] == "https://recipe:test-pass@example.ngrok.app/transcript"


def test_bridge_mode_connects_after_transcription_starts():
    main = dump(MEETING_BRIDGE_NUMBER="+15550100123")
    names = verbs(main)
    assert names.index("live_transcribe") < names.index("connect")
    assert main[names.index("connect")]["connect"]["to"] == "+15550100123"
    assert "connect" not in verbs(dump())  # default is dictation mode
