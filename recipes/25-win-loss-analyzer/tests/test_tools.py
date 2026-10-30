"""on_summary and analyze.py tests, plus governance assertions on the swaig-test SWML dump."""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

RECIPE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RECIPE))

import analyze  # noqa: E402
import config  # noqa: E402
import extraction  # noqa: E402
from app import WinLossAgent  # noqa: E402

GOOD = {"outcome": "lost", "reasons": ["price", "integrations"], "competitor": "Acme CRM",
        "objections": ["too expensive for our team size"]}


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CALLS_FILE", tmp_path / "calls.jsonl")


@pytest.fixture(scope="module")
def agent():
    return WinLossAgent()


def stored():
    return [json.loads(line) for line in config.CALLS_FILE.read_text().splitlines()]


# --- schema validation ---------------------------------------------------------

def test_valid_extraction_passes():
    assert extraction.parse(GOOD) == (GOOD, [])
    assert extraction.parse(json.dumps(GOOD)) == (GOOD, [])   # raw JSON text is fine too


@pytest.mark.parametrize("bad, expected", [
    ({**GOOD, "outcome": "probably_lost"}, "outcome"),
    ({**GOOD, "reasons": []}, "reasons"),
    ({**GOOD, "reasons": ["vibes"]}, "reasons/0"),
    ({**GOOD, "reasons": ["price", "support", "timing", "security"]}, "reasons"),
    ({k: v for k, v in GOOD.items() if k != "competitor"}, "competitor"),
    ({**GOOD, "deal_size": 50000}, "deal_size"),
    ("The prospect went with Acme on price.", "not JSON"),
    (["lost"], "expected an object"),
    (None, "no summary"),
])
def test_schema_rejects_malformed_extraction(bad, expected):
    record, errors = extraction.parse(bad)
    assert record is None
    assert any(expected in e for e in errors), errors


def test_competitor_aliases_normalize():
    assert extraction.competitor_name(" acme ") == "Acme CRM"
    assert extraction.competitor_name("Someone New") == "Someone New"
    assert extraction.competitor_name(None) is None


# --- on_summary ------------------------------------------------------------------

def test_on_summary_stores_valid_extraction(agent):
    agent.on_summary(GOOD, {"call_id": "call-1", "post_prompt_data": {"raw": json.dumps(GOOD)}})
    [row] = stored()
    assert row["call_id"] == "call-1" and row["valid"] is True
    assert row["summary"] == GOOD and row["errors"] == [] and row["raw"] is None


def test_on_summary_flags_malformed_and_keeps_raw(agent):
    raw = "Sure! Here is the summary: they picked Acme."
    agent.on_summary(raw, {"call_id": "call-2", "post_prompt_data": {"raw": raw}})
    agent.on_summary(None, {"call_id": "call-3"})
    bad, empty = stored()
    assert bad["valid"] is False and bad["summary"] is None and bad["raw"] == raw
    assert bad["errors"][0].startswith("not JSON")
    assert empty["valid"] is False and empty["errors"] == ["no summary returned"]


# --- analyze.py ------------------------------------------------------------------

def test_fixture_report_matches_golden():
    text = analyze.main(["--source", "fixtures", "--since", "7d"])
    assert text == (RECIPE / "tests" / "expected_report.md").read_text()


def test_report_flags_bad_rows_and_never_counts_them():
    good, flagged = analyze.split(analyze.load("fixtures"))
    assert {f["call_id"] for f in flagged} == {"fixture-12", "fixture-13"}
    assert all(s["outcome"] in config.OUTCOMES for s in good)
    # fixture-13 claims valid=true but fails the schema: re-validated, not trusted
    assert "probably_lost" in next(f for f in flagged if f["call_id"] == "fixture-13")["errors"][0]


def test_since_window_and_local_source(agent):
    agent.on_summary(GOOD, {"call_id": "call-9"})
    text = analyze.main(["--source", "local", "--since", "24h"])
    assert "1 interviews analyzed, 0 flagged" in text and "| Acme CRM | 0 | 1 | 0 |" in text
    assert "11 interviews" in analyze.main(["--source", "fixtures", "--since", "all"])
    with pytest.raises(SystemExit):
        analyze.main(["--since", "a week"])


def test_signalwire_source_is_blocked_not_guessed():
    with pytest.raises(SystemExit, match="TODO\\(blocked"):
        analyze.load("signalwire")


# --- governance: the SWML swaig-test dumps -----------------------------------------

def swaig_test_bin() -> str:
    local = Path(sys.executable).with_name("swaig-test")
    return str(local) if local.exists() else (shutil.which("swaig-test") or "swaig-test")


@pytest.fixture(scope="module")
def ai():
    out = subprocess.run([swaig_test_bin(), str(RECIPE / "app.py"), "--dump-swml", "--raw"],
                         capture_output=True, text=True, check=True, cwd=RECIPE).stdout
    return next(v["ai"] for v in json.loads(out)["sections"]["main"] if "ai" in v)


def test_governance_interviewer_has_no_tools(ai):
    steps = ai["prompt"]["contexts"]["default"]["steps"]
    assert all(s["functions"] == [] for s in steps)
    assert not ai.get("SWAIG", {}).get("functions")   # it cannot write or look anything up


def test_governance_post_prompt_is_the_schema(ai):
    text = ai["post_prompt"]["text"]
    assert text == extraction.POST_PROMPT
    for key in extraction.SCHEMA["required"]:
        assert f'"{key}"' in text
    assert all(f'"{r}"' in text for r in config.REASONS)
    assert ai["post_prompt"]["temperature"] == config.POST_PROMPT_TEMPERATURE
    assert ai["post_prompt_url"].split("?")[0].endswith("/post_prompt/")
