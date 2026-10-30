"""Handler tests, kickoff script tests, and governance assertions on the dumped SWML."""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

RECIPE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RECIPE))

import call_candidate  # noqa: E402
import config  # noqa: E402
from app import HiringScreenAgent, build_record  # noqa: E402

FIXTURE = json.loads((RECIPE / "tests" / "fixtures" / "global_data.json").read_text())
KEYS = [q["key"] for q in config.QUESTIONS]


@pytest.fixture(scope="module")
def agent():
    return HiringScreenAgent()


@pytest.fixture(autouse=True)
def scratch_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CANDIDATES_DIR", tmp_path / "candidates")


def actions(result):
    return result.to_dict().get("action", [])


# --- submit_screen ----------------------------------------------------------

def test_submit_writes_expected_schema(agent):
    result = agent.submit_screen({}, {"global_data": FIXTURE, "call_id": "abcdef123456"})
    record = json.loads((config.CANDIDATES_DIR / "C-0101.json").read_text())
    assert set(record) == {"candidate_id", "call_id", "role", "submitted_at", "complete", "missing", "answers"}
    assert record["candidate_id"] == "C-0101" and record["call_id"] == "abcdef123456"
    assert record["complete"] is True and record["missing"] == []
    assert record["answers"] == FIXTURE["screen"]
    assert list(record["answers"]) == KEYS  # question order preserved
    acts = actions(result)
    assert {"change_step": "wrap_up"} in acts
    assert {"set_global_data": {"submitted": "C-0101"}} in acts


def test_submit_marks_missing_answers(agent):
    partial = {"candidate_id": "C-0102", "screen": {"work_authorized": False}}
    agent.submit_screen({}, {"global_data": partial, "call_id": "x"})
    record = json.loads((config.CANDIDATES_DIR / "C-0102.json").read_text())
    assert record["complete"] is False
    assert record["missing"] == KEYS[1:]
    assert record["answers"]["years_experience"] is None


def test_submit_never_uses_unsafe_id_as_a_path(agent):
    bad = {"candidate_id": "../../etc/passwd", "screen": FIXTURE["screen"]}
    agent.submit_screen({}, {"global_data": bad, "call_id": "12345678abcd"})
    assert [p.name for p in config.CANDIDATES_DIR.iterdir()] == ["call-12345678.json"]


def test_build_record_without_candidate_id_uses_call_id():
    assert build_record({}, None)["candidate_id"] == "call-unknown"


# --- per-call config (candidate id from the dial URL) -----------------------

def test_per_call_sets_candidate_id(agent):
    seen = {}

    class Fake:
        def set_global_data(self, data):
            seen.update(data)

    HiringScreenAgent.per_call({"candidate": "C-0103"}, {}, {}, Fake())
    assert seen == {"candidate_id": "C-0103"}
    seen.clear()
    HiringScreenAgent.per_call({"candidate": "drop table;"}, {}, {}, Fake())
    assert seen == {}


# --- call_candidate.py -------------------------------------------------------

@pytest.fixture
def dial_env(monkeypatch):
    monkeypatch.setenv("PUBLIC_URL", "https://example.ngrok.app")
    monkeypatch.setenv("SWML_BASIC_AUTH_USER", "recipe")
    monkeypatch.setenv("SWML_BASIC_AUTH_PASSWORD", "p@ss")


def test_agent_url_carries_auth_and_candidate(dial_env):
    assert call_candidate.agent_url("C-0101") == "https://recipe:p%40ss@example.ngrok.app/?candidate=C-0101"
    assert "p%40ss" not in call_candidate.agent_url("C-0101", mask=True)


def test_dry_run_does_not_dial(dial_env, capsys):
    rc = call_candidate.main(["C-0101", "--to", "+15550123", "--from", "+15550100", "--dry-run"])
    out = capsys.readouterr().out
    assert rc == 0 and "dial +15550123 from +15550100" in out and "***" in out


def test_kickoff_rejects_bad_id(dial_env):
    with pytest.raises(SystemExit):
        call_candidate.main(["../x", "--to", "+15550123", "--from", "+15550100", "--dry-run"])


def test_kickoff_dials_with_rest_client(dial_env, monkeypatch):
    calls = []

    class FakeCalling:
        def dial(self, **kw):
            calls.append(kw)
            return {"id": "call-sid-1"}

    class FakeClient:
        calling = FakeCalling()

    import signalwire.rest
    monkeypatch.setattr(signalwire.rest, "RestClient", lambda: FakeClient())
    assert call_candidate.main(["C-0101", "--to", "+15550123", "--from", "+15550100"]) == 0
    assert calls == [{"from_": "+15550100", "to": "+15550123",
                      "url": "https://recipe:p%40ss@example.ngrok.app/?candidate=C-0101"}]


# --- governance: read the SWML exactly as swaig-test dumps it ---------------

def swaig_test_bin() -> str:
    local = Path(sys.executable).with_name("swaig-test")
    return str(local) if local.exists() else (shutil.which("swaig-test") or "swaig-test")


@pytest.fixture(scope="module")
def ai():
    out = subprocess.run(
        [swaig_test_bin(), str(RECIPE / "app.py"), "--dump-swml", "--raw",
         "--query-params", '{"candidate": "C-0101"}'],
        capture_output=True, text=True, check=True, cwd=RECIPE,
    ).stdout
    return next(v["ai"] for v in json.loads(out)["sections"]["main"] if "ai" in v)


def steps_of(ai_doc):
    return {s["name"]: s for s in ai_doc["prompt"]["contexts"]["default"]["steps"]}


def test_governance_no_tools_reachable_during_gather(ai):
    screen = steps_of(ai)["screen"]
    assert screen["functions"] == []          # nothing but the platform's gather_submit
    assert screen["valid_steps"] == []        # no next_step: the form can't be skipped
    assert all("functions" not in q for q in screen["gather_info"]["questions"])


def test_governance_questions_fixed_order_and_confirmed(ai):
    gather = steps_of(ai)["screen"]["gather_info"]
    assert [q["key"] for q in gather["questions"]] == KEYS
    confirmed = {q["key"] for q in gather["questions"] if q.get("confirm")}
    assert confirmed == {"work_authorized", "earliest_start"}
    assert gather["completion_action"] == "submit" and gather["output_key"] == config.OUTPUT_KEY


def test_governance_submit_tool_only_in_submit_step(ai):
    steps = steps_of(ai)
    assert steps["submit"]["functions"] == ["submit_screen"]
    assert steps["wrap_up"]["functions"] == []
    assert ai["global_data"] == {"candidate_id": "C-0101"}
