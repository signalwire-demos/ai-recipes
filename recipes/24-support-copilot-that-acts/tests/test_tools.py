"""Tests for the support copilot.

1. lookup_order and issue_credit, called directly: the cap and every other credit rule is
   enforced in the handler, and refusals tell the model nothing.
2. The sidecar event consumer and the rep page (auth, static files, SSE card stream).
3. Governance, against the SWML that swaig-test dumps: two tools exactly, both legs, and
   the cap appears nowhere the model can read it.
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

RECIPE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RECIPE))

import config  # noqa: E402
from app import REFUSED, SupportCopilot, build_app  # noqa: E402

CAP = config.CREDIT_CAP_USD


@pytest.fixture(autouse=True)
def ledger(tmp_path, monkeypatch):
    path = tmp_path / "credits.jsonl"
    monkeypatch.setattr(config, "CREDIT_LEDGER", path)
    return path


@pytest.fixture
def svc():
    return SupportCopilot()


@pytest.fixture
def client(svc):
    return TestClient(build_app(svc)), svc.get_basic_auth_credentials()


def credit(svc, amount, order_id="A-1001", call_id="c1"):
    return svc.issue_credit({"order_id": order_id, "amount": amount, "reason": "arrived scratched"},
                            {"call_id": call_id}).to_dict()["response"]


def last_card(svc):
    return svc.feed.since(0)[-1]


# --- lookup_order ---------------------------------------------------------------

def test_lookup_order_found_card_has_full_record(svc):
    response = svc.lookup_order({"order_id": "a-1002"}, {"call_id": "c1"}).to_dict()["response"]
    card = last_card(svc)
    assert card["kind"] == "order" and card["found"] and card["order_id"] == "A-1002"
    assert card["phone"] == "+15550112" and card["notes"]
    assert "in_transit" in response and "2026-11-04" in response and "189.00" in response


def test_lookup_order_keeps_phone_and_notes_from_the_model(svc):
    response = svc.lookup_order({"order_id": "A-1001"}, {}).to_dict()["response"]
    assert "+15550111" not in response and "scratched" not in response


def test_lookup_order_not_found(svc):
    response = svc.lookup_order({"order_id": "Z-9999"}, {}).to_dict()["response"]
    assert "No order Z-9999" in response and last_card(svc)["found"] is False


# --- issue_credit: the cap and the rules live in the handler --------------------

def test_credit_within_cap_is_issued_and_written_to_ledger(svc, ledger):
    response = credit(svc, 10)
    assert "issued on A-1001" in response
    assert last_card(svc)["status"] == "issued"
    entry = json.loads(ledger.read_text())
    assert entry["order_id"] == "A-1001" and entry["amount"] == 10.0 and entry["call_id"] == "c1"


def test_credit_at_exactly_the_cap_is_issued(svc):
    assert "issued" in credit(svc, CAP)


def test_credit_above_cap_is_refused_in_handler(svc, ledger):
    assert credit(svc, CAP + 0.01) == REFUSED
    card = last_card(svc)
    assert card["status"] == "refused" and f"{CAP:.2f}" in card["detail"]   # the rep sees the cap
    assert not ledger.exists()


@pytest.mark.parametrize("order_id,amount", [("Z-9999", 5), ("A-1001", 0), ("A-1001", -5),
                                             ("A-1003", 20), ("A-1001", "lots")])
def test_other_refusals(svc, ledger, order_id, amount):
    # unknown order, zero, negative, more than the order total (12.00), not a number
    assert credit(svc, amount, order_id=order_id) == REFUSED
    assert last_card(svc)["status"] == "refused" and not ledger.exists()


def test_one_credit_per_order(svc):
    assert "issued" in credit(svc, 5)
    assert credit(svc, 5, call_id="c2") == REFUSED
    assert "already has a credit" in last_card(svc)["detail"]


def test_refusals_never_tell_the_model_the_cap(svc):
    responses = {credit(svc, a) for a in (CAP + 1, 1000, -1)} | {credit(svc, 5, order_id="Z-1")}
    assert responses == {REFUSED}
    assert f"{CAP:.2f}" not in REFUSED and str(int(CAP)) not in REFUSED


# --- sidecar events and the rep page -----------------------------------------

def event(kind, **fields):
    return {"call_info": {"call_id": "call-1"}, "sidecar_event": {"type": kind, "ts": 1, "tick_id": 1, **fields}}


def test_insight_and_final_events_become_cards(svc):
    assert svc.on_event(event("insight", raw="Offer a replacement first."))[0]["text"] == "Offer a replacement first."
    assert svc.on_event(event("final", stop_reason="hung_up"))[0]["text"] == "hung_up"
    assert svc.on_event({"type": "insight", "raw": "top-level is not the documented shape"}) == []


def test_rep_page_and_events_need_basic_auth(client):
    http, auth = client
    assert http.get("/rep/").status_code == 401 and http.post("/events", json={}).status_code == 401
    assert 'src="rep.js"' in http.get("/rep/", auth=auth).text
    assert http.post("/events", auth=auth, content=b"[1]").json() == {"ok": True}


def test_tool_results_reach_the_rep_stream(client):
    http, auth = client
    for args, fn in [({"order_id": "A-1001"}, "lookup_order"),
                     ({"order_id": "A-1001", "amount": CAP + 5, "reason": "late"}, "issue_credit")]:
        r = http.post("/swaig", auth=auth, json={"function": fn, "call_id": "call-1", "argument": {"parsed": [args]}})
        assert r.status_code == 200
    text = http.get("/rep/stream?once=1", auth=auth).text
    cards = [json.loads(line[6:]) for line in text.splitlines() if line.startswith("data: ")]
    assert [c["kind"] for c in cards] == ["order", "credit"] and cards[1]["status"] == "refused"
    assert cards[0]["customer"] == "Dana Reyes" and cards[1]["amount"] == CAP + 5


# --- governance: read the SWML exactly as swaig-test dumps it ---------------

def swaig_test_bin() -> str:
    local = Path(sys.executable).with_name("swaig-test")
    return str(local) if local.exists() else (shutil.which("swaig-test") or "swaig-test")


@pytest.fixture(scope="module")
def swml():
    out = subprocess.run([swaig_test_bin(), str(RECIPE / "app.py"), "--dump-swml", "--raw"],
                         capture_output=True, text=True, check=True, cwd=RECIPE).stdout
    return json.loads(out)


def sidecar_of(doc):
    return next(v["ai_sidecar"] for v in doc["sections"]["main"] if "ai_sidecar" in v)


def test_governance_sidecar_has_exactly_two_scoped_tools(swml):
    side = sidecar_of(swml)
    assert [f["function"] for f in side["SWAIG"]["functions"]] == ["lookup_order", "issue_credit"]
    assert sorted(side["direction"]) == ["local-caller", "remote-caller"]
    assert [next(iter(v)) for v in swml["sections"]["main"]] == ["answer", "ai_sidecar", "connect", "hangup"]


def test_governance_cap_is_not_in_anything_the_model_reads(swml):
    side = sidecar_of(swml)
    model_visible = json.dumps({"prompt": side["prompt"], "functions": side["SWAIG"]["functions"]})
    assert f"{CAP:.2f}" not in model_visible and f"{CAP:g}" not in model_visible
    assert "cap" not in model_visible.lower()
