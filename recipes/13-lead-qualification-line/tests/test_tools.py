"""Handler tests, the disposition and scoring rule, the CRM sinks, and governance.

The key test: on_summary builds the CRM record from global_data only. It is handed a
post-prompt payload whose transcript and model summary say "hot lead", and the
handler-written global_data says otherwise. Any read of the transcript fails the test.
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path
from unittest import mock

import pytest

RECIPE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RECIPE))

import config  # noqa: E402
import disposition  # noqa: E402
from app import LeadQualificationAgent  # noqa: E402

FIXTURE = json.loads((RECIPE / "tests" / "fixtures" / "post_prompt.json").read_text())
HOT = {"budget_usd": 50_000, "timeline_months": 1, "is_decision_maker": True, "need": "contact_center"}


@pytest.fixture(scope="module")
def agent():
    return LeadQualificationAgent()


@pytest.fixture
def leads_file(tmp_path, monkeypatch):
    path = tmp_path / "leads.jsonl"
    monkeypatch.setattr(config, "LEADS_FILE", path)
    monkeypatch.setattr(config, "CRM_SINK", "file")
    return path


def actions(result):
    return result.to_dict().get("action", [])


def find(acts, key):
    return [a[key] for a in acts if key in a]


# --- handlers -------------------------------------------------------------

@pytest.mark.parametrize("tool,args,key,value", [
    ("record_budget", {"amount_usd": 25000}, "budget_usd", 25000),
    ("record_budget", {"amount_usd": "8000"}, "budget_usd", 8000),
    ("record_timeline", {"months": 3}, "timeline_months", 3),
    ("record_timeline", {"months": 99}, "timeline_months", config.MAX_TIMELINE_MONTHS),
    ("record_authority", {"is_decision_maker": True}, "is_decision_maker", True),
    ("record_authority", {"is_decision_maker": False}, "is_decision_maker", False),
    ("record_need", {"need": "Contact_Center"}, "need", "contact_center"),
])
def test_record_writes_typed_value(agent, tool, args, key, value):
    acts = actions(getattr(agent, tool)(args, {"global_data": {}}))
    assert find(acts, "set_global_data") == [{key: value}]
    assert find(acts, "change_step") == []  # other fields still missing


@pytest.mark.parametrize("tool,args", [
    ("record_budget", {"amount_usd": "lots"}),
    ("record_budget", {"amount_usd": -5}),
    ("record_timeline", {"months": "soon"}),
    ("record_authority", {"is_decision_maker": "maybe"}),
    ("record_need", {"need": "world_peace"}),
])
def test_record_rejects_bad_values(agent, tool, args):
    assert actions(getattr(agent, tool)(args, {"global_data": {}})) == []


def test_last_field_moves_to_wrap_up(agent):
    known = {k: v for k, v in HOT.items() if k != "need"}
    acts = actions(agent.record_need({"need": "contact_center"}, {"global_data": known}))
    assert find(acts, "set_global_data") == [{"need": "contact_center"}]
    assert find(acts, "change_step") == ["wrap_up"]


# --- disposition and scoring ------------------------------------------------

SCHEMA = {"call_id": (str, type(None)), "recorded_at": int, "budget_usd": (int, type(None)),
          "timeline_months": (int, type(None)), "is_decision_maker": (bool, type(None)),
          "need": (str, type(None)), "missing": list, "score": int, "tier": str}


def test_disposition_matches_schema():
    d = disposition.build_disposition(FIXTURE["global_data"], call_id="call-0113")
    assert set(d) == set(SCHEMA)
    for key, types in SCHEMA.items():
        assert isinstance(d[key], types), key
    assert d["tier"] in {name for _, name in config.TIERS}
    assert d["missing"] == []


def test_partial_lead_lists_missing_fields():
    d = disposition.build_disposition({"budget_usd": 20000})
    assert d["missing"] == ["timeline_months", "is_decision_maker", "need"]
    assert d["need"] is None and d["score"] == 1 and d["tier"] == "cold"


@pytest.mark.parametrize("lead,points,tier", [
    (HOT, 4, "hot"),
    ({**HOT, "budget_usd": 500}, 3, "warm"),
    ({**HOT, "budget_usd": 500, "timeline_months": 12}, 2, "warm"),
    (FIXTURE["global_data"], 0, "cold"),
    ({}, 0, "cold"),
])
def test_scoring_is_deterministic(lead, points, tier):
    runs = {(disposition.score(lead), disposition.tier(disposition.score(lead))) for _ in range(20)}
    assert runs == {(points, tier)}


# --- on_summary: governance -------------------------------------------------

TRANSCRIPT_KEYS = {"call_log", "raw_call_log", "conversation_summary", "post_prompt_data",
                   "swaig_log", "previous_contexts", "call_timeline"}


class TripwirePayload(dict):
    """A post-prompt payload that fails the test if transcript fields are read."""

    def __getitem__(self, key):
        assert key not in TRANSCRIPT_KEYS, f"on_summary read {key}"
        return super().__getitem__(key)

    def get(self, key, default=None):
        assert key not in TRANSCRIPT_KEYS, f"on_summary read {key}"
        return super().get(key, default)

    def __iter__(self):
        raise AssertionError("on_summary iterated the whole payload")

    items = values = keys = __iter__


class TripwireSummary:
    def __getattr__(self, name):
        raise AssertionError("on_summary read the model summary")

    def __getitem__(self, key):
        raise AssertionError("on_summary read the model summary")

    def __bool__(self):
        raise AssertionError("on_summary read the model summary")


def test_on_summary_never_reads_transcript(agent, leads_file):
    agent.on_summary(TripwireSummary(), TripwirePayload(FIXTURE))
    row = json.loads(leads_file.read_text().splitlines()[-1])
    # The transcript and summary say "hot". Handler-written data says cold, and that wins.
    assert row["tier"] == "cold"
    assert row["budget_usd"] == 2000 and row["call_id"] == "call-0113"


def test_on_summary_appends_one_row_per_call(agent, leads_file):
    agent.on_summary(None, {"call_id": "a", "global_data": HOT})
    agent.on_summary(None, {"call_id": "b", "global_data": {}})
    rows = [json.loads(line) for line in leads_file.read_text().splitlines()]
    assert [(r["call_id"], r["tier"]) for r in rows] == [("a", "hot"), ("b", "cold")]


# --- optional HubSpot sink (mocked: no network) -----------------------------

def test_hubspot_sink_posts_contact(agent, monkeypatch, leads_file):
    monkeypatch.setattr(config, "CRM_SINK", "hubspot")
    monkeypatch.setattr(config, "HUBSPOT_TOKEN", "test-token")
    with mock.patch("urllib.request.urlopen") as urlopen:
        agent.on_summary(None, {"call_id": "call-0114", "global_data": HOT})
    req = urlopen.call_args.args[0]
    assert req.full_url == config.HUBSPOT_URL and req.get_method() == "POST"
    assert req.get_header("Authorization") == "Bearer test-token"
    props = json.loads(req.data)["properties"]
    assert props["lead_tier"] == "hot" and props["lead_budget_usd"] == 50_000
    assert props["lead_call_id"] == "call-0114"
    assert not leads_file.exists()  # hubspot replaces the file sink


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


def test_governance_steps_and_tools(ai):
    steps = {s["name"]: s for s in ai["prompt"]["contexts"]["default"]["steps"]}
    assert sorted(steps["qualify"]["functions"]) == sorted(
        ["record_budget", "record_timeline", "record_authority", "record_need"])
    assert steps["qualify"]["valid_steps"] == []   # only a handler leaves qualify
    assert steps["wrap_up"]["functions"] == []


def test_governance_post_prompt_wired(ai):
    assert "/post_prompt" in ai["post_prompt_url"]
