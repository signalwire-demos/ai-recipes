"""Handler tests plus governance assertions against the SWML that swaig-test dumps.

Wire names: swml_change_step() emits {"change_step": ...}, update_global_data()
emits {"set_global_data": ...}, connect() emits {"SWML": {...}}.
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
from app import OrderStatusAgent  # noqa: E402

HIDDEN_FIELDS = ["risk_flag", "prior_refunds", "internal_notes", "total"]  # in the record, never projected
THRESHOLD_NAMES = ["AUTO_CREDIT_LIMIT", "MAX_PRIOR_REFUNDS", "REFUNDABLE_STATUSES", "threshold", "limit"]


@pytest.fixture(scope="module")
def agent():
    return OrderStatusAgent()


@pytest.fixture(autouse=True)
def tmp_credits(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CREDITS_FILE", tmp_path / "credits.jsonl")


def actions(result):
    return result.to_dict().get("action", [])


def find(acts, key):
    return [a[key] for a in acts if key in a]


def verified_gd(agent, order_number, postal_code):
    acts = actions(agent.verify_identity({"order_number": order_number, "postal_code": postal_code}, {}))
    return find(acts, "set_global_data")[0]


def expand(text: str, gd: dict) -> str:
    """What the platform does with ${global_data.a.b} in step text at runtime."""
    def lookup(m):
        value = gd
        for key in m.group(1).split("."):
            value = value[key]
        return str(value)
    return re.sub(r"\$\{global_data\.([\w.]+)\}", lookup, text)


# --- verify_identity (same shape as recipe 08) ------------------------------

def test_verify_loads_full_record_and_changes_step(agent):
    acts = actions(agent.verify_identity({"order_number": "100-234", "postal_code": "74101"}, {}))
    gd = find(acts, "set_global_data")[0]
    assert gd["verified"] is True
    assert gd["order"]["risk_flag"] is False and gd["order"]["internal_notes"]  # full record is stored
    assert gd["order"]["items_text"] == "1 x trail running shoes, 2 x wool socks"
    assert find(acts, "change_step") == ["order_status"]


def test_failed_verify_does_not_change_step(agent):
    acts = actions(agent.verify_identity({"order_number": "100234", "postal_code": "99999"}, {}))
    assert find(acts, "change_step") == []
    assert find(acts, "set_global_data") == [{"verify_failures": 1}]


def test_third_failure_jumps_to_escalate(agent):
    acts = actions(agent.verify_identity({"order_number": "1", "postal_code": "2"},
                                         {"global_data": {"verify_failures": 2}}))
    assert find(acts, "change_step") == ["escalate"]


# --- request_refund: the rule decides, the model narrates --------------------

def test_small_clean_order_is_auto_credited(agent):
    gd = verified_gd(agent, "100235", "74012")
    result = agent.request_refund({"reason": "late"}, {"global_data": gd})
    acts = actions(result)
    assert find(acts, "change_step") == []
    assert find(acts, "set_global_data") == [{"refund": {"outcome": "credited", "ref": "CR-0001"}}]
    assert "$24.00" in result.to_dict()["response"]
    assert json.loads(config.CREDITS_FILE.read_text())["order_id"] == "ORD-0102"


@pytest.mark.parametrize("order_number,postal,why", [
    ("100236", "74133", "risk flag"),
    ("100234", "74101", "over the limit and not refundable yet"),
])
def test_other_orders_transfer_without_revealing_why(agent, order_number, postal, why):
    gd = verified_gd(agent, order_number, postal)
    result = agent.request_refund({"reason": "not received"}, {"global_data": gd})
    acts = actions(result)
    assert find(acts, "change_step") == ["escalate"], why
    assert find(acts, "set_global_data") == [{"refund": {"outcome": "transferred"}}]
    response = result.to_dict()["response"].lower()
    for leak in ("risk", "flag", "limit", "prior", "threshold", f"{config.AUTO_CREDIT_LIMIT:g}"):
        assert leak not in response
    assert not config.CREDITS_FILE.exists()


def test_refund_requires_verification(agent):
    assert agent.request_refund({"reason": "x"}, {}).to_dict()["response"] == "The caller is not verified."


def test_escalate_call(agent, monkeypatch):
    monkeypatch.setattr(config, "ESCALATION_NUMBER", "")
    assert find(actions(agent.escalate_call({}, {})), "hangup") == [True]
    monkeypatch.setattr(config, "ESCALATION_NUMBER", "+15550144")
    swml = find(actions(agent.escalate_call({}, {})), "SWML")[0]
    assert swml["sections"]["main"][0]["connect"]["to"] == "+15550144"


# --- governance: read the SWML exactly as swaig-test dumps it ---------------

def swaig_test_bin() -> str:
    local = Path(sys.executable).with_name("swaig-test")
    return str(local) if local.exists() else (shutil.which("swaig-test") or "swaig-test")


@pytest.fixture(scope="module")
def ai():
    out = subprocess.run(
        [swaig_test_bin(), str(RECIPE / "app.py"), "--dump-swml", "--raw"],
        capture_output=True, text=True, check=True, cwd=RECIPE,
    ).stdout
    return next(v["ai"] for v in json.loads(out)["sections"]["main"] if "ai" in v)


def steps_of(ai):
    return {s["name"]: s for s in ai["prompt"]["contexts"]["default"]["steps"]}


def test_governance_rendered_prompt_has_no_risk_or_threshold_fields(ai):
    visible = json.dumps({
        "prompt": ai["prompt"],
        "tools": [{k: v for k, v in f.items() if k != "web_hook_url"} for f in ai["SWAIG"]["functions"]],
        "global_data": ai.get("global_data", {}),
    })
    for name in HIDDEN_FIELDS + THRESHOLD_NAMES:
        assert name not in visible, name
    assert f"{config.AUTO_CREDIT_LIMIT:g}" not in visible


def test_governance_step_text_projects_only_curated_fields(ai):
    text = steps_of(ai)["order_status"]["text"]
    referenced = re.findall(r"\$\{global_data\.order\.(\w+)\}", text)
    assert referenced and set(referenced) == set(config.CURATED_FIELDS)
    assert re.findall(r"\$\{global_data\.(\w+)", text) == ["order"] * len(referenced)


def test_governance_expanded_step_text_hides_the_risk_record(agent, ai):
    gd = verified_gd(agent, "100236", "74133")          # the risk-flagged order
    rendered = expand(steps_of(ai)["order_status"]["text"], gd)
    assert "delivered on October 27" in rendered and "1 x headlamp" in rendered
    assert gd["order"]["internal_notes"] not in rendered
    for name in HIDDEN_FIELDS:
        assert name not in rendered
    assert str(gd["order"]["prior_refunds"]) not in rendered


def test_governance_verify_step_shape_matches_recipe_08(ai):
    steps = steps_of(ai)
    assert steps["verify_identity"]["functions"] == ["verify_identity"]
    assert steps["verify_identity"]["valid_steps"] == []
    assert steps["order_status"]["functions"] == ["request_refund"]
    assert steps["escalate"]["valid_steps"] == [] and steps["wrap_up"]["functions"] == []
