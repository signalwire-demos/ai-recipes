"""Travel concierge: two agents on one server, with a handler-written handoff between them.

Governance point: the concierge can't book and the booking desk can't wander. Each handoff is
a final swml_transfer to the other agent. The handler writes the handoff (a summary it builds
from structured fields, plus trip or booking state) to a short-lived store and puts only a
one-time token in the transfer URL. The receiving agent's dynamic config callback claims that
record and rebuilds its context. The booking tools read the destination and party size from
global_data, never from model arguments. No transcript crosses either handoff.
"""
import json
from datetime import datetime
from urllib.parse import urlsplit, urlunsplit

from signalwire import AgentBase, AgentServer, FunctionResult

import config
import handoff


def load_destinations() -> dict:
    return json.loads(config.DESTINATIONS_FILE.read_text())


def spoken(depart: str) -> str:
    """'2026-12-11 18:30' -> 'December 11 at 18:30', so the model matches what callers say."""
    when = datetime.strptime(depart, "%Y-%m-%d %H:%M")
    return f"{when:%B} {when.day} at {when:%H:%M}"


def agent_url(agent: AgentBase, route: str, token: str) -> str:
    """Transfer target with basic auth, so the platform can fetch the other agent's SWML."""
    user, password = agent.get_basic_auth_credentials()[:2]
    parts = urlsplit(config.PUBLIC_URL)
    netloc = f"{user}:{password}@{parts.netloc}"
    return urlunsplit((parts.scheme, netloc, route, f"h={token}", ""))


class ConciergeDesk(AgentBase):
    def __init__(self, **kwargs):
        super().__init__(name="concierge", route=config.CONCIERGE_ROUTE, **kwargs)
        self.destinations = load_destinations()
        self.add_language("English", config.LANGUAGE_CODE, config.CONCIERGE_VOICE)
        self.prompt_add_section(
            "Role",
            f"You are the travel concierge at {config.AGENCY_NAME}. Answer questions about our "
            "destinations with destination_info. You can't check flights or book. When the caller "
            "wants to book, confirm the destination, how many travelers and which month, then call "
            "handoff_to_booking.",
            bullets=[f"We offer: {', '.join(d['name'] for d in self.destinations.values())}"],
        )
        self.set_global_data({"looked_up": []})
        self.define_contexts().add_context("default").add_step("explore") \
            .set_text("Help the caller choose a trip. Hand off to booking when they're ready.") \
            .set_functions(["destination_info", "handoff_to_booking"]) \
            .set_valid_steps([])
        self.set_dynamic_config_callback(self.from_booking)

    def from_booking(self, query_params, body_params, headers, agent):
        """A caller coming back from /booking: claim the return record and brief this agent."""
        record = handoff.claim(query_params.get("h"))
        if not record:
            return
        agent.set_global_data({"looked_up": record.get("looked_up") or [], "booking": record.get("booking")})
        held = record.get("booking")
        outcome = (f"The booking desk held {held['readback']}, reference {held['ref']}." if held
                   else "Nothing was booked.")
        # Written here from the stored fields; the booking agent's conversation never crosses over.
        agent.prompt_add_section("Returning caller", f"The caller is back from the booking desk. Trip: "
                                 f"{record['summary']} {outcome} Greet them, confirm that outcome in one "
                                 "sentence, and ask if there's anything else.")

    def _find(self, name):
        key = str(name or "").strip().lower()
        return key, self.destinations.get(key)

    @AgentBase.tool(name="destination_info", description="Best time to visit and tips for a destination.",
                    parameters={"type": "object", "required": ["destination"], "properties": {
                        "destination": {"type": "string", "description": "e.g. lisbon"}}})
    def destination_info(self, args, raw_data):
        key, dest = self._find(args.get("destination"))
        if not dest:
            return FunctionResult(f"We don't offer {args.get('destination')}. Offer one we do.")
        looked = (raw_data.get("global_data") or {}).get("looked_up") or []
        return FunctionResult(f"{dest['name']}: best {dest['best_months']}. {dest['notes']}") \
            .update_global_data({"looked_up": sorted(set(looked) | {key})})

    @AgentBase.tool(name="handoff_to_booking", description="Hand the caller to the booking desk.",
                    parameters={"type": "object", "required": ["destination", "travelers", "month"],
                                "properties": {
                                    "destination": {"type": "string", "description": "e.g. lisbon"},
                                    "travelers": {"type": "integer", "description": "Number of travelers"},
                                    "month": {"type": "string", "description": "Month of travel"}}})
    def handoff_to_booking(self, args, raw_data):
        key, dest = self._find(args.get("destination"))
        travelers = int(args.get("travelers") or 0)
        if not dest:
            return FunctionResult(f"We don't offer {args.get('destination')}. Ask where they'd like to go.")
        if not 1 <= travelers <= config.MAX_TRAVELERS:
            return FunctionResult(f"We book 1 to {config.MAX_TRAVELERS} travelers. Ask how many.")
        month = str(args.get("month") or "").strip().capitalize()
        looked = (raw_data.get("global_data") or {}).get("looked_up") or []
        # The summary is written here, from validated fields. It is not the model's prose.
        summary = (f"{travelers} traveler{'s' if travelers > 1 else ''} to {dest['name']} in {month}. "
                   f"Destinations discussed: {', '.join(looked) or key}.")
        token = handoff.save({
            "call_id": raw_data.get("call_id"), "summary": summary, "looked_up": looked,
            "trip": {"destination": key, "destination_name": dest["name"], "travelers": travelers,
                     "month": month},
        })
        # final=True: this AI ends and /booking takes the call. return_to_concierge brings it back.
        return FunctionResult("Tell the caller you're connecting them to the booking desk.", post_process=True) \
            .swml_transfer(agent_url(self, config.BOOKING_ROUTE, token), "", final=True)


class BookingDesk(AgentBase):
    def __init__(self, **kwargs):
        super().__init__(name="booking", route=config.BOOKING_ROUTE, **kwargs)
        self.destinations = load_destinations()
        self.add_language("English", config.LANGUAGE_CODE, config.BOOKING_VOICE)
        self.prompt_add_section(
            "Role",
            f"You are the booking desk at {config.AGENCY_NAME}. The concierge handed this caller "
            "to you with this note: ${global_data.summary} Don't re-ask anything in the note.",
        )
        self.set_global_data({"summary": "No handoff on file.", "trip": None})
        ctx = self.define_contexts().add_context("default")
        ctx.add_step("choose") \
            .set_text("Greet the caller and confirm the trip in the note. Call search_flights; it reads "
                      "the options aloud. When they pick one, call hold_flight. If there's no trip on file, "
                      "or they want to go back, call return_to_concierge.") \
            .set_functions(["search_flights", "hold_flight", "return_to_concierge"]) \
            .set_valid_steps([])
        ctx.add_step("done") \
            .set_text("Read back the hold: ${global_data.booking.readback}. When the caller is done, "
                      "call return_to_concierge.") \
            .set_functions(["return_to_concierge"])
        self.set_dynamic_config_callback(self.from_handoff)

    def from_handoff(self, query_params, body_params, headers, agent):
        """Rebuild global_data from the one-time handoff record named in the transfer URL."""
        token = query_params.get("h")
        record = handoff.claim(token)
        if record:
            agent.set_global_data({"handoff_id": token, "summary": record["summary"], "trip": record["trip"],
                                   "looked_up": record.get("looked_up") or []})

    def _options(self, trip):
        flights = self.destinations[trip["destination"]]["flights"]
        return [f for f in flights if f["seats"] >= trip["travelers"]]

    @AgentBase.tool(name="search_flights", description="List flights for the trip in the handoff.",
                    parameters={"type": "object", "properties": {}})
    def search_flights(self, args, raw_data):
        trip = (raw_data.get("global_data") or {}).get("trip")
        if not trip:
            return FunctionResult("There's no trip on file. Offer to go back to the concierge.")
        options = self._options(trip)
        if not options:
            return FunctionResult(f"No flights to {trip['destination_name']} have {trip['travelers']} seats.")
        listing = "; ".join(f"{f['id']} departing {spoken(f['depart'])}, ${f['price'] * trip['travelers']} "
                            f"total for {trip['travelers']}" for f in options)
        # The platform speaks the inventory verbatim, so the model can't paraphrase or invent flights.
        return FunctionResult(f"The caller just heard these, word for word: {listing}. These are the only "
                              "flights. Don't repeat or add any. Ask which one; then call hold_flight.") \
            .say(f"Flights to {trip['destination_name']}: {listing}.")

    @AgentBase.tool(name="hold_flight", description="Hold seats on one of the listed flights.",
                    parameters={"type": "object", "required": ["flight_id"], "properties": {
                        "flight_id": {"type": "string", "description": "e.g. FL-101"}}})
    def hold_flight(self, args, raw_data):
        gd = raw_data.get("global_data") or {}
        trip = gd.get("trip")
        if not trip:
            return FunctionResult("There's no trip on file. Offer to go back to the concierge.")
        flight_id = str(args.get("flight_id") or "").strip().upper()
        flight = next((f for f in self._options(trip) if f["id"] == flight_id), None)
        if not flight:
            return FunctionResult(f"{flight_id} isn't one of the available flights. Call search_flights.")
        total = flight["price"] * trip["travelers"]
        booking = {"ref": f"R-{(gd.get('handoff_id') or 'direct')[:6].upper()}", "flight_id": flight_id,
                   "travelers": trip["travelers"], "total": total,
                   "readback": f"{trip['travelers']} seats on {flight_id} to {trip['destination_name']}, "
                               f"departing {spoken(flight['depart'])}, ${total} total"}
        config.BOOKINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with config.BOOKINGS_FILE.open("a") as f:
            f.write(json.dumps({"call_id": raw_data.get("call_id"), **booking}) + "\n")
        return FunctionResult(f"Held: {booking['readback']}.") \
            .update_global_data({"booking": booking}).swml_change_step("done")

    @AgentBase.tool(name="return_to_concierge", description="Send the caller back to the concierge.",
                    parameters={"type": "object", "properties": {}})
    def return_to_concierge(self, args, raw_data):
        gd = raw_data.get("global_data") or {}
        # A fresh one-time token: structured summary + booking result, never the transcript.
        token = handoff.save({"call_id": raw_data.get("call_id"), "looked_up": gd.get("looked_up") or [],
                              "summary": gd.get("summary") or "No trip on file.", "booking": gd.get("booking")})
        return FunctionResult("Tell the caller you're handing them back to the concierge.", post_process=True) \
            .swml_transfer(agent_url(self, config.CONCIERGE_ROUTE, token), "", final=True)


agent = ConciergeDesk()      # the entry point; `swaig-test app.py` picks this one by default
booking = BookingDesk()      # `swaig-test app.py --route /booking`
server = AgentServer(host="0.0.0.0", port=config.PORT)
server.register(agent, config.CONCIERGE_ROUTE)
server.register(booking, config.BOOKING_ROUTE)

if __name__ == "__main__":
    server.run()
