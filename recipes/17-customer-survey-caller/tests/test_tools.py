"""Prefab configuration, handler, scoring and kickoff tests, plus SWML governance checks."""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

RECIPE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RECIPE))

import call_customer  # noqa: E402
import config  # noqa: E402
import score_results  # noqa: E402
from app import SurveyCaller, normalize  # noqa: E402

FIXTURE = RECIPE / "tests" / "fixtures" / "results.jsonl"
Q = {q["id"]: q for q in config.QUESTIONS}


@pytest.fixture(scope="module")
def agent():
    return SurveyCaller()


@pytest.fixture(autouse=True)
def scratch_results(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "RESULTS_FILE", tmp_path / "results.jsonl")


def rows():
    if not config.RESULTS_FILE.exists():
        return []
    return [json.loads(x) for x in config.RESULTS_FILE.read_text().splitlines()]


# --- log_response (handler decides what is recorded) ------------------------

def test_valid_answers_are_normalized_and_written(agent):
    raw = {"call_id": "c1", "global_data": {"customer_id": "P-0101"}}
    agent.log_response({"question_id": "likely_to_recommend", "response": "9"}, raw)
    agent.log_response({"question_id": "best_part", "response": "Wait Time"}, raw)
    agent.log_response({"question_id": "issue_resolved", "response": "Yeah."}, raw)
    got = [(r["question_id"], r["answer"], r["customer_id"], r["call_id"]) for r in rows()]
    assert got == [("likely_to_recommend", 9, "P-0101", "c1"), ("best_part", "wait time", "P-0101", "c1"),
                   ("issue_resolved", "yes", "P-0101", "c1")]


@pytest.mark.parametrize("qid,response", [
    ("likely_to_recommend", "11"), ("likely_to_recommend", "0"), ("likely_to_recommend", "great"),
    ("likely_to_recommend", "eleven"), ("likely_to_recommend", "twelve"),
    ("best_part", "parking"), ("issue_resolved", "maybe"), ("no_such_question", "yes"),
])
def test_invalid_answers_are_refused_and_not_written(agent, qid, response):
    result = agent.log_response({"question_id": qid, "response": response}, {"call_id": "c2"})
    assert result.to_dict()["response"].startswith(("Not recorded", "Unknown question"))
    assert rows() == []


@pytest.mark.parametrize("spoken,value", [
    ("nine", 9), ("Nine.", 9), ("ten", 10), ("a seven out of ten", 7), ("9 out of 10", 9), ("8.0", 8),
])
def test_rating_spoken_as_a_word_is_accepted(spoken, value):
    # Regression: live call 46145b42 sent log_response("nine") and the handler refused it.
    assert normalize(Q["likely_to_recommend"], spoken) == (value, None)


def test_optional_open_question_accepts_empty(agent):
    assert normalize(Q["comments"], "") == ("", None)
    assert normalize({"type": "open_ended", "required": True}, " ")[1] is not None
    agent.log_response({"question_id": "comments", "response": "Great hygienist"}, {"call_id": "c3"})
    assert rows()[0]["answer"] == "Great hygienist"


def test_prefab_validate_response_still_works(agent):
    out = agent.validate_response({"question_id": "issue_resolved", "response": "maybe"}, {})
    assert "yes" in out.to_dict()["response"]


def test_per_call_customer_id(agent):
    seen = {}

    class Fake:
        def update_global_data(self, data):
            seen.update(data)

    SurveyCaller.per_call({"customer": "P-0105"}, {}, {}, Fake())
    SurveyCaller.per_call({"customer": "../../x"}, {}, {}, Fake())
    assert seen == {"customer_id": "P-0105"}


# --- prefab configuration renders the expected questions --------------------

def swaig_test_bin() -> str:
    local = Path(sys.executable).with_name("swaig-test")
    return str(local) if local.exists() else (shutil.which("swaig-test") or "swaig-test")


@pytest.fixture(scope="module")
def ai():
    out = subprocess.run(
        [swaig_test_bin(), str(RECIPE / "app.py"), "--dump-swml", "--raw",
         "--query-params", '{"customer": "P-0101"}'],
        capture_output=True, text=True, check=True, cwd=RECIPE,
    ).stdout
    return next(v["ai"] for v in json.loads(out)["sections"]["main"] if "ai" in v)


def test_prefab_renders_configured_questions_in_order(ai):
    section = next(s for s in ai["prompt"]["pom"] if s["title"] == "Survey Questions")
    assert [s["title"] for s in section["subsections"]] == [q["text"] for q in config.QUESTIONS]
    assert "Scale: 1-10" in section["subsections"][0]["body"]
    assert "Options: scheduling, staff, price, wait time" in section["subsections"][1]["body"]
    assert [q["id"] for q in ai["global_data"]["questions"]] == list(Q)
    assert ai["params"]["static_greeting"] == config.INTRODUCTION
    assert ai["languages"][0]["voice"] == config.VOICE


def test_governance_only_survey_tools_and_customer_from_url(ai):
    tools = {f["function"] for f in ai["SWAIG"]["functions"]}
    assert tools == {"validate_response", "log_response"}
    log = next(f for f in ai["SWAIG"]["functions"] if f["function"] == "log_response")
    assert "customer_id" not in log["parameters"]["properties"]   # the model can't pick whose row it is
    assert ai["global_data"]["customer_id"] == "P-0101"


# --- score_results.py --------------------------------------------------------

def test_scoring_totals_on_fixture():
    report = score_results.score(score_results.load_respondents(FIXTURE))
    assert report["respondents"] == 4
    assert report["complete"] == 3                 # call-d only answered the rating
    # last answer wins: call-b re-rated 4 -> 6. Ratings 10, 6, 8, 9.
    assert report["nps"] == {"rated": 4, "promoters": 2, "passives": 1, "detractors": 1, "score": 25}
    assert report["questions"]["best_part"] == {"staff": 2, "price": 1}
    assert report["questions"]["issue_resolved"] == {"yes": 2, "no": 1}
    assert report["questions"]["likely_to_recommend"] == {"average": 8.2}
    assert report["questions"]["comments"] == ["Very friendly front desk."]


def test_scoring_rule_comes_from_config(monkeypatch):
    monkeypatch.setattr(config, "PROMOTER_MIN", 8)
    report = score_results.score(score_results.load_respondents(FIXTURE))
    assert report["nps"]["promoters"] == 3 and report["nps"]["score"] == 50


def test_scoring_empty_file(tmp_path, capsys):
    assert score_results.score({})["nps"]["score"] is None
    assert score_results.main([str(tmp_path / "none.jsonl")]) == 0
    assert "NPS n/a" in capsys.readouterr().out


def test_report_text(capsys):
    score_results.main([str(FIXTURE)])
    out = capsys.readouterr().out
    assert "4 respondents, 3 complete" in out and "NPS 25" in out


# --- call_customer.py ---------------------------------------------------------

@pytest.fixture
def dial_env(monkeypatch):
    monkeypatch.setenv("PUBLIC_URL", "https://example.ngrok.app")
    monkeypatch.setenv("SWML_BASIC_AUTH_USER", "recipe")
    monkeypatch.setenv("SWML_BASIC_AUTH_PASSWORD", "p@ss")


def test_kickoff_dry_run_and_bad_id(dial_env, capsys):
    assert call_customer.main(["P-0101", "--to", "+15550123", "--from", "+15550100", "--dry-run"]) == 0
    assert "?customer=P-0101" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        call_customer.main(["../x", "--to", "+15550123", "--from", "+15550100", "--dry-run"])


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
    assert call_customer.main(["P-0101", "--to", "+15550123", "--from", "+15550100"]) == 0
    assert calls == [{"from_": "+15550100", "to": "+15550123",
                      "url": "https://recipe:p%40ss@example.ngrok.app/?customer=P-0101"}]
