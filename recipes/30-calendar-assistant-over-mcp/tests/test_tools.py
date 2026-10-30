"""Tests: the agent's SWML, the reference calendar MCP server, and the discovery the
platform does at call start (read mcp_servers from the dumped SWML, then initialize
and tools/list with exactly that URL and headers).
"""
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

os.environ["MCP_TOKEN"] = "voice-agent-test-token"
os.environ["MCP_ADMIN_TOKEN"] = "admin-test-token"
os.environ["MCP_URL"] = "https://calendar.example.com/mcp"

RECIPE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RECIPE))

import mcp_calendar  # noqa: E402
from app import CalendarAgent  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

VOICE = {"Authorization": "Bearer voice-agent-test-token"}
ADMIN = {"Authorization": "Bearer admin-test-token"}
DAY = "2030-01-07"  # a Monday
SEED = [
    {"id": "M-1001", "title": "Cleaning", "start": f"{DAY} 10:00", "attendee": "Dana Rivera"},
    {"id": "M-1002", "title": "Checkup", "start": f"{DAY} 11:00", "attendee": "Sam Okafor"},
]


@pytest.fixture
def server():
    return TestClient(mcp_calendar.create_app(mcp_calendar.Calendar(SEED)))


def rpc(client, method, params=None, headers=VOICE, req_id=1):
    body = {"jsonrpc": "2.0", "method": method}
    if req_id is not None:
        body["id"] = req_id
    if params is not None:
        body["params"] = params
    return client.post("/mcp", json=body, headers=headers)


def call(client, name, arguments, headers=VOICE):
    return rpc(client, "tools/call", {"name": name, "arguments": arguments}, headers).json()


def text(reply):
    return reply["result"]["content"][0]["text"]


# --- the agent ---------------------------------------------------------------

def test_get_today_handler():
    reply = CalendarAgent().get_today({}, {"call_id": "c1"}).to_dict()["response"]
    assert datetime.now().strftime("%Y-%m-%d") in reply


def test_get_today_guard_stops_the_loop():
    # B13: with the MCP tools unreachable the model called get_today 10 times in a row.
    agent = CalendarAgent()
    first = agent.get_today({}, {"call_id": "loop"}).to_dict()
    assert "action" not in first and "again" not in first["response"]
    second = agent.get_today({}, {"call_id": "loop"}).to_dict()["response"]
    assert "don't call get_today again" in second and datetime.now().strftime("%Y-%m-%d") in second
    for _ in range(2):
        agent.get_today({}, {"call_id": "loop"})
    capped = agent.get_today({}, {"call_id": "loop"}).to_dict()
    assert "calendar is unavailable" in capped["response"]
    assert capped["action"] == [{"toggle_functions": [{"function": "get_today", "active": False}]}]
    # Another call has its own count.
    assert "action" not in agent.get_today({}, {"call_id": "other"}).to_dict()


def swaig_test_bin() -> str:
    local = Path(sys.executable).with_name("swaig-test")
    return str(local) if local.exists() else (shutil.which("swaig-test") or "swaig-test")


@pytest.fixture(scope="module")
def swml():
    out = subprocess.run(
        [swaig_test_bin(), str(RECIPE / "app.py"), "--dump-swml", "--raw"],
        capture_output=True, text=True, check=True, cwd=RECIPE,
    ).stdout
    return json.loads(out)


def swaig_of(swml_doc):
    return next(v["ai"] for v in swml_doc["sections"]["main"] if "ai" in v)["SWAIG"]


def test_swml_points_the_platform_at_the_mcp_server(swml):
    assert swaig_of(swml)["mcp_servers"] == [
        {"url": "https://calendar.example.com/mcp", "headers": VOICE}
    ]


def test_swml_carries_no_calendar_code(swml):
    # Calendar tools are discovered by the platform at call start, not defined here.
    assert [f["function"] for f in swaig_of(swml)["functions"]] == ["get_today"]


def test_platform_discovery_with_the_swml_entry(swml, server):
    entry = swaig_of(swml)["mcp_servers"][0]
    init = rpc(server, "initialize", {"protocolVersion": "2025-06-18"}, entry["headers"]).json()
    assert init["result"]["capabilities"] == {"tools": {}}
    assert rpc(server, "notifications/initialized", headers=entry["headers"], req_id=None).status_code == 202
    tools = rpc(server, "tools/list", headers=entry["headers"]).json()["result"]["tools"]
    assert {t["name"] for t in tools} == {"find_free_slots", "find_my_meetings", "book_meeting", "move_meeting"}
    assert next(t for t in tools if t["name"] == "book_meeting")["inputSchema"]["required"] == \
        ["title", "start", "attendee"]


# --- default: the reference calendar is served by the agent's own app ---------

def dump_swml(env_overrides):
    env = {**os.environ, **env_overrides}
    out = subprocess.run([swaig_test_bin(), str(RECIPE / "app.py"), "--dump-swml", "--raw"],
                         capture_output=True, text=True, check=True, cwd=RECIPE, env=env).stdout
    return json.loads(out)


def test_default_mcp_url_is_the_agent_public_url():
    # MCP_URL unset: one tunnel covers both, so the SWML points at PUBLIC_URL + /mcp-calendar.
    doc = dump_swml({"MCP_URL": "", "PUBLIC_URL": "https://agent.example.com/"})
    assert swaig_of(doc)["mcp_servers"] == [
        {"url": "https://agent.example.com/mcp-calendar", "headers": VOICE}
    ]


@pytest.fixture
def same_app(monkeypatch):
    import config
    monkeypatch.setattr(config, "SERVE_REFERENCE_CALENDAR", True)
    agent = CalendarAgent()
    agent.calendar_router.calendar.meetings = {m["id"]: dict(m) for m in SEED}
    return TestClient(agent.get_app())


def test_same_app_serves_mcp_at_the_path(same_app):
    def post(body, headers=VOICE):
        return same_app.post("/mcp-calendar", json=body, headers=headers)
    init = post({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}).json()
    assert init["result"]["serverInfo"]["name"] == "reference-calendar"
    tools = post({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}).json()["result"]["tools"]
    assert {t["name"] for t in tools} == {"find_free_slots", "find_my_meetings", "book_meeting", "move_meeting"}
    booked = post({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                   "params": {"name": "book_meeting",
                              "arguments": {"title": "Whitening", "start": f"{DAY} 14:00", "attendee": "Priya Shah"}}})
    assert text(booked.json()).startswith("Booked M-1003")
    # Token scoping still holds on the mounted route.
    assert post({"jsonrpc": "2.0", "id": 4, "method": "tools/list"}, headers={}).status_code == 401
    refused = post({"jsonrpc": "2.0", "id": 5, "method": "tools/call",
                    "params": {"name": "cancel_meeting", "arguments": {"meeting_id": "M-1001"}}}).json()
    assert refused["error"]["code"] == -32602


def test_same_app_still_serves_swml_behind_basic_auth(same_app):
    assert same_app.post("/").status_code == 401


# --- reference server: book and move round trip -----------------------------

def test_book_and_move_round_trip(server):
    booked = text(call(server, "book_meeting", {"title": "Whitening", "start": f"{DAY} 14:00", "attendee": "Priya Shah"}))
    assert booked.startswith("Booked M-1003")
    assert "14:00" not in text(call(server, "find_free_slots", {"date": DAY}))
    moved = text(call(server, "move_meeting", {"meeting_id": "m-1003", "new_start": f"{DAY} 15:30"}))
    assert moved == f"Moved M-1003 (Whitening) to {DAY} 15:30."
    free = text(call(server, "find_free_slots", {"date": DAY}))
    assert "14:00" in free and "15:30" not in free
    assert "M-1003: Whitening at 2030-01-07 15:30" in text(call(server, "find_my_meetings", {"attendee": "priya shah"}))


@pytest.mark.parametrize("args, expect", [
    ({"title": "x", "start": f"{DAY} 10:00", "attendee": "A"}, "taken"),
    ({"title": "x", "start": "2030-01-05 10:00", "attendee": "A"}, "weekdays"),  # Saturday
    ({"title": "x", "start": f"{DAY} 10:15", "attendee": "A"}, "30-minute mark"),
    ({"title": "x", "start": "2001-01-08 10:00", "attendee": "A"}, "passed"),
])
def test_book_rejections(server, args, expect):
    assert expect in text(call(server, "book_meeting", args))


def test_move_unknown_meeting(server):
    assert text(call(server, "move_meeting", {"meeting_id": "M-9", "new_start": f"{DAY} 12:00"})) == "No meeting M-9."


def test_bad_arguments_are_a_tool_error(server):
    reply = call(server, "book_meeting", {"title": "x", "start": "tomorrow", "attendee": "A"})
    assert reply["result"]["isError"] is True and "YYYY-MM-DD HH:MM" in text(reply)


def test_seed_lands_on_next_business_day():
    seeded = mcp_calendar.seed_meetings([{"title": "t", "attendee": "a", "time": "10:00"}])
    day = datetime.strptime(seeded[0]["start"], "%Y-%m-%d %H:%M")
    assert day.weekday() < 5 and timedelta(0) < day - datetime.now() < timedelta(days=4)


# --- governance: the token decides what the voice agent can reach ---------------

def test_governance_no_token_no_calendar(server):
    assert rpc(server, "tools/list", headers={}).status_code == 401
    assert rpc(server, "tools/list", headers={"Authorization": "Bearer guess"}).status_code == 401


def test_governance_voice_agent_cannot_cancel(server):
    names = {t["name"] for t in rpc(server, "tools/list").json()["result"]["tools"]}
    assert "cancel_meeting" not in names
    reply = call(server, "cancel_meeting", {"meeting_id": "M-1001"})
    assert reply["error"]["code"] == -32602
    assert "M-1001" in text(call(server, "find_my_meetings", {"attendee": "Dana Rivera"}))


def test_governance_admin_scope_can_cancel(server):
    assert text(call(server, "cancel_meeting", {"meeting_id": "M-1001"}, ADMIN)) == "Cancelled M-1001."


def test_governance_free_slots_hide_other_peoples_meetings(server):
    free = text(call(server, "find_free_slots", {"date": DAY}))
    assert "10:00" not in free and "Dana" not in free and "Cleaning" not in free
    assert "Dana" not in text(call(server, "find_my_meetings", {"attendee": "Sam Okafor"}))
