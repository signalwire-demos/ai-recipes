"""Agent tests: the handler, config selection, payload capture, and SWML governance per config."""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

RECIPE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RECIPE))

import app  # noqa: E402
import config  # noqa: E402


@pytest.fixture(scope="module")
def agent():
    return app.LatencyLabAgent()


def test_check_hours(agent):
    assert agent.check_hours({"day": "Saturday"}, {}).to_dict()["response"] == "saturday: open 10:00 to 14:00"
    assert agent.check_hours({"day": "sunday"}, {}).to_dict()["response"] == "sunday: closed"
    assert "isn't a day" in agent.check_hours({"day": "someday"}, {}).to_dict()["response"]


@pytest.mark.parametrize("q,expected", [({"config": "mini-rime"}, "mini-rime"), ({}, app.DEFAULT_CONFIG),
                                        ({"config": "gpt-5"}, app.DEFAULT_CONFIG),
                                        ({"model": "gpt-5"}, app.DEFAULT_CONFIG)])
def test_pick_config_is_whitelisted(q, expected):
    assert app.pick_config(q) == expected


def test_on_summary_files_payload_under_its_config(agent, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "RUNS_DIR", tmp_path)
    agent.on_summary({}, {"call_id": "abc/../123", "global_data": {"lab_config": "mini-gcloud"}, "raw_call_log": []})
    saved = list(tmp_path.glob("*/*.json"))
    assert [p.relative_to(tmp_path).as_posix() for p in saved] == ["mini-gcloud/abc123.json"]
    assert json.loads(saved[0].read_text())["global_data"]["lab_config"] == "mini-gcloud"


def test_on_summary_ignores_payload_without_known_config(agent, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "RUNS_DIR", tmp_path)
    agent.on_summary({}, {"call_id": "x", "global_data": {"lab_config": "evil"}})
    agent.on_summary(None, None)
    assert list(tmp_path.rglob("*.json")) == []


# --- governance: the SWML for each config differs ONLY in model and voice ---

def swaig_test_bin() -> str:
    local = Path(sys.executable).with_name("swaig-test")
    return str(local) if local.exists() else (shutil.which("swaig-test") or "swaig-test")


def dump(name):
    out = subprocess.run([swaig_test_bin(), str(RECIPE / "app.py"), "--dump-swml", "--raw",
                          "--query-params", json.dumps({"config": name})],
                         capture_output=True, text=True, check=True, cwd=RECIPE).stdout
    return next(v["ai"] for v in json.loads(out)["sections"]["main"] if "ai" in v)


@pytest.fixture(scope="module")
def dumps():
    return {name: dump(name) for name in config.CONFIGS}


def comparable(ai):
    """The AI verb minus the two variables under test and per-render tokens/URLs."""
    ai = json.loads(json.dumps(ai))
    ai["prompt"].pop("model")
    ai.pop("languages")
    ai.pop("global_data")
    ai["SWAIG"].get("defaults", {}).pop("web_hook_url", None)  # per-process random basic auth
    for fn in ai["SWAIG"].get("functions", []):
        fn.pop("web_hook_url", None)
    ai.pop("post_prompt_url", None)
    return ai


def test_each_config_sets_its_model_and_voice(dumps):
    for name, ai in dumps.items():
        assert ai["prompt"]["model"] == config.CONFIGS[name]["model"]
        assert ai["prompt"]["temperature"] == config.TEMPERATURE
        assert [lang["voice"] for lang in ai["languages"]] == [config.CONFIGS[name]["voice"]]
        assert ai["global_data"] == {"lab_config": name}


def test_governance_everything_else_is_identical(dumps):
    baseline = comparable(dumps[app.DEFAULT_CONFIG])
    for name, ai in dumps.items():
        assert comparable(ai) == baseline, f"{name} differs from {app.DEFAULT_CONFIG} beyond model/voice"


def test_governance_step_tools_and_post_prompt(dumps):
    ai = dumps[app.DEFAULT_CONFIG]
    step = ai["prompt"]["contexts"]["default"]["steps"][0]
    assert step["functions"] == ["check_hours"] and step["valid_steps"] == []
    assert "post_prompt_url" in ai  # without it there is no timing payload to measure
