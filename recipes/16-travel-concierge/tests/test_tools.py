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
from app import BookingDesk, ConciergeDesk, caller_spoke_after  # noqa: E402

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
    options = copy._global_data.pop("options")
    assert copy._global_data.pop("options_read").startswith("Option 1: departing December 4")
    assert copy._global_data == {"summary": "2 travelers to Lisbon.", "trip": TRIP, "handoff_id": token,
                                 "looked_up": ["lisbon"]}
    assert [f["id"] for f in options.values()] == ["FL-101", "FL-103"]
    again = BookingDesk()
    booking.from_handoff({"h": token}, {}, {}, again)                  # one-time: a replay gets nothing
    assert again._global_data["trip"] is None and again._global_data["options_read"] == "none."


def test_unknown_or_expired_token_leaves_defaults(booking, monkeypatch):
    token = handoff.save({"summary": "old", "trip": TRIP})
    monkeypatch.setattr(time, "time", lambda: 1e12)              # far past the TTL
    for query in ({"h": token}, {"h": "nope"}, {}):
        copy = BookingDesk()
        booking.from_handoff(query, {}, {}, copy)
        assert copy._global_data == {"summary": "No handoff on file.", "trip": None, "options_read": "none."}
        assert "static_greeting" not in copy._params


def test_booking_opening_reads_the_options_verbatim(booking):
    """Live call 55b18265: the model never read the options and asked for a departure city.
    The options are known from the handoff, so the platform speaks them as the opening."""
    copy = BookingDesk()
    booking.from_handoff({"h": handoff.save({"summary": "s", "trip": TRIP})}, {}, {}, copy)
    params = copy._params
    assert params["static_greeting"] == (
        "Hi, this is the booking desk. I have 2 travelers to Lisbon. "
        "Option 1: departing December 4 at 18:30, 1224 dollars total for 2. "
        "Option 2: departing December 11 at 18:30, 1180 dollars total for 2. Which option would you like?")
    assert params["static_greeting_no_barge"] is True
    assert "FL-" not in params["static_greeting"] and "$" not in params["static_greeting"]
    # hold_flight works straight off the options stored at handoff, with no search_flights call
    result = booking.hold_flight({"option": 2}, {"global_data": copy._global_data})
    assert find(acts(result), "set_global_data")[0]["booking"]["flight_id"] == "FL-103"


def test_booking_opening_without_seats_offers_the_way_back(booking):
    copy = BookingDesk()
    trip = {**TRIP, "destination": "kyoto", "destination_name": "Kyoto", "travelers": 5}
    booking.from_handoff({"h": handoff.save({"summary": "s", "trip": trip})}, {}, {}, copy)
    assert copy._global_data["options"] == {}
    assert "back to the concierge" in copy._params["static_greeting"]


def search(booking):
    """Run search_flights for TRIP; return (response text, stored options)."""
    result = booking.search_flights({}, {"global_data": {"trip": TRIP}})
    (stored,) = find(acts(result), "set_global_data")
    return result.to_dict()["response"], stored["options"]


def test_search_flights_numbers_and_stores_results(booking):
    text, options = search(booking)
    assert [f["id"] for f in options.values()] == ["FL-101", "FL-103"]   # FL-102 has only 1 seat
    assert list(options) == ["1", "2"]
    lines = ("Option 1: departing December 4 at 18:30, 1224 dollars total for 2. "
             "Option 2: departing December 11 at 18:30, 1180 dollars total for 2.")
    assert len(text) < 100                         # long results were logged empty on live calls
    assert "FL-" not in text                       # the model sees option numbers, not flight IDs
    # the platform speaks the options; nothing in the text reads as "no flights"
    said = find(acts(booking.search_flights({}, {"global_data": {"trip": TRIP}})), "say")
    assert said == [f"{lines} Which option would you like?"]
    assert "all the flights" not in text and "$" not in text
    (stored,) = find(acts(booking.search_flights({}, {"global_data": {"trip": TRIP}})), "set_global_data")
    assert stored["options_read"] == lines
    assert "no trip" in booking.search_flights({}, {"global_data": {}}).to_dict()["response"].lower()


def test_hold_flight_maps_option_number_to_stored_flight(booking, tmp_store):
    _, options = search(booking)
    gd = {"global_data": {"trip": TRIP, "handoff_id": "abc123xyz", "options": options}, "call_id": "call-1"}
    result = booking.hold_flight({"option": 2}, gd)
    assert find(acts(result), "change_step") == ["done"]
    held = find(acts(result), "set_global_data")[0]["booking"]
    assert held["flight_id"] == "FL-103" and held["total"] == 1180 and held["ref"] == "R-ABC123"
    assert "December 11" in held["readback"]
    # the readback and "anything else?" are spoken by the platform, then the done step waits
    (said,) = find(acts(result), "say")
    assert said.startswith("Done. I've held 2 seats on FL-103") and said.endswith("anything else you need for this booking?")
    assert "R-ABC123" in said and len(result.to_dict()["response"]) < 100
    assert json.loads((tmp_store / "bookings.jsonl").read_text())["flight_id"] == "FL-103"


@pytest.mark.parametrize("option", [0, 3, 99, -1, "FL-103", "two", None])
def test_hold_flight_refuses_option_outside_stored_results(booking, tmp_store, option):
    _, options = search(booking)
    gd = {"global_data": {"trip": TRIP, "options": options}}
    result = booking.hold_flight({"option": option}, gd)
    assert acts(result) == [] and "isn't one of the options" in result.to_dict()["response"]
    assert not (tmp_store / "bookings.jsonl").exists()


def test_hold_flight_refuses_without_search_or_with_tampered_option(booking, tmp_store):
    no_search = booking.hold_flight({"option": 1}, {"global_data": {"trip": TRIP}})
    assert acts(no_search) == [] and "search_flights first" in no_search.to_dict()["response"]
    fake = {"1": {"id": "FL-999", "depart": "2026-12-01 08:00", "price": 1, "seats": 9}}
    tampered = booking.hold_flight({"option": 1}, {"global_data": {"trip": TRIP, "options": fake}})
    assert acts(tampered) == []                                         # not in real inventory
    assert not (tmp_store / "bookings.jsonl").exists()


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


HELD = {"ref": "R-ABC123", "flight_id": "FL-103", "readback": "2 seats on FL-103 to Lisbon"}


def log_after_hold(*after):
    """A raw_call_log as swaig_post_conversation posts it, ending with `after`."""
    return [{"role": "assistant", "content": "Which option would you like?"},
            {"role": "user", "content": "Option two, please."},
            {"role": "assistant", "tool_calls": [{"function": {"name": "hold_flight", "arguments": "{}"}}]},
            {"role": "tool", "function_name": "hold_flight", "content": "Held"}, *after]


def test_return_to_concierge_waits_for_the_caller_after_a_hold(booking):
    """Live call 55b18265: hold_flight, then return_to_concierge one second later with no reply."""
    gd = {"summary": "s", "trip": TRIP, "booking": HELD}
    same_breath = log_after_hold({"role": "assistant", "tool_calls": [
        {"function": {"name": "return_to_concierge", "arguments": "{}"}}]})
    early = booking.return_to_concierge({}, {"global_data": gd, "raw_call_log": same_breath}).to_dict()
    assert "action" not in early and "hasn't answered" in early["response"]
    answered = log_after_hold({"role": "user", "content": "No, that's all, thanks."})
    late = booking.return_to_concierge({}, {"global_data": gd, "raw_call_log": answered}).to_dict()
    transfer_target(late, config.CONCIERGE_ROUTE)
    # nothing held: going back is always allowed
    back = booking.return_to_concierge({}, {"global_data": {"summary": "s"}, "raw_call_log": []}).to_dict()
    transfer_target(back, config.CONCIERGE_ROUTE)


def test_caller_spoke_after_reads_either_log_shape():
    assert caller_spoke_after({}, "hold_flight") is None                       # no conversation posted
    assert caller_spoke_after({"call_log": log_after_hold()}, "hold_flight") is False
    assert caller_spoke_after({"call_log": log_after_hold({"role": "user", "content": " "})}, "hold_flight") is False
    assert caller_spoke_after({"call_log": log_after_hold({"role": "user", "content": "done"})}, "hold_flight")


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
    # the platform speaks the welcome-back outcome verbatim, from the stored fields
    assert copy._params["static_greeting"].startswith("Welcome back. ")
    assert says in copy._params["static_greeting"]
    fresh = ConciergeDesk()
    concierge.from_booking({}, {}, {}, fresh)                          # a first-time caller: no section
    assert fresh.pom.find_section("Returning caller") is None
    assert "static_greeting" not in fresh._params


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
    assert set(fns["hold_flight"]["parameters"]["properties"]) == {"option"}          # a number, not an ID
    assert fns["hold_flight"]["parameters"]["properties"]["option"]["type"] == "integer"
    assert ai["prompt"]["model"] == config.BOOKING_MODEL == "gpt-4.1-mini"
    s = steps(ai)
    assert "handoff_to_booking" not in s["choose"]["functions"]
    assert s["done"]["functions"] == ["return_to_concierge"] and s["done"]["valid_steps"] == []
    assert ai["params"]["swaig_post_conversation"] is True
    assert "Option 2: departing December 11" in ai["params"]["static_greeting"]
