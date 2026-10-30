"""The concierge agent: one definition for every channel.

Nothing in this file knows about phones, SMS or browsers. The same class answers a
voice call (the platform fetches its SWML at ROUTE) and a text conversation (the AI
Chat service fetches the very same SWML as its config_url). Recipes #27 (SMS) and #28
(web chat) ship this file unchanged; only app.py, the channel wiring, differs.

Governance, identical on every channel:
- verify_guest is the only tool until the handler has matched room + last name.
- request_service files a request for the room in global_data, set by verify_guest.
  The model never supplies a room number, so it can't file for someone else's room.
- Only the service names in config.SERVICES can be requested.
"""
import json
import time

from signalwire import AgentBase, FunctionResult

import config


def load_json(path):
    return json.loads(path.read_text())


def channel_of(raw_data: dict) -> str:
    # The AI Chat service marks its requests conversation_type "chat"; calls don't set it.
    return "text" if raw_data.get("conversation_type") == "chat" else "voice"


class HotelConcierge(AgentBase):
    def __init__(self, **kwargs):
        kwargs.setdefault("route", config.ROUTE)
        kwargs.setdefault("port", config.PORT)
        super().__init__(name="hotel-concierge", **kwargs)
        self.guests = load_json(config.GUESTS_FILE)
        self.amenities = load_json(config.AMENITIES_FILE)

        self.add_language("English", config.LANGUAGE_CODE, config.VOICE)  # voice only
        self.prompt_add_section(
            "Role",
            f"You are the concierge at {config.HOTEL_NAME}. Guests reach you by phone or by "
            "text. Keep every reply to one or two short sentences, with no lists or markdown.",
        )

        ctx = self.define_contexts().add_context("default")
        ctx.add_step("verify") \
            .set_text("Ask for the guest's room number and last name, then call verify_guest.") \
            .set_functions(["verify_guest"]) \
            .set_valid_steps([])  # only the verify_guest handler can open the concierge step
        ctx.add_step("concierge") \
            .set_text(
                "Help ${global_data.guest.name} in room ${global_data.guest.room}. Answer amenity "
                "questions with amenity_hours and log requests with request_service. "
                f"You can only log these requests: {', '.join(config.SERVICES)}."
            ) \
            .set_functions(["amenity_hours", "request_service"]) \
            .set_valid_steps([])

    @AgentBase.tool(
        name="verify_guest",
        description="Check the guest's room number and last name against the hotel register.",
        parameters={
            "type": "object",
            "properties": {
                "room": {"type": "string", "description": "Room number, digits only"},
                "last_name": {"type": "string", "description": "Guest's last name"},
            },
            "required": ["room", "last_name"],
        },
    )
    def verify_guest(self, args, raw_data):
        room = "".join(ch for ch in str(args.get("room", "")) if ch.isdigit())
        last = str(args.get("last_name", "")).strip().lower()
        guest = next((g for g in self.guests if g["room"] == room and g["last_name"] == last), None)
        if guest is None:
            return FunctionResult("That room and name don't match. Ask the guest to check both.")
        return (
            FunctionResult(f"Verified {guest['name']} in room {room}. Ask how you can help.")
            .update_global_data({"guest": {"room": room, "name": guest["name"]}})
            .swml_change_step("concierge")
        )

    @AgentBase.tool(
        name="amenity_hours",
        description="Look up hours and location for a hotel amenity.",
        parameters={
            "type": "object",
            "properties": {"amenity": {"type": "string", "description": "e.g. pool, gym, breakfast"}},
            "required": ["amenity"],
        },
    )
    def amenity_hours(self, args, raw_data):
        name = str(args.get("amenity", "")).strip().lower()
        info = self.amenities.get(name)
        if info is None:
            return FunctionResult(f"We don't list that. Amenities: {', '.join(self.amenities)}.")
        return FunctionResult(f"The {name}: {info}.")

    @AgentBase.tool(
        name="request_service",
        description="Log a service request for the verified guest's room.",
        parameters={
            "type": "object",
            "properties": {
                "service": {"type": "string", "enum": list(config.SERVICES), "description": "Which service"},
                "notes": {"type": "string", "description": "Optional details, e.g. a time"},
            },
            "required": ["service"],
        },
    )
    def request_service(self, args, raw_data):
        guest = (raw_data.get("global_data") or {}).get("guest")
        if not guest:
            return FunctionResult("Verify the guest first.")
        service = str(args.get("service", "")).strip().lower()
        if service not in config.SERVICES:
            return FunctionResult(f"I can only log: {', '.join(config.SERVICES)}.")
        rows = load_json(config.REQUESTS_FILE) if config.REQUESTS_FILE.exists() else []
        ticket = f"SR-{len(rows) + 101}"
        rows.append({"ticket": ticket, "room": guest["room"], "service": service,
                     "notes": str(args.get("notes", "")), "channel": channel_of(raw_data),
                     "at": int(time.time())})
        config.REQUESTS_FILE.write_text(json.dumps(rows, indent=2) + "\n")
        return FunctionResult(f"Logged {service} for room {guest['room']}, ticket {ticket}.")
