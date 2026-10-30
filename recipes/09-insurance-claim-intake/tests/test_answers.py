"""Regression tests for the live failure: gather answers are checked in code, not trusted.

On live calls fc0c53b7 and abbbb168 the model submitted the policy number as the incident
date and then asked for a phone number that isn't in the form. These pin both down.
"""
import json
import sys
from datetime import date
from pathlib import Path

import pytest

RECIPE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RECIPE))

import answers  # noqa: E402
import claims  # noqa: E402
import config  # noqa: E402
from test_tools import FNOL, actions, agent, find, isolated, raw, steps  # noqa: E402,F401

TODAY = date(2026, 10, 30)


# --- the exact failure: a policy number given as the date -------------------------

@pytest.mark.parametrize("words", ["POL-0101", "P O L zero one zero one", "pol 0101",
                                   "my policy number is POL 0101"])
def test_policy_number_shaped_date_is_rejected(words):
    value, reason = answers.check_incident_date(words, TODAY)
    assert value is None and "policy number" in reason


def test_check_tool_rejects_policy_number_as_date_with_a_re_ask(agent):
    response = agent._checker("incident_date")({"words": "POL-0101"}, raw()).to_dict()["response"]
    assert response.startswith("Not accepted") and "On what date" in response


def test_submit_claim_refuses_the_live_failure_then_files_the_correction(agent):
    bad = {**FNOL, "incident_date": "POL-0101"}
    result = agent.submit_claim({}, raw({"fnol": bad}))
    assert claims.load_all() == {} and not find(actions(result), "hold")
    gd = find(actions(result), "set_global_data")[0]
    assert gd["fix_field"] == "incident_date"
    assert "policy number" in result.to_dict()["response"]
    # The model re-asks and passes the caller's words; code applies them to that field only.
    acts = actions(agent.submit_claim({"answer": "October 28"}, raw(gd)))
    assert find(acts, "hold") and claims.get("CL-0001")["incident_date"].endswith("-10-28")


def test_a_correction_cannot_overwrite_a_field_code_did_not_flag(agent):
    acts = actions(agent.submit_claim({"answer": "POL-9999"}, raw({"fnol": FNOL})))
    assert find(acts, "hold") and claims.get("CL-0001")["policy_number"] == "POL-0101"


# --- incident date ---------------------------------------------------------------

@pytest.mark.parametrize("words,iso", [
    ("October 28th, 2026", "2026-10-28"), ("the twenty eighth of October", "2026-10-28"),
    ("October 28", "2026-10-28"), ("December 3", "2025-12-03"),  # no year: most recent past
    ("yesterday", "2026-10-29"), ("10/28/2026", "2026-10-28"), ("2026-10-28", "2026-10-28"),
])
def test_incident_date_resolves_to_a_real_past_date(words, iso):
    assert answers.check_incident_date(words, TODAY) == (iso, None)


@pytest.mark.parametrize("words,fragment", [
    ("November 5 2026", "future"), ("February 30 2026", "doesn't exist"),
    ("March 3 2019", "too long ago"), ("Main and 3rd", "didn't catch"), ("", "didn't catch"),
    ("0101", "didn't catch"), ("1 2 26", "Did you mean"),
])
def test_bad_incident_dates_are_rejected(words, fragment):
    value, reason = answers.check_incident_date(words, TODAY)
    assert value is None and fragment in reason


# --- policy number, location, description, injuries -----------------------------

@pytest.mark.parametrize("words", ["POL-0101", "pol 0101", "P O L zero one zero one",
                                   "P.O.L. 0 1 0 1", "it's POL oh one oh one"])
def test_policy_number_normalizes(words):
    assert answers.check_policy_number(words) == ("POL-0101", None)


@pytest.mark.parametrize("words", ["October 28", "0101", "POL-01", "POL-010199", "policy", ""])
def test_bad_policy_numbers_are_rejected(words):
    value, reason = answers.check_policy_number(words)
    assert value is None and "P O L" in reason


@pytest.mark.parametrize("words", ["yes", "no", "October 28th", "POL-0101", "ok", ""])
def test_bad_locations_are_rejected(words):
    assert answers.check_location(words)[0] is None


def test_location_and_description_accept_real_answers():
    assert answers.check_location("Main and 3rd") == ("Main and 3rd", None)
    assert answers.check_location("the Costco on 5th Street") == ("the Costco on 5th Street", None)
    assert answers.check_description("Rear-ended at a red light")[0]
    assert answers.check_description("car")[0] is None


@pytest.mark.parametrize("words,value", [
    ("no", False), ("No, nobody was hurt", False), ("no one", False), (False, False),
    ("yes", True), ("Yes, my passenger hurt her neck", True), (True, True),
])
def test_injuries_yes_no(words, value):
    assert answers.check_injuries(words) == (value, None)


@pytest.mark.parametrize("words", ["I'm not sure", "maybe", "October 28", ""])
def test_unclear_injuries_answer_is_re_asked(words):
    value, reason = answers.check_injuries(words)
    assert value is None and "yes or no" in reason


# --- caller ID comes from the call, never from a question ------------------------

def test_caller_number_comes_from_call_data(agent, steps):
    agent.submit_claim({}, raw({"fnol": FNOL}))
    assert claims.get("CL-0001")["caller"] == "+15550100"  # raw_data["caller_id_num"]
    questions = steps["intake"]["gather_info"]["questions"]
    assert not any("phone" in json.dumps(q).lower() for q in questions)


# --- governance: the gather as swaig-test dumps it -------------------------------

def test_governance_each_question_unlocks_only_its_own_check(steps):
    gather = steps["intake"]["gather_info"]
    assert gather["isolated"] is True and gather["completion_action"] == "submit"
    qs = {q["key"]: q for q in gather["questions"]}
    assert list(qs) == list(claims.FIELDS)
    for key in ("policy_number", "incident_date", "location", "injuries"):
        assert qs[key]["functions"] == [f"check_{key}"]
    assert "functions" not in qs["description"]
    assert qs["incident_date"].get("confirm") and qs["injuries"].get("confirm")
    assert qs["injuries"]["type"] == "boolean"
    for name in ("submit", "connected", "callback"):
        assert not any(f.startswith("check_") for f in steps[name]["functions"])


def test_model_choice_comes_from_config():
    a = __import__("app").ClaimIntakeAgent()
    assert a._prompt_llm_params["model"] == config.MODEL
