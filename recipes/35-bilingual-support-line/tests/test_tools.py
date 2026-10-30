"""Handler tests plus governance assertions on the SWML that swaig-test dumps."""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

RECIPE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RECIPE))

import config  # noqa: E402
from app import BilingualSupportAgent  # noqa: E402

VERIFIED = {"global_data": {"account_id": "100877"}}


@pytest.fixture(scope="module")
def agent():
    return BilingualSupportAgent()


def actions(result):
    return result.to_dict().get("action", [])


def find(acts, key):
    return [a[key] for a in acts if key in a]


def payload(result):
    return json.loads(result.to_dict()["response"])  # every tool answers in JSON, never prose


# --- handler tests --------------------------------------------------------

def test_lookup_match_projects_public_fields_and_moves_to_help(agent):
    result = agent.lookup_account({"account_number": "100-234", "zip": "74101"}, {})
    assert payload(result) == {"found": True, "first_name": "Dana", "plan": "fiber-500"}
    acts = actions(result)
    assert find(acts, "set_global_data") == [
        {"account_id": "100234", "account": {"first_name": "Dana", "plan": "fiber-500"}}
    ]
    assert find(acts, "change_step") == ["help"]


def test_lookup_never_leaks_internal_fields(agent):
    text = json.dumps(agent.lookup_account({"account_number": "100877", "zip": "74103"}, {}).to_dict())
    assert "internal_risk_flag" not in text and "billing_notes" not in text and "courtesy" not in text


def test_lookup_wrong_zip_stays_in_identify(agent):
    result = agent.lookup_account({"account_number": "100234", "zip": "74199"}, {})
    assert payload(result) == {"found": False, "reason": "no_match"}
    assert actions(result) == []


def test_outage_uses_verified_zip(agent):
    assert payload(agent.check_outage({}, VERIFIED)) == {
        "outage": True, "cause": "fiber_cut", "restore_eta": "2026-10-31T14:00:00-05:00"}
    assert payload(agent.check_outage({"zip": "74103"}, {"global_data": {"account_id": "100234"}})) == {
        "outage": False}  # a model-supplied zip is ignored


def test_balance(agent):
    assert payload(agent.get_balance({}, {"global_data": {"account_id": "101555"}})) == {
        "amount_due": 79.5, "currency": "USD", "due_date": "2026-11-02"}


@pytest.mark.parametrize("tool", ["check_outage", "get_balance"])
def test_account_tools_refuse_unverified(agent, tool):
    assert payload(getattr(agent, tool)({}, {})) == {"error": "not_verified"}


def test_responses_are_language_neutral(agent):
    """Same data whatever language the call is in: no sentences in either language."""
    results = [
        agent.lookup_account({"account_number": "100234", "zip": "74101"}, {}),
        agent.check_outage({}, VERIFIED),
        agent.get_balance({}, VERIFIED),
    ]
    for r in results:
        text = r.to_dict()["response"]
        assert isinstance(json.loads(text), dict)
        for word in (" the ", " your ", " is ", " el ", " su ", " es "):
            assert word not in f" {text.lower()} "


# --- governance: read the SWML exactly as swaig-test dumps it ---------------

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


def test_swml_has_both_languages_with_their_own_voices_and_fillers(swml):
    langs = {lang["code"]: lang for lang in ai_of(swml)["languages"]}
    assert set(langs) == {"en-US", "es"}
    assert langs["en-US"]["voice"] == "gcloud.en-US-Neural2-F"
    assert langs["es"]["voice"] == "gcloud.es-US-Neural2-A"
    assert langs["en-US"]["voice"] != langs["es"]["voice"]
    assert "Un momento, lo reviso." in langs["es"]["function_fillers"]
    assert "One moment while I check." in langs["en-US"]["function_fillers"]
    assert ai_of(swml)["params"]["languages_enabled"] is True


def test_swml_languages_match_config(swml):
    dumped = [(lang["name"], lang["code"], lang["voice"]) for lang in ai_of(swml)["languages"]]
    assert dumped == [(lang["name"], lang["code"], lang["voice"]) for lang in config.LANGUAGES]


def test_internal_step_fillers_exist_per_language(swml):
    fillers = json.dumps(swml)
    for lang in config.LANGUAGES:
        for phrase in lang["step_fillers"]:
            assert json.dumps(phrase)[1:-1] in fillers


def test_governance_account_tools_absent_until_verified(swml):
    steps = steps_of(swml)
    assert steps["identify"]["functions"] == ["lookup_account"]
    assert steps["identify"]["valid_steps"] == []  # only the handler moves the call
    assert "get_balance" not in steps["identify"]["functions"]
    assert sorted(steps["help"]["functions"]) == ["check_outage", "get_balance"]
    assert steps["wrap_up"]["functions"] == []


def test_governance_wrap_up_is_terminal(swml):
    # Without valid_steps the platform offers next_step on the last step, and the model can
    # loop on it (seen live in #7, #10, #12, #13). The last step ends the flow.
    final = steps_of(swml)["wrap_up"]
    assert final["functions"] == [] and final["valid_steps"] == [] and final["end"] is True
