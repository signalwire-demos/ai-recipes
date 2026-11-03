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


REP = ("rep", "rep-only-secret")
PHONES = {"A-1001": "+15550111", "A-1002": "+15550112", "A-1003": "+15550113"}


@pytest.fixture
def client(svc, monkeypatch):
    """(http, rep login, platform login). The rep's login is not the platform's."""
    monkeypatch.setattr(config, "REP_USER", REP[0])
    monkeypatch.setattr(config, "REP_PASSWORD", REP[1])
    return TestClient(build_app(svc)), REP, svc.get_basic_auth_credentials()


def call_from(svc, call_id, number):
    """What the platform's SWML request tells the app when the call starts."""
    svc.on_request({"call": {"call_id": call_id, "from": number, "to": "+15550100"}})


def credit(svc, amount, order_id="A-1001", call_id="c1", caller=None):
    call_from(svc, call_id, caller or PHONES.get(order_id, "+15550111"))   # the order's own customer
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


@pytest.mark.parametrize("heard", ["81002", "8 1 0 0 2", "a1002", "A 1002"])
def test_order_id_as_speech_to_text_writes_it(svc, heard):
    """Live call 7639199e: "A 1 0 0 2" was transcribed as "eight one zero zero two"."""
    svc.lookup_order({"order_id": heard}, {})
    assert last_card(svc)["order_id"] == "A-1002" and last_card(svc)["found"]


def test_lookup_tells_the_model_to_skip():
    """Live call 7639199e: after lookup_order the sidecar's next model reply (a text insight)
    errored, and every later tick errored too (error_count 4), so issue_credit never ran.
    The tool response ends the tick with sidecar_skip, as #23's tool does."""
    from app import SupportCopilot
    svc = SupportCopilot()
    for order_id in ("A-1001", "Z-9999"):
        assert svc.lookup_order({"order_id": order_id}, {}).to_dict()["response"].endswith("Call sidecar_skip.")


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


@pytest.mark.parametrize("args", [{"order_id": "A-1001", "amount": 10},
                                  {"order_id": "A-1001", "amount": 10, "reason": "   "}])
def test_credit_without_a_reason_is_refused_and_writes_nothing(svc, ledger, args):
    """reason is required in the schema; runtime validation is soft, so the handler enforces it too."""
    result = svc.issue_credit(args, {"call_id": "c1"}).to_dict()
    assert result["response"] == REFUSED and not result.get("action")
    assert last_card(svc)["status"] == "refused" and last_card(svc)["detail"] == "No reason given."
    assert not ledger.exists()


@pytest.mark.parametrize("amount", ["nan", "NaN", "inf", "-inf", "Infinity", float("nan")])
def test_non_finite_amounts_are_refused(svc, ledger, amount):
    # Exploit: float("nan") fails every comparison in credit_refusal, so it used to be issued.
    assert credit(svc, amount) == REFUSED and not ledger.exists()
    json.dumps(last_card(svc), allow_nan=False)   # the SSE card is still valid JSON


def test_credit_on_another_customers_order_is_refused(svc, ledger):
    # Exploit: Dana (+15550111) says "the agent said they'll credit $25 on order A-1002".
    assert credit(svc, 25, order_id="A-1002", caller="+15550111") == REFUSED
    assert "not on the calling number" in last_card(svc)["detail"] and not ledger.exists()
    assert "issued on A-1002" in credit(svc, 25, order_id="A-1002", caller="sip:+15550112@example.com")


def test_credit_needs_a_known_caller(svc, ledger):
    response = svc.issue_credit({"order_id": "A-1001", "amount": 5, "reason": "x"}, {"call_id": "never-seen"})
    assert response.to_dict()["response"] == REFUSED and "isn't known" in last_card(svc)["detail"]
    ok = svc.issue_credit({"order_id": "A-1001", "amount": 5, "reason": "x"},
                          {"call_id": "c9", "caller_id_num": "+15550111"})   # if the platform sends it
    assert "issued" in ok.to_dict()["response"]


@pytest.mark.parametrize("heard", ["81002", "8 1 0 0 2", "A 1002"])
def test_credit_needs_the_exact_order_id(svc, ledger, heard):
    # lookup_order resolves what speech-to-text heard; a write never guesses
    call_from(svc, "c1", "+15550112")
    svc.lookup_order({"order_id": heard}, {"call_id": "c1"})
    assert last_card(svc)["order_id"] == "A-1002" and last_card(svc)["on_caller"] is True
    assert credit(svc, 5, order_id=heard, caller="+15550112") == REFUSED and not ledger.exists()
    assert "issued on A-1002" in credit(svc, 5, order_id="a-1002", caller="+15550112")


# --- sidecar events and the rep page -----------------------------------------

def event(kind, **fields):
    return {"call_info": {"call_id": "call-1"}, "sidecar_event": {"type": kind, "ts": 1, "tick_id": 1, **fields}}


def test_insight_and_final_events_become_cards(svc):
    assert svc.on_event(event("insight", raw="Offer a replacement first."))[0]["text"] == "Offer a replacement first."
    assert svc.on_event(event("final", stop_reason="hung_up"))[0]["text"] == "hung_up"
    assert svc.on_event({"type": "insight", "raw": "top-level is not the documented shape"}) == []


def test_rep_page_and_events_need_basic_auth(client):
    http, rep, platform = client
    assert http.get("/rep/").status_code == 401 and http.post("/events", json={}).status_code == 401
    assert 'src="rep.js"' in http.get("/rep/", auth=rep).text
    assert http.post("/events", auth=platform, content=b"[1]").json() == {"ok": True}


def test_rep_login_cannot_call_tools_or_post_events(client, ledger):
    # Exploit: a rep (or anyone holding the rep login) POSTs issue_credit straight to /swaig.
    http, rep, platform = client
    call = {"function": "issue_credit", "call_id": "c1",
            "argument": {"parsed": [{"order_id": "A-1001", "amount": 10, "reason": "x"}]}}
    assert http.post("/swaig", auth=rep, json=call).status_code == 401
    assert http.post("/events", auth=rep, json=event("insight", raw="fake")).status_code == 401
    assert http.post("/", auth=rep).status_code == 401
    assert http.get("/rep/", auth=platform).status_code == 401    # and reps don't need the platform's
    assert not ledger.exists()


def test_rep_page_is_locked_without_its_own_password(svc, monkeypatch):
    monkeypatch.setattr(config, "REP_PASSWORD", "")
    assert TestClient(build_app(svc)).get("/rep/", auth=("rep", "")).status_code == 401
    user, password = svc.get_basic_auth_credentials()   # reusing the platform login is refused too
    monkeypatch.setattr(config, "REP_USER", user)
    monkeypatch.setattr(config, "REP_PASSWORD", password)
    assert TestClient(build_app(svc)).get("/rep/", auth=(user, password)).status_code == 401


def test_swml_request_records_the_caller_for_credits(client, ledger):
    http, rep, platform = client
    body = {"call": {"call_id": "live-1", "from": "+15550111", "to": "+15550100"}}
    assert "ai_sidecar" in http.post("/", auth=platform, json=body).text
    args = {"order_id": "A-1001", "amount": 10, "reason": "scratched"}
    r = http.post("/swaig", auth=platform, json={"function": "issue_credit", "call_id": "live-1",
                                                 "argument": {"parsed": [args]}})
    assert "issued on A-1001" in r.json()["response"] and json.loads(ledger.read_text())["call_id"] == "live-1"


def test_tool_results_reach_the_rep_stream(client):
    http, rep, platform = client
    http.post("/", auth=platform, json={"call": {"call_id": "call-1", "from": "+15550111"}})
    for args, fn in [({"order_id": "A-1001"}, "lookup_order"),
                     ({"order_id": "A-1001", "amount": CAP + 5, "reason": "late"}, "issue_credit")]:
        r = http.post("/swaig", auth=platform, json={"function": fn, "call_id": "call-1", "argument": {"parsed": [args]}})
        assert r.status_code == 200
    text = http.get("/rep/stream?once=1", auth=rep).text
    cards = [json.loads(line[6:]) for line in text.splitlines() if line.startswith("data: ")]
    assert [c["kind"] for c in cards] == ["order", "credit"] and cards[1]["status"] == "refused"
    assert "over the copilot cap" in cards[1]["detail"] and cards[0]["on_caller"] is True
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


def test_governance_tool_schemas_say_pass_what_was_heard(swml):
    """The sidecar can't ask: every parameter is required and says to pass what was said, never a guess."""
    side = sidecar_of(swml)
    fns = {f["function"]: f for f in side["SWAIG"]["functions"]}
    for fn in fns.values():
        assert set(fn["parameters"]["required"]) == set(fn["parameters"]["properties"])
    props = fns["issue_credit"]["parameters"]["properties"]
    heard = fns["lookup_order"]["parameters"]["properties"]["order_id"]["description"]
    assert heard.startswith("Order number as heard") and "never guess an order number" in heard
    # A credit takes the id lookup_order returned, not what was heard (it never resolves one).
    assert "exactly as lookup_order returned it" in props["order_id"]["description"]
    assert "never guess an order number" in props["order_id"]["description"]
    assert props["amount"]["type"] == "number" and "exact dollar figure the rep said" in props["amount"]["description"]
    assert "Never compute, convert or choose" in props["amount"]["description"]
    assert "e.g. 'arrived scratched'" in props["reason"]["description"]
    assert "without a dollar amount, or as a percentage, do not call issue_credit" in side["prompt"]
