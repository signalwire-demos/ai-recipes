import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE)); sys.modules.pop("snippet", None)  # noqa: E702
from snippet import deal, place_bet  # noqa: E402


def acts(result, key):
    return [a[key] for a in result.to_dict().get("action", []) if key in a]


@pytest.mark.parametrize("amount", [0, -5, 101, "ten", None])
def test_invalid_bet_does_not_change_step(amount):
    r = place_bet({"amount": amount}, {"global_data": {"chips": 100}})
    assert acts(r, "change_step") == [] and acts(r, "set_global_data") == []


def test_valid_bet_is_the_only_way_to_play():
    r = place_bet({"amount": 25}, {"global_data": {"chips": 100}})
    assert acts(r, "set_global_data") == [{"bet": 25, "chips": 75}]
    assert acts(r, "change_step") == ["play"]


def test_deal_without_a_bet_goes_back_to_bet():
    assert acts(deal({}, {"global_data": {"chips": 100}}), "change_step") == ["bet"]


def test_deal_with_a_bet_deals():
    r = deal({}, {"global_data": {"bet": 25}})
    assert "25 chips" in r.to_dict()["response"] and acts(r, "change_step") == []


@pytest.fixture(scope="module")
def steps():
    exe = Path(sys.executable).with_name("swaig-test")
    exe = str(exe) if exe.exists() else shutil.which("swaig-test")
    swml = json.loads(subprocess.run([exe, str(HERE / "snippet.py"), "--dump-swml", "--raw"],
                                     capture_output=True, text=True, check=True, cwd=HERE).stdout)
    ai = next(v["ai"] for v in swml["sections"]["main"] if "ai" in v)
    return {s["name"]: s for s in ai["prompt"]["contexts"]["default"]["steps"]}


def test_governance_model_cannot_reach_play_before_the_handler_allows_it(steps):
    assert steps["bet"]["valid_steps"] == []           # no next_step tool to call
    assert steps["bet"]["functions"] == ["place_bet"]  # and no way to deal from here
    assert "deal" not in steps["bet"]["functions"]


def test_governance_play_cannot_bet_again_or_wander(steps):
    assert steps["play"]["functions"] == ["deal"] and steps["play"]["valid_steps"] == []
