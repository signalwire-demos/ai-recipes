"""Tests for the trivia hotline.

1. submit_answer is called directly with a fixture global_data; assertions are on
   the FunctionResult actions (wire names: set_global_data, change_step).
2. The answer key never reaches the model: not in the dumped SWML (prompt, steps,
   global_data), and not in any global_data the handler writes.
3. Governance assertions read the SWML exactly as swaig-test dumps it.
"""
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

RECIPE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RECIPE))

import config  # noqa: E402
from app import TriviaAgent, is_correct, model_state  # noqa: E402

QUESTIONS = json.loads(config.QUESTIONS_FILE.read_text())
ALL_ANSWERS = [a for q in QUESTIONS for a in q["answers"]]


@pytest.fixture(scope="module")
def agent():
    return TriviaAgent()


def state(agent, order, round_no=1, score=0):
    return model_state(agent.questions, order, round_no, score)


def actions(result):
    return result.to_dict().get("action", [])


def find(acts, key):
    return [a[key] for a in acts if key in a]


def leaked(text: str) -> list[str]:
    """Accepted answers that appear as whole words in text."""
    return [a for a in ALL_ANSWERS if re.search(rf"\b{re.escape(a)}\b", text, re.I)]


# --- grading ------------------------------------------------------------------

@pytest.mark.parametrize("guess, accepted", [
    ("Mars", ["Mars"]),
    ("mars.", ["Mars"]),
    ("I think it's Mars", ["Mars"]),
    ("the pacific ocean", ["Pacific", "Pacific Ocean"]),
    ("shakespear", ["William Shakespeare", "Shakespeare"]),      # fuzzy: typo
    ("um, carbon dioxide", ["carbon dioxide", "CO2"]),
    ("Mount Everest!", ["Mount Everest", "Everest"]),
])
def test_correct_answers_including_fuzzy(guess, accepted):
    assert is_correct(guess, accepted)


@pytest.mark.parametrize("guess, accepted", [
    ("Venus", ["Mars"]),
    ("Kyoto", ["Tokyo"]),
    ("I don't know", ["Egypt"]),
    ("", ["piano"]),
])
def test_wrong_answers(guess, accepted):
    assert not is_correct(guess, accepted)


def test_tolerance_is_the_knob(monkeypatch):
    monkeypatch.setattr(config, "FUZZY_TOLERANCE", 0.99)
    assert not is_correct("shakespear", ["Shakespeare"])
    assert is_correct("shakespeare", ["Shakespeare"])


# --- submit_answer ------------------------------------------------------------

def test_correct_answer_scores_and_loads_next_question(agent):
    gd = state(agent, ["q01", "q05", "q08"])
    acts = actions(agent.submit_answer({"answer": "mars"}, {"global_data": gd}))
    (new,) = find(acts, "set_global_data")
    assert new["score"] == 1 and new["round"] == 2
    assert new["question_id"] == "q05"
    assert new["question"] == agent.questions["q05"]["question"]
    assert new["queue"] == ["q08"]
    assert find(acts, "change_step") == []


def test_incorrect_answer_does_not_score_but_still_advances(agent):
    gd = state(agent, ["q01", "q05"], round_no=1, score=0)
    result = agent.submit_answer({"answer": "jupiter"}, {"global_data": gd})
    (new,) = find(actions(result), "set_global_data")
    assert new["score"] == 0 and new["round"] == 2 and new["question_id"] == "q05"
    assert "Not quite" in result.to_dict()["response"]


def test_round_limit_jumps_to_final_score(agent):
    gd = state(agent, ["q07", "q02"], round_no=config.ROUNDS, score=3)
    acts = actions(agent.submit_answer({"answer": "a lion"}, {"global_data": gd}))
    assert find(acts, "change_step") == ["final_score"]
    (new,) = find(acts, "set_global_data")
    assert new["score"] == 4 and new["question"] == "" and new["question_id"] == ""


def test_full_game_ends_after_rounds(agent):
    gd = state(agent, [q["id"] for q in QUESTIONS][:config.ROUNDS])
    for n in range(1, config.ROUNDS + 1):
        answer = agent.questions[gd["question_id"]]["answers"][0]
        acts = actions(agent.submit_answer({"answer": answer}, {"global_data": gd}))
        gd = {**gd, **find(acts, "set_global_data")[0]}
        assert find(acts, "change_step") == (["final_score"] if n == config.ROUNDS else [])
    assert gd["score"] == config.ROUNDS


def test_no_question_in_play(agent):
    result = agent.submit_answer({"answer": "mars"}, {"global_data": {}})
    assert actions(result) == []


def test_start_game_picks_rounds_questions(agent):
    copy = TriviaAgent()
    agent.start_game({}, {}, {}, copy)
    gd = copy._global_data
    assert gd["round"] == 1 and gd["score"] == 0
    assert len([gd["question_id"], *gd["queue"]]) == config.ROUNDS
    assert gd["question"] == agent.questions[gd["question_id"]]["question"]


# --- the answer key never reaches the model -----------------------------------

def test_leak_detector_works():
    assert leaked('{"note": "the answer is Mars"}') == ["Mars"]
    assert leaked(json.dumps(QUESTIONS)) != []

def test_no_answer_in_any_global_data_the_handler_writes(agent):
    gd = state(agent, [q["id"] for q in QUESTIONS])
    for _ in range(len(QUESTIONS)):
        for guess in ("wrong guess", agent.questions[gd["question_id"]]["answers"][0]):
            acts = actions(agent.submit_answer({"answer": guess}, {"global_data": gd}))
            for written in find(acts, "set_global_data"):
                assert leaked(json.dumps(written)) == []
        gd = {**gd, **find(acts, "set_global_data")[0]}
        if not gd["question_id"]:
            break


def swaig_test_bin() -> str:
    local = Path(sys.executable).with_name("swaig-test")
    return str(local) if local.exists() else (shutil.which("swaig-test") or "swaig-test")


@pytest.fixture(scope="module")
def swml():
    out = subprocess.run(
        [swaig_test_bin(), str(RECIPE / "app.py"), "--dump-swml", "--raw"],
        capture_output=True, text=True, check=True, cwd=RECIPE,
    ).stdout
    return json.loads(out)


def ai_of(swml_doc):
    return next(v["ai"] for v in swml_doc["sections"]["main"] if "ai" in v)


def steps_of(swml_doc):
    return {s["name"]: s for s in ai_of(swml_doc)["prompt"]["contexts"]["default"]["steps"]}


def test_no_answer_anywhere_in_the_swml(swml):
    ai = ai_of(swml)
    assert ai["global_data"]["question"]                 # a question is in play...
    assert leaked(json.dumps(ai["global_data"])) == []   # ...but no answer
    assert leaked(json.dumps(ai["prompt"])) == []
    assert leaked(json.dumps(swml)) == []                # nor anywhere else in the document


# --- governance ------------------------------------------------------------------

def test_governance_final_score_has_no_tools(swml):
    assert steps_of(swml)["final_score"]["functions"] == []


def test_governance_play_step_only_submits(swml):
    play = steps_of(swml)["play"]
    assert play["functions"] == ["submit_answer"]
    assert play["valid_steps"] == []      # the model can't end the game early
    assert "${global_data.question}" in play["text"]
