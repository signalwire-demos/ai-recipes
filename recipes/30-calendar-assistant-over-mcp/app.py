"""AI calendar assistant over MCP: the calendar tools come from an MCP server.

Governance point: the voice agent owns no calendar code. add_mcp_server() puts
the server in the SWML, and SignalWire's platform discovers its tools when each
call starts. What the caller can do is decided by the server and the token: the
agent's token is scoped to find/book/move, so cancel_meeting is never listed to
this agent, and free-slot answers never say whose meeting is in the way.
"""
import logging
from datetime import datetime
from urllib.parse import urlparse

from signalwire import AgentBase, FunctionResult

import config

log = logging.getLogger("calendar-assistant")


class CalendarAgent(AgentBase):
    def __init__(self, **kwargs):
        super().__init__(name="calendar-assistant", route=config.ROUTE, port=config.PORT, **kwargs)
        headers = {"Authorization": f"Bearer {config.MCP_TOKEN}"} if config.MCP_TOKEN else None
        self.add_mcp_server(config.MCP_URL, headers=headers)
        if urlparse(config.MCP_URL).hostname in ("localhost", "127.0.0.1", "calendar"):
            log.warning("MCP_URL %s is not public: SignalWire can't reach it on a live call", config.MCP_URL)

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
        now = datetime.now()
        return FunctionResult(f"Today is {now:%A}, {now:%Y-%m-%d}. It is {now:%H:%M}.")


agent = CalendarAgent()

if __name__ == "__main__":
    agent.run()
