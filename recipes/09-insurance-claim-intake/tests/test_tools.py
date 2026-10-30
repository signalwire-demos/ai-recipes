"""Handler tests call the SWAIG handlers directly and assert on FunctionResult actions.
Governance tests read the SWML exactly as swaig-test dumps it.
"""
import asyncio
import base64
import json
import shutil
import subprocess
import sys
from pathlib import Path

import jsonschema_rs
import pytest
from starlette.requests import Request

RECIPE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RECIPE))

import answers  # noqa: E402
import claims  # noqa: E402
import config  # noqa: E402
from app import ClaimIntakeAgent  # noqa: E402

ADJUSTER, FROM = "+15550142", "+15550143"
FNOL = {"policy_number": "POL-0101", "incident_date": "October 28", "location": "Main and 3rd",
        "description": "Rear-ended at a red light", "injuries": False}
CLEAN = {**FNOL, "incident_date": answers.check_incident_date("October 28")[0]}  # ISO, past
SCHEMA = json.loads(config.CLAIM_SCHEMA_FILE.read_text())


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CLAIMS_FILE", tmp_path / "claims.json")
    monkeypatch.setattr(config, "ADJUSTER_NUMBER", ADJUSTER)
    monkeypatch.setattr(config, "FROM_NUMBER", FROM)


@pytest.fixture(scope="module")
def agent():
    a = ClaimIntakeAgent(basic_auth=("u", "p"))
    a.manual_set_proxy_url("https://example.ngrok.app")
    return a


def raw(gd=None):
    return {"global_data": gd or {}, "call_id": "call-abc", "caller_id_num": "+15550100"}


def actions(result):
    return result.to_dict().get("action", [])


def find(acts, key):
    return [a[key] for a in acts if key in a]


def rpc_dial_of(acts):
    rpcs = [v["execute_rpc"] for a in find(acts, "SWML") for v in a["sections"]["main"]
            if "execute_rpc" in v]
    return next(r for r in rpcs if r["method"] == "dial")


def get_brief(agent, query, auth=("u", "p")):
    """Call the /brief route the way the platform's dest_swml fetch would."""
    route = next(r for r in agent.as_router().routes if r.path == "/brief")
    headers = []
    if auth:
        headers.append((b"authorization", b"Basic " + base64.b64encode(":".join(auth).encode())))
    req = Request({"type": "http", "method": "GET", "path": "/brief", "headers": headers,
                   "query_string": query.encode()})
    res = asyncio.run(route.endpoint(req))
    return res.status_code, json.loads(res.body)


# --- submit_claim ----------------------------------------------------------

def test_submit_writes_a_claim_matching_the_schema(agent):
    acts = actions(agent.submit_claim({}, raw({"fnol": FNOL})))
    assert find(acts, "set_global_data") == [{"claim_id": "CL-0001"}]
    claim = claims.get("CL-0001")
    assert jsonschema_rs.validator_for(SCHEMA).is_valid(claim)
    assert claim["status"] == "awaiting_adjuster" and claim["caller"] == "+15550100"
    assert {k: claim[k] for k in claims.FIELDS} == CLEAN


def test_schema_rejects_a_bad_record():
    bad = {"claim_id": "CL-1", "status": "lost"}
    assert not jsonschema_rs.validator_for(SCHEMA).is_valid(bad)
    with pytest.raises(jsonschema_rs.ValidationError):
        claims.save(bad)


def test_submit_holds_caller_and_rpc_dials_adjuster(agent):
    acts = actions(agent.submit_claim({}, raw({"fnol": FNOL})))
    hold = find(acts, "hold")[0]
    assert hold == {"timeout": config.HOLD_TIMEOUT, "step": "connected", "timeout_step": "callback"}
    dial = rpc_dial_of(acts)["params"]
    assert dial["devices"]["params"] == {"to_number": ADJUSTER, "from_number": FROM}
    assert dial["dest_swml"] == "https://u:p@example.ngrok.app/brief?claim=CL-0001&call=call-abc"


def test_briefing_swml_is_built_from_the_claim_fields(agent):
    agent.submit_claim({}, raw({"fnol": {**FNOL, "injuries": True}}))
    assert get_brief(agent, "claim=CL-0001", auth=None)[0] == 401
    status, swml = get_brief(agent, "claim=CL-0001&call=call-abc")
    assert status == 200
    main = swml["sections"]["main"]
    spoken = main[0]["play"]["url"]
    for value in ("CL-0001", "POL-0101", "October 28", "Main and 3rd", "Rear-ended at a red light",
                  "Injuries were reported"):
        assert value in spoken
    switch = main[2]["switch"]
    accept = switch["case"][config.ACCEPT_DIGIT]
    assert accept[0]["execute_rpc"] == {"method": "ai_unhold", "call_id": "call-abc", "params": {}}
    assert accept[1]["join_conference"]["name"] == claims.get("CL-0001")["conference"]
    assert get_brief(agent, "claim=CL-9999")[0] == 404


def test_submit_with_missing_fields_does_not_file(agent):
    result = agent.submit_claim({}, raw({"fnol": {**FNOL, "location": ""}}))
    assert find(actions(result), "set_global_data")[0]["fix_field"] == "location"
    assert "location" in result.to_dict()["response"] and not find(actions(result), "hold")
    assert claims.load_all() == {}


def test_submit_twice_does_not_dial_again(agent):
    assert actions(agent.submit_claim({}, raw({"claim_id": "CL-0001"}))) == []


def test_no_adjuster_configured_goes_straight_to_callback(agent, monkeypatch):
    monkeypatch.setattr(config, "ADJUSTER_NUMBER", "")
    acts = actions(agent.submit_claim({}, raw({"fnol": FNOL})))
    assert find(acts, "change_step") == ["callback"] and not find(acts, "hold")


# --- join_adjuster / promise_callback ----------------------------------------

def test_join_adjuster_bridges_into_the_claim_conference(agent):
    agent.submit_claim({}, raw({"fnol": FNOL}))
    acts = actions(agent.join_adjuster({}, raw({"claim_id": "CL-0001"})))
    verb = find(acts, "SWML")[0]["sections"]["main"][0]["join_conference"]
    assert verb["name"] == claims.get("CL-0001")["conference"]
    assert claims.get("CL-0001")["status"] == "bridged"


def test_no_answer_path_writes_a_callback_record(agent):
    agent.submit_claim({}, raw({"fnol": FNOL}))
    result = agent.promise_callback({"preferred_time": "tomorrow after 2pm"},
                                    raw({"claim_id": "CL-0001"}))
    claim = claims.get("CL-0001")
    assert claim["status"] == "callback_promised"
    assert claim["callback"]["number"] == "+15550100"
    assert claim["callback"]["preferred_time"] == "tomorrow after 2pm"
    assert jsonschema_rs.validator_for(SCHEMA).is_valid(claim)
    assert find(actions(result), "hangup")


def test_promise_callback_needs_a_time(agent):
    assert actions(agent.promise_callback({"preferred_time": " "}, raw({"claim_id": "CL-0001"}))) == []


# --- governance: the SWML swaig-test dumps -----------------------------------

def swaig_test_bin() -> str:
    local = Path(sys.executable).with_name("swaig-test")
    return str(local) if local.exists() else (shutil.which("swaig-test") or "swaig-test")


@pytest.fixture(scope="module")
def steps():
    out = subprocess.run([swaig_test_bin(), str(RECIPE / "app.py"), "--dump-swml", "--raw"],
                         capture_output=True, text=True, check=True, cwd=RECIPE).stdout
    ai = next(v["ai"] for v in json.loads(out)["sections"]["main"] if "ai" in v)
    return {s["name"]: s for s in ai["prompt"]["contexts"]["default"]["steps"]}


def test_governance_each_step_has_exactly_one_door(steps):
    assert steps["intake"]["functions"] == []
    assert steps["submit"]["functions"] == ["submit_claim"]
    assert steps["connected"]["functions"] == ["join_adjuster"]
    assert steps["callback"]["functions"] == ["promise_callback"]
    assert all(s["valid_steps"] == [] for s in steps.values())  # no next_step tool anywhere


def test_governance_bridge_tool_absent_until_adjuster_accepts(steps):
    for name in ("intake", "submit", "callback"):
        assert "join_adjuster" not in steps[name]["functions"]
