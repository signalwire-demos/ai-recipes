"""Reference calendar MCP server: in memory, MCP over streamable HTTP (JSON responses).

By default app.py serves it from the agent's own app at config.MCP_CALENDAR_PATH
(/mcp-calendar), so one public URL covers both the SWML and the MCP server. Swap it for
any calendar MCP server by setting MCP_URL / MCP_TOKEN. What it shows: the server
decides what each client may do. A bearer token maps to a scope (config.MCP_SCOPES),
and tools outside that scope are neither listed nor callable. Free-slot answers never
reveal whose meeting is in the way. Meetings belong to a caller ID: find_my_meetings and
move_meeting act only for the caller the agent signed into the call's MCP headers
(X-Caller, X-Caller-Sig), never for a name or id the caller says out loud.

  python mcp_calendar.py        # optional: run it on its own, POST /mcp on config.MCP_PORT
"""
import hashlib
import hmac
import itertools
import logging
import os
from datetime import datetime, timedelta

import uvicorn
from fastapi import APIRouter, FastAPI, Request, Response
from fastapi.responses import JSONResponse

import config

FMT = "%Y-%m-%d %H:%M"
log = logging.getLogger("uvicorn.error")   # shows up in the server log next to the access lines


class Calendar:
    def __init__(self, meetings=None):
        self.meetings = {m["id"]: dict(m) for m in (meetings or [])}
        self._ids = itertools.count(1001 + len(self.meetings))

    def _check_slot(self, start: datetime, ignore_id=None) -> str | None:
        first, last = config.OFFICE_HOURS
        if start.weekday() >= 5 or not first <= start.hour < last or start.minute % config.SLOT_MINUTES:
            return f"Meetings start on the {config.SLOT_MINUTES}-minute mark, weekdays {first}:00 to {last}:00."
        if start <= datetime.now():
            return "That time has already passed."
        if any(m["start"] == start.strftime(FMT) for i, m in self.meetings.items() if i != ignore_id):
            return "That slot is taken."
        return None

    def find_my_meetings(self, caller: str = ""):
        if not caller:
            return "This call has no verified caller number, so I can't look up meetings. Offer to book one."
        mine = [m for m in self.meetings.values() if m.get("phone") == caller]
        return "; ".join(f"{m['id']}: {m['title']} at {m['start']}" for m in sorted(mine, key=lambda m: m["start"])) \
            or "No meetings booked from this caller's number."

    def find_free_slots(self, date: str):
        day = datetime.strptime(date, "%Y-%m-%d")
        first, last = config.OFFICE_HOURS
        slots = [day.replace(hour=first) + timedelta(minutes=config.SLOT_MINUTES * i)
                 for i in range((last - first) * 60 // config.SLOT_MINUTES)]
        free = [s.strftime("%H:%M") for s in slots if not self._check_slot(s)]
        return f"Free on {date}: {', '.join(free)}." if free else f"No free slots on {date}."

    def book_meeting(self, title: str, start: str, attendee: str, caller: str = ""):
        when = datetime.strptime(start, FMT)
        if problem := self._check_slot(when):
            return problem
        mid = f"M-{next(self._ids)}"
        self.meetings[mid] = {"id": mid, "title": title, "start": start, "attendee": attendee, "phone": caller}
        return f"Booked {mid}: {title} with {attendee} at {start}."

    def move_meeting(self, meeting_id: str, new_start: str, caller: str = ""):
        meeting = self.meetings.get(meeting_id.strip().upper())
        if not meeting or not caller or meeting.get("phone") != caller:   # same answer: ids don't leak
            return f"No meeting {meeting_id} for this caller."
        when = datetime.strptime(new_start, FMT)
        if problem := self._check_slot(when, ignore_id=meeting["id"]):
            return problem
        meeting["start"] = new_start
        return f"Moved {meeting['id']} ({meeting['title']}) to {new_start}."

    def cancel_meeting(self, meeting_id: str):
        return f"Cancelled {meeting_id}." if self.meetings.pop(meeting_id.strip().upper(), None) \
            else f"No meeting {meeting_id}."


def _schema(**props):
    """One required string property per keyword; the value is its description plus any format/pattern."""
    return {"type": "object", "properties": {k: {"type": "string", **v} for k, v in props.items()},
            "required": list(props)}


# The platform turns each inputSchema into SWAIG parameters, so these use the keys SWAIG allows
# (format, pattern). Caller-supplied values say what they are, their exact shape, and to ask.
DATE = {"format": "date",
        "description": "The day the caller wants, YYYY-MM-DD. Ask if not provided; never assume today."}
SLOT = {"pattern": r"^\d{4}-\d{2}-\d{2} ([01]\d|2[0-3]):[0-5]\d$",
        "description": "The free slot the caller chose, YYYY-MM-DD HH:MM, one returned by find_free_slots. "
                       "Ask if not provided."}
ATTENDEE = {"description": "Caller's full name exactly as they gave it (same value find_my_meetings uses). "
                           "Ask if not provided."}
TITLE = {"description": "Reason for the visit in the caller's words, e.g. Cleaning, Checkup. Ask if not provided."}
MEETING_ID = {"pattern": r"^[Mm]-\d+$", "description": "Meeting id from find_my_meetings, e.g. M-1001"}

TOOLS = {
    "find_free_slots": ("List free meeting start times on one date.", _schema(date=DATE)),
    "find_my_meetings": ("List the caller's own meetings with their ids. The caller is known from the call.",
                         _schema()),
    "book_meeting": ("Book a meeting in a free slot.", _schema(title=TITLE, start=SLOT, attendee=ATTENDEE)),
    "move_meeting": ("Move an existing meeting to a new free slot.", _schema(meeting_id=MEETING_ID, new_start=SLOT)),
    "cancel_meeting": ("Cancel a meeting.", _schema(meeting_id=MEETING_ID)),
}
CALLER_BOUND = {"find_my_meetings", "book_meeting", "move_meeting"}   # get caller= from the signed headers


def token_ok(token: str) -> bool:
    return token not in config.PLACEHOLDER_TOKENS


def caller_sig(caller: str) -> str:
    return hmac.new(config.MCP_CALLER_KEY.encode(), caller.encode(), hashlib.sha256).hexdigest()


def caller_headers(caller: str) -> dict:
    """What the agent adds to one call's MCP headers: the caller ID and proof it came from us."""
    return {"X-Caller": caller, "X-Caller-Sig": caller_sig(caller)} if caller else {}


def verified_caller(headers) -> str:
    caller, sig = headers.get("x-caller", ""), headers.get("x-caller-sig", "")
    return caller if caller and hmac.compare_digest(sig.encode(), caller_sig(caller).encode()) else ""


def seed_meetings(seed: list) -> list:
    day = datetime.now() + timedelta(days=1)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return [{"id": f"M-{1001 + i}", "title": m["title"], "attendee": m["attendee"], "phone": m.get("phone", ""),
             "start": f"{day:%Y-%m-%d} {m['time']}"} for i, m in enumerate(seed)]


def create_router(calendar: Calendar | None = None, scopes: dict | None = None, path: str = "/mcp") -> APIRouter:
    """The MCP endpoint as a router: POST <prefix><path>. app.py mounts it with path=""."""
    cal = calendar or Calendar(seed_meetings(config.SEED_MEETINGS))
    scopes = config.MCP_SCOPES if scopes is None else scopes
    router = APIRouter()

    def ok(req_id, result):
        return JSONResponse({"jsonrpc": "2.0", "id": req_id, "result": result})

    def err(req_id, code, message):
        return JSONResponse({"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}})

    @router.post(path)
    async def mcp(request: Request):
        token = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
        allowed = next((tools for t, tools in scopes.items()
                        if token_ok(t) and hmac.compare_digest(t.encode(), token.encode())), None)
        if allowed is None:
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        body = await request.json()
        method, req_id, params = body.get("method"), body.get("id"), body.get("params") or {}
        if "id" not in body:                       # a notification: accept, no body
            return Response(status_code=202)
        if method == "initialize":
            return ok(req_id, {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}},
                               "serverInfo": {"name": "reference-calendar", "version": "1.0.0"}})
        if method == "ping":
            return ok(req_id, {})
        if method == "tools/list":
            return ok(req_id, {"tools": [{"name": n, "description": d, "inputSchema": s}
                                         for n, (d, s) in TOOLS.items() if n in allowed]})
        if method == "tools/call":
            name, args = params.get("name"), params.get("arguments") or {}
            if name not in allowed or name not in TOOLS:
                return err(req_id, -32602, f"Unknown tool: {name}")
            bound = {"caller": verified_caller(request.headers)} if name in CALLER_BOUND else {}  # never from args
            try:
                kwargs = {k: str(args[k]) for k in TOOLS[name][1]["required"]}
                text, is_error = getattr(cal, name)(**kwargs, **bound), False
            except (KeyError, ValueError) as exc:
                text, is_error = f"Bad arguments: {exc}. Dates are YYYY-MM-DD, times YYYY-MM-DD HH:MM.", True
            log.info("mcp tools/call %s %s -> %s", name, args, text)
            return ok(req_id, {"content": [{"type": "text", "text": text}], "isError": is_error})
        return err(req_id, -32601, f"Method not found: {method}")

    router.calendar = cal
    return router


def create_app(calendar: Calendar | None = None, scopes: dict | None = None) -> FastAPI:
    """Standalone server: POST /mcp."""
    router = create_router(calendar, scopes)
    app = FastAPI()
    app.include_router(router)
    app.state.calendar = router.calendar
    return app


if __name__ == "__main__":
    if not token_ok(config.MCP_TOKEN):
        raise SystemExit("Set MCP_TOKEN to a long random string (see .env.example) before starting.")
    if not os.environ.get("MCP_CALLER_KEY"):
        raise SystemExit("Set MCP_CALLER_KEY to the same value as the agent's, so callers can be verified.")
    uvicorn.run(create_app(), host="0.0.0.0", port=config.MCP_PORT)
