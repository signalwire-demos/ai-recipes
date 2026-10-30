"""AI calendar assistant over MCP: the calendar tools come from an MCP server.

Governance point: the voice agent owns no calendar code. add_mcp_server() puts
the server in the SWML, and SignalWire's platform discovers its tools when each
call starts. What the caller can do is decided by the server and the token: the
agent's token is scoped to find/book/move, so cancel_meeting is never listed to
this agent, and free-slot answers never say whose meeting is in the way.

By default this same app also serves the reference calendar MCP server at
config.MCP_CALENDAR_PATH, so one public URL covers both. Set MCP_URL to use another.
"""
import logging
import threading
from collections import OrderedDict
from datetime import datetime
from urllib.parse import urlparse

from signalwire import AgentBase, FunctionResult

import config
import mcp_calendar

log = logging.getLogger("calendar-assistant")


class CalendarAgent(AgentBase):
    def __init__(self, **kwargs):
        super().__init__(name="calendar-assistant", route=config.ROUTE, port=config.PORT, **kwargs)
        self._today_calls: OrderedDict[str, int] = OrderedDict()   # call_id -> get_today count
        self._today_lock = threading.Lock()
        if config.SERVE_REFERENCE_CALENDAR:
            if not config.MCP_TOKEN:   # an empty token is never accepted: every MCP request gets 401
                log.warning("MCP_TOKEN is not set: the calendar at %s refuses every request", config.MCP_CALENDAR_PATH)
            # Same app, same port, same tunnel: POST <PUBLIC_URL>/mcp-calendar. Bearer-token
            # auth only (the platform sends the MCP headers from the SWML, not basic auth).
            self.calendar_router = mcp_calendar.create_router(path="")
            self.mount(self.calendar_router, prefix=config.MCP_CALENDAR_PATH)
        headers = {"Authorization": f"Bearer {config.MCP_TOKEN}"} if config.MCP_TOKEN else None
        self.add_mcp_server(config.MCP_URL, headers=headers)
        if urlparse(config.MCP_URL).hostname in ("localhost", "127.0.0.1", "calendar"):
            log.warning("MCP_URL %s is not public: SignalWire can't reach it on a live call. "
                        "Set PUBLIC_URL (or MCP_URL).", config.MCP_URL)

        self.add_language("English", config.LANGUAGE_CODE, config.VOICE)
        self.prompt_add_section(
            "Role",
            f"You book and move appointments for {config.BUSINESS_NAME} by phone. Be brief.",
        )
        self.prompt_add_section("Rules", bullets=[
            "Call get_today first so you can turn 'next Tuesday' into a date.",
            "Ask for the caller's full name before anything else.",
            "To book: find_free_slots for the date, offer at most three times, then book_meeting.",
            "To move: find_my_meetings with the caller's name, confirm which one, "
            "find_free_slots, then move_meeting.",
            "Read back the result the tool gives you. If a tool says a slot is taken, offer another.",
            "You can't cancel meetings by phone. Offer to move the meeting instead.",
        ])

    @AgentBase.tool(
        name="get_today",
        description="Get today's date and weekday in the office's time zone.",
        parameters={"type": "object", "properties": {}},
    )
    def get_today(self, args, raw_data):
        count = self._count_today_call((raw_data or {}).get("call_id") or "")
        if count > config.GET_TODAY_MAX_CALLS:
            # The model keeps asking for the date: the calendar tools almost certainly never
            # reached this call. Say so and take this tool away so the loop stops.
            log.warning("get_today called %d times on one call: are the MCP tools reachable at %s?",
                        count, config.MCP_URL)
            return FunctionResult(
                "The calendar is unavailable right now, so you can't book or move anything on this "
                "call. Apologize, ask the caller to try again later, and say goodbye. Don't call "
                "get_today again."
            ).toggle_functions([{"function": "get_today", "active": False}])
        now = datetime.now()
        reply = f"Today is {now:%A}, {now:%Y-%m-%d}. It is {now:%H:%M}."
        if count > 1:
            reply += (" You already have today's date; don't call get_today again. Use the calendar "
                      "tools (find_free_slots, find_my_meetings, book_meeting, move_meeting). If you "
                      "don't have them, tell the caller the calendar is unavailable.")
        return FunctionResult(reply)

    def _count_today_call(self, call_id: str) -> int:
        with self._today_lock:
            count = self._today_calls.pop(call_id, 0) + 1
            self._today_calls[call_id] = count
            while len(self._today_calls) > 1000:       # bounded: forget the oldest calls
                self._today_calls.popitem(last=False)
            return count


agent = CalendarAgent()

if __name__ == "__main__":
    agent.run()
