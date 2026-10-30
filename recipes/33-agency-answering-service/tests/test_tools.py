"""Handler tests, tenant resolution, and cross-tenant isolation (SWML dumps and SWAIG exec)."""
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

RECIPE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RECIPE))

import app  # noqa: E402
import config  # noqa: E402

NUMBERS = {"TENANT_1": "+15550111", "TENANT_2": "+15550112", "TENANT_3": "+15550113",
           "DENTAL_FRONT_DESK": "+15550121", "HVAC_ON_CALL": "+15550122", "LAW_INTAKE_DESK": ""}
EXPECTED_TOOLS = {
    "dental": {"check_hours", "take_message", "book_appointment", "transfer_call"},
    "hvac": {"check_hours", "take_message", "dispatch_technician"},
    "law": {"check_hours", "take_message", "request_consultation", "transfer_call"},
    "default": {"take_message"},
}
TENANT_ONLY = {"book_appointment": "dental", "dispatch_technician": "hvac", "request_consultation": "law"}


@pytest.fixture(autouse=True)
def env(monkeypatch, tmp_path):
    for k, v in NUMBERS.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setattr(config, "MESSAGES_FILE", tmp_path / "messages.jsonl")


def tenant(tid):
    return app.load_tenants()[tid]


def per_call(query=None, to=None):
    """Exactly what the SDK does per request: a fresh agent passed through the callback."""
    agent = app.AnsweringServiceAgent()
    app.configure(query or {}, {"call": {"to": to}} if to else {}, {}, agent)
    return agent


def actions(result):
    return result.to_dict().get("action", [])


def swml_verbs(result):
    return [a["SWML"]["sections"]["main"][0] for a in actions(result) if "SWML" in a]


def records():
    return [json.loads(line) for line in config.MESSAGES_FILE.read_text().splitlines()]


def at(monkeypatch, hhmm, weekday=0):  # weekday 0 = a Monday
    h, m = map(int, hhmm.split(":"))
    fixed = datetime(2026, 11, 2 + weekday, h, m, tzinfo=ZoneInfo("America/Chicago"))
    monkeypatch.setattr(app, "now", lambda tz: fixed)


# --- tenant resolution ----------------------------------------------------

@pytest.mark.parametrize("to,tid", [("+15550111", "dental"), ("+1 (555) 0112", "hvac"), ("15550113", "law")])
def test_called_number_picks_tenant(to, tid):
    assert app.resolve_tenant({}, {"call": {"to": to}})["id"] == tid


def test_called_number_beats_query_param():
    assert app.resolve_tenant({"tenant": "law"}, {"call": {"to": "+15550111"}})["id"] == "dental"


def test_query_param_fallback_for_unmapped_number():
    assert app.resolve_tenant({"tenant": "hvac"}, {"call": {"to": "+15550199"}})["id"] == "hvac"


@pytest.mark.parametrize("q", [{}, {"tenant": "nope"}, {"tenant": "../config"}, {"tenant": "DENTAL"}])
def test_unknown_tenant_gets_safe_default(q):
    cfg = app.resolve_tenant(q, {})
    assert cfg is config.DEFAULT_TENANT and cfg["tools"] == ["take_message"]


def test_query_param_can_be_disabled(monkeypatch):
    monkeypatch.setattr(config, "ALLOW_TENANT_QUERY", False)
    assert app.resolve_tenant({"tenant": "hvac"}, {})["id"] == "default"


def test_new_yaml_is_picked_up_without_restart(monkeypatch, tmp_path):
    for p in config.TENANTS_DIR.glob("*.yaml"):
        (tmp_path / p.name).write_text(p.read_text())
    (tmp_path / "spa.yaml").write_text((config.TENANTS_DIR / "dental.yaml").read_text()
                                       .replace("id: dental", "id: spa").replace("${TENANT_1}", "+15550114"))
    monkeypatch.setattr(config, "TENANTS_DIR", tmp_path)
    assert app.resolve_tenant({}, {"call": {"to": "+15550114"}})["id"] == "spa"


# --- handlers -------------------------------------------------------------

def test_check_hours():
    assert "open 08:00 to 13:00" in app.check_hours(tenant("dental"), {"day": "Friday"}).to_dict()["response"]
    assert "closed" in app.check_hours(tenant("law"), {"day": "saturday"}).to_dict()["response"]
    assert "isn't a day" in app.check_hours(tenant("law"), {"day": "someday"}).to_dict()["response"]


def test_take_message_tags_tenant_from_config_not_args():
    app.take_message(tenant("law"), {"caller_name": "Sam", "callback_number": "+15550142",
                                     "message": "call me", "tenant": "dental"})
    assert records()[0]["tenant"] == "law" and records()[0]["kind"] == "message"


def test_book_appointment():
    r = app.book_appointment(tenant("dental"), {"patient_name": "Ana", "reason": "cleaning"})
    assert "saved" in r.to_dict()["response"] and records()[0]["kind"] == "appointment_request"


def test_request_consultation_validates_practice_area():
    assert "handles" in app.request_consultation(tenant("law"), {"name": "Bo", "practice_area": "criminal"}) \
        .to_dict()["response"]
    app.request_consultation(tenant("law"), {"name": "Bo", "practice_area": "estate"})
    assert records()[0]["practice_area"] == "estate"


def test_dispatch_emergency_connects_on_call_any_hour(monkeypatch):
    at(monkeypatch, "03:00", weekday=6)
    r = app.dispatch_technician(tenant("hvac"), {"address": "1 Elm", "issue": "no heat", "emergency": True})
    assert swml_verbs(r) == [{"connect": {"to": "+15550122"}}]


def test_dispatch_non_emergency_opens_ticket():
    r = app.dispatch_technician(tenant("hvac"), {"address": "1 Elm", "issue": "noisy", "emergency": False})
    assert actions(r) == [] and records()[0]["kind"] == "service_request"


def test_transfer_open_connects_to_yaml_number(monkeypatch):
    at(monkeypatch, "10:00")
    r = app.transfer_call(tenant("dental"), {"target": "front_desk"})
    assert swml_verbs(r) == [{"connect": {"to": "+15550121"}}]


def test_transfer_closed_refuses(monkeypatch):
    at(monkeypatch, "18:30")
    r = app.transfer_call(tenant("dental"), {"target": "front_desk"})
    assert actions(r) == [] and "closed" in r.to_dict()["response"]


def test_transfer_unknown_or_unconfigured_target_refuses(monkeypatch):
    at(monkeypatch, "10:00")
    assert actions(app.transfer_call(tenant("dental"), {"target": "+15550100"})) == []
    assert actions(app.transfer_call(tenant("law"), {"target": "intake_desk"})) == []  # blank in env


# --- cross-tenant leakage -------------------------------------------------

def tool_names(agent):
    swml = json.loads(agent._render_swml())
    ai = next(v["ai"] for v in swml["sections"]["main"] if "ai" in v)
    return {f["function"] for f in ai["SWAIG"].get("functions", [])}, ai


@pytest.mark.parametrize("tid", ["dental", "hvac", "law"])
def test_each_tenant_gets_exactly_its_tools(tid):
    names, ai = tool_names(per_call({"tenant": tid}))
    assert names == EXPECTED_TOOLS[tid]
    assert ai["global_data"]["tenant"] == tid
    for tool, owner in TENANT_ONLY.items():
        assert (tool in names) == (owner == tid)


def test_interleaved_requests_do_not_leak():
    master = app.agent
    dental, hvac = per_call({"tenant": "dental"}), per_call(to="+15550112")
    assert "book_appointment" not in tool_names(hvac)[0]
    assert "dispatch_technician" not in tool_names(dental)[0]
    assert tool_names(per_call({}))[0] == EXPECTED_TOOLS["default"]
    assert "not found" in str(master.on_function_call("book_appointment", {}, {}))  # master has no tenant tools


def test_transfer_enum_lists_only_own_targets():
    _, ai = tool_names(per_call({"tenant": "dental"}))
    fn = next(f for f in ai["SWAIG"]["functions"] if f["function"] == "transfer_call")
    assert fn["parameters"]["properties"]["target"]["enum"] == ["front_desk"]


# --- the same checks through swaig-test, exactly as CI and the README run them ---

def swaig_test(*args, tmp=None):
    local = Path(sys.executable).with_name("swaig-test")
    exe = str(local) if local.exists() else (shutil.which("swaig-test") or "swaig-test")
    env = {**os.environ, "MESSAGES_FILE": str(config.MESSAGES_FILE)}  # keep test writes out of data/
    return subprocess.run([exe, str(RECIPE / "app.py"), *args], capture_output=True, text=True, cwd=RECIPE, env=env)


@pytest.mark.parametrize("tid", ["dental", "hvac", "law", "nobody"])
def test_governance_swml_dump_per_tenant(tid):
    out = swaig_test("--dump-swml", "--raw", "--query-params", json.dumps({"tenant": tid}))
    ai = next(v["ai"] for v in json.loads(out.stdout)["sections"]["main"] if "ai" in v)
    assert {f["function"] for f in ai["SWAIG"]["functions"]} == EXPECTED_TOOLS.get(tid, EXPECTED_TOOLS["default"])


@pytest.mark.parametrize("tool,owner", TENANT_ONLY.items())
def test_governance_other_tenants_cannot_execute_tool(tool, owner):
    for tid in ("dental", "hvac", "law"):
        out = swaig_test("--query-params", json.dumps({"tenant": tid}), "--exec", tool)
        if tid == owner:
            assert "not found in agent" not in out.stdout + out.stderr
        else:
            assert out.returncode != 0 and "not found in agent" in out.stdout + out.stderr
