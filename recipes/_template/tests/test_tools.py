"""House style for recipe tests.

1. Call each SWAIG handler directly with fixture args / raw_data and assert on the
   FunctionResult actions (to_dict()["action"]). Wire names differ from the helper
   names: swml_change_step() emits {"change_step": ...} and update_global_data()
   emits {"set_global_data": ...}.
2. At least one governance assertion against the SWML that swaig-test dumps:
   which tools exist in which step.
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

RECIPE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RECIPE))

from app import TemplateAgent  # noqa: E402


@pytest.fixture(scope="module")
def agent():
    return TemplateAgent()


def actions(result):
    return result.to_dict().get("action", [])


def find(acts, key):
    return [a[key] for a in acts if key in a]


# --- handler tests --------------------------------------------------------

def test_open_day_sets_global_data_and_changes_step(agent):
    acts = actions(agent.check_hours({"day": "Monday"}, {"global_data": {}}))
    assert find(acts, "set_global_data") == [{"day": "monday", "hours": "09:00 to 17:00"}]
    assert find(acts, "change_step") == ["wrap_up"]


def test_closed_day_still_advances_with_closed(agent):
    acts = actions(agent.check_hours({"day": "sunday"}, {}))
    assert find(acts, "set_global_data") == [{"day": "sunday", "hours": "closed"}]
    assert find(acts, "change_step") == ["wrap_up"]


def test_invalid_day_does_not_advance(agent):
    result = agent.check_hours({"day": "someday"}, {})
    assert actions(result) == []
    assert "isn't a day" in result.to_dict()["response"]


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


def steps_of(swml_doc):
    ai = next(v["ai"] for v in swml_doc["sections"]["main"] if "ai" in v)
    return {s["name"]: s for s in ai["prompt"]["contexts"]["default"]["steps"]}


def test_governance_wrap_up_has_no_tools(swml):
    steps = steps_of(swml)
    assert "check_hours" not in steps["wrap_up"]["functions"]
    assert steps["wrap_up"]["functions"] == []


def test_governance_model_cannot_leave_lookup(swml):
    lookup = steps_of(swml)["lookup"]
    assert lookup["functions"] == ["check_hours"]
    assert lookup["valid_steps"] == []  # no next_step tool: only the handler moves the call
