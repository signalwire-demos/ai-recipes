"""Handler tests for both agents, the handoff round trip, and governance assertions on the SWML
that swaig-test dumps (default agent = /concierge, --route /booking for the other).
swml_transfer(final=True) emits {"SWML": {...}, "transfer": "true"}; swml_change_step emits {"change_step": ...}.
"""
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

RECIPE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RECIPE))

import config  # noqa: E402
import handoff  # noqa: E402
from app import BookingDesk, ConciergeDesk  # noqa: E402

TRIP = {"destination": "lisbon", "destination_name": "Lisbon", "travelers": 2, "month": "December"}


@pytest.fixture(autouse=True)
def tmp_store(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "HANDOFF_FILE", tmp_path / "handoffs.json")
    monkeypatch.setattr(config, "BOOKINGS_FILE", tmp_path / "bookings.jsonl")
    monkeypatch.setattr(config, "PUBLIC_URL", "https://travel.example.com")
    return tmp_path


@pytest.fixture(scope="module")
def concierge():
    return ConciergeDesk()


@pytest.fixture(scope="module")
def booking():
    return BookingDesk()


def acts(result):
    return result.to_dict().get("action", [])


def find(actions, key):
    return [a[key] for a in actions if key in a]


# --- concierge ---------------------------------------------------------------------

def test_destination_info_records_interest(concierge):
    result = concierge.destination_info({"destination": "Kyoto"}, {"global_data": {"looked_up": ["lisbon"]}})
    assert "Osaka" in result.to_dict()["response"]
    assert find(acts(result), "set_global_data") == [{"looked_up": ["kyoto", "lisbon"]}]
    assert acts(concierge.destination_info({"destination": "Atlantis"}, {})) == []


def transfer_target(d, route):
    """The one final transfer in a result: returns (parsed URL, token)."""
    (transfer,) = [a for a in d["action"] if "SWML" in a]
    assert transfer["transfer"] == "true"   # final: a non-final transfer into a second ai verb gets 409
    url = urlsplit(transfer["SWML"]["sections"]["main"][1]["transfer"]["dest"])
    assert (url.scheme, url.hostname, url.path) == ("https", "travel.example.com", route)
    assert url.username and url.password                       # basic auth for the platform fetch
    assert list(parse_qs(url.query)) == ["h"]                  # only an opaque token in the URL
    assert url.password not in d["response"]                     # the model never sees the credentials
    return url, parse_qs(url.query)["h"][0]


def test_transfer_action_has_booking_url_and_token(concierge):
    raw = {"call_id": "call-1", "global_data": {"looked_up": ["kyoto", "lisbon"]}}
    result = concierge.handoff_to_booking({"destination": "lisbon", "travelers": 2, "month": "december"}, raw)
    d = result.to_dict()
    url, token = transfer_target(d, config.BOOKING_ROUTE)
    assert d["post_process"] is True
    # the handler-written record: structured trip + a summary built in code
    record = handoff.load(token)
    assert record["trip"] == TRIP and record["call_id"] == "call-1"
    assert record["summary"] == "2 travelers to Lisbon in December. Destinations discussed: kyoto, lisbon."


@pytest.mark.parametrize("args, says", [
    ({"destination": "atlantis", "travelers": 2, "month": "may"}, "don't offer"),
    ({"destination": "lisbon", "travelers": 40, "month": "may"}, "1 to"),
])
def test_handoff_validates_before_transfer(concierge, args, says, tmp_store):
    result = concierge.handoff_to_booking(args, {})
    assert acts(result) == [] and says in result.to_dict()["response"]
    assert not (tmp_store / "handoffs.json").exists()


# --- booking: dynamic config rebuilds global_data from the handoff ------------------

def test_booking_dynamic_config_rebuilds_global_data(booking):
    token = handoff.save({"call_id": "call-1", "summary": "2 travelers to Lisbon.", "trip": TRIP,
                          "looked_up": ["lisbon"]})
    copy = BookingDesk()
    booking.from_handoff({"h": token}, {}, {}, copy)
    assert copy._global_data == {"summary": "2 travelers to Lisbon.", "trip": TRIP, "handoff_id": token,
                                 "looked_up": ["lisbon"]}
    again = BookingDesk()
    booking.from_handoff({"h": token}, {}, {}, again)                  # one-time: a replay gets nothing
    assert again._global_data["trip"] is None


def test_unknown_or_expired_token_leaves_defaults(booking, monkeypatch):
    token = handoff.save({"summary": "old", "trip": TRIP})
    monkeypatch.setattr(time, "time", lambda: 1e12)              # far past the TTL
    for query in ({"h": token}, {"h": "nope"}, {}):
        copy = BookingDesk()
        booking.from_handoff(query, {}, {}, copy)
        assert copy._global_data == {"summary": "No handoff on file.", "trip": None}


def test_search_flights_uses_handoff_party_size(booking):
    text = booking.search_flights({}, {"global_data": {"trip": TRIP}}).to_dict()["response"]
    assert "FL-101" in text and "$1224 total for 2" in text
    assert "FL-103 departing December 11 at 18:30" in text           # dates as callers say them
    assert "FL-102" not in text                                  # only 1 seat left
    assert "no trip" in booking.search_flights({}, {"global_data": {}}).to_dict()["response"].lower()


def test_hold_flight_books_handoff_trip_only(booking, tmp_store):
    gd = {"global_data": {"trip": TRIP, "handoff_id": "abc123xyz"}, "call_id": "call-1"}
    assert acts(booking.hold_flight({"flight_id": "FL-102"}, gd)) == []   # not enough seats
    assert acts(booking.hold_flight({"flight_id": "FL-201"}, gd)) == []   # another destination
    result = booking.hold_flight({"flight_id": "fl-103"}, gd)
    assert find(acts(result), "change_step") == ["done"]
    held = find(acts(result), "set_global_data")[0]["booking"]
    assert held["total"] == 1180 and held["travelers"] == 2 and held["ref"] == "R-ABC123"
    assert json.loads((tmp_store / "bookings.jsonl").read_text())["flight_id"] == "FL-103"


def test_return_to_concierge_transfers_back_with_fresh_token(booking):
    held = {"ref": "R-ABC123", "flight_id": "FL-103", "readback": "2 seats on FL-103 to Lisbon"}
    gd = {"handoff_id": "abc123xyz", "summary": "2 travelers to Lisbon in December.", "trip": TRIP,
          "looked_up": ["lisbon"], "booking": held}
    d = booking.return_to_concierge({}, {"call_id": "call-1", "global_data": gd}).to_dict()
    url, token = transfer_target(d, config.CONCIERGE_ROUTE)
    assert token != "abc123xyz" and d["post_process"] is True
    assert find(d["action"], "stop") == []
    record = handoff.load(token)
    assert {k: record[k] for k in ("summary", "booking", "looked_up", "call_id")} == {
        "summary": gd["summary"], "booking": held, "looked_up": ["lisbon"], "call_id": "call-1"}
    # no transcript or conversation fields cross back, only the structured summary and result
    assert set(record) == {"call_id", "summary", "booking", "looked_up", "created"}


@pytest.mark.parametrize("booking_result, says", [
    ({"ref": "R-ABC123", "readback": "2 seats on FL-103 to Lisbon"}, "held 2 seats on FL-103 to Lisbon, reference R-ABC123"),
    (None, "Nothing was booked."),
])
def test_concierge_resumes_with_return_context(concierge, booking_result, says):
    token = handoff.save({"summary": "2 travelers to Lisbon in December.", "looked_up": ["lisbon"],
                          "booking": booking_result})
    copy = ConciergeDesk()
    concierge.from_booking({"h": token}, {}, {}, copy)
    assert copy._global_data == {"looked_up": ["lisbon"], "booking": booking_result}
    section = copy.pom.find_section("Returning caller").body
    assert says in section and "2 travelers to Lisbon in December." in section
    assert handoff.load(token) is None                                 # claimed: one-time token
    fresh = ConciergeDesk()
    concierge.from_booking({}, {}, {}, fresh)                          # a first-time caller: no section
    assert fresh.pom.find_section("Returning caller") is None


# --- governance: read the SWML exactly as swaig-test dumps it ----------------------

def dump(*extra, env=None):
    local = Path(sys.executable).with_name("swaig-test")
    exe = str(local) if local.exists() else (shutil.which("swaig-test") or "swaig-test")
    out = subprocess.run([exe, str(RECIPE / "app.py"), *extra, "--dump-swml", "--raw"],
                         capture_output=True, text=True, check=True, cwd=RECIPE,
                         env={**os.environ, **(env or {})}).stdout
    return next(v["ai"] for v in json.loads(out)["sections"]["main"] if "ai" in v)


def steps(ai):
    return {s["name"]: s for s in ai["prompt"]["contexts"]["default"]["steps"]}


def test_governance_concierge_cannot_book():
    ai = dump()
    tools = {f["function"] for f in ai["SWAIG"]["functions"]}
    assert tools == {"destination_info", "handoff_to_booking"}
    assert steps(ai)["explore"]["valid_steps"] == []


def test_governance_booking_tools_take_no_trip_args_and_dump_rebuilds_global_data(tmp_path):
    store = tmp_path / "handoffs.json"
    os.environ["HANDOFF_FILE"] = str(store)
    try:
        config.HANDOFF_FILE = store
        token = handoff.save({"summary": "2 travelers to Lisbon in December.", "trip": TRIP})
        ai = dump("--route", config.BOOKING_ROUTE, "--query-params", json.dumps({"h": token}))
    finally:
        os.environ.pop("HANDOFF_FILE")
    assert ai["global_data"]["trip"] == TRIP and ai["global_data"]["handoff_id"] == token
    fns = {f["function"]: f for f in ai["SWAIG"]["functions"]}
    assert fns["search_flights"]["parameters"]["properties"] == {}          # party/destination from handoff
    assert set(fns["hold_flight"]["parameters"]["properties"]) == {"flight_id"}
    s = steps(ai)
    assert "handoff_to_booking" not in s["choose"]["functions"]
    assert s["done"]["functions"] == ["return_to_concierge"]
