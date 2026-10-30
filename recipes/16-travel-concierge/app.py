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


def money(amount: int) -> str:
    """Spoken price: '1180 dollars'. No '$' in text the platform speaks or the model reads."""
    return f"{amount} dollars"


def caller_spoke_after(raw_data: dict, function: str):
    """True if the caller said something after `function` last ran, False if not, None if the
    platform didn't post the conversation (swaig_post_conversation is set on the booking desk)."""
    log = raw_data.get("raw_call_log") or raw_data.get("call_log")
    if not isinstance(log, list):
        return None
    ran = None
    for i, entry in enumerate(log):
        calls = [c.get("function", {}).get("name") for c in entry.get("tool_calls") or []]
        if entry.get("function_name") == function or function in calls:
            ran = i
    if ran is None:
        return False
    return any(e.get("role") == "user" and str(e.get("content") or "").strip() for e in log[ran + 1:])


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
                                 f"{record['summary']} {outcome} You already welcomed them back with that "
                                 "outcome and asked if there's anything else. Don't repeat it. That booking "
                                 "is finished: there's nothing to confirm or finalize. If they're done, thank "
                                 "them and say goodbye. Call handoff_to_booking only for a new trip.")
        # The platform speaks this verbatim, so the outcome the caller hears comes from code.
        agent.set_param("static_greeting", f"Welcome back. {outcome} Is there anything else I can help with?")

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
        self.set_global_data({"summary": "No handoff on file.", "trip": None, "options_read": "none."})
        self.set_prompt_llm_params(model=config.BOOKING_MODEL)
        ctx = self.define_contexts().add_context("default")
        # The options are spoken by the platform (static_greeting from from_handoff, say() in
        # search_flights), never paraphrased by the model, so the caller always hears them.
        ctx.add_step("choose") \
            .set_text("The caller has just heard these flight options: ${global_data.options_read} "
                      "Wait for them to pick one, then call hold_flight with its number. Don't ask for a "
                      "departure city or anything else in the note. If they want the options again, call "
                      "search_flights. If there's no trip on file, or they want to go back, call "
                      "return_to_concierge.") \
            .set_functions(["search_flights", "hold_flight", "return_to_concierge"]) \
            .set_valid_steps([])
        ctx.add_step("done") \
            .set_text("The hold was read back and the caller was asked if they need anything else. Wait "
                      "for their answer. Only after they say they're done, call return_to_concierge.") \
            .set_functions(["return_to_concierge"]) \
            .set_valid_steps([])
        # Posts the conversation with each SWAIG call: return_to_concierge checks the caller answered.
        self.set_param("swaig_post_conversation", True)
        self.set_dynamic_config_callback(self.from_handoff)

    def from_handoff(self, query_params, body_params, headers, agent):
        """Rebuild global_data from the one-time handoff record named in the transfer URL."""
        token = query_params.get("h")
        record = handoff.claim(token)
        if not record:
            return
        trip = record["trip"]
        options = self._numbered(trip)
        agent.set_global_data({"handoff_id": token, "summary": record["summary"], "trip": trip,
                               "looked_up": record.get("looked_up") or [], "options": options,
                               "options_read": self._read(options, trip) or "none."})
        # The destination, party and dates are known from the handoff, so the options are known
        # before the AI starts. The platform reads them verbatim as the opening line.
        party = f"{trip['travelers']} traveler{'s' if trip['travelers'] > 1 else ''}"
        opening = f"Hi, this is the booking desk. I have {party} to {trip['destination_name']}. "
        if options:
            opening += f"{self._read(options, trip)} Which option would you like?"
        else:
            opening += (f"I don't have a flight with {trip['travelers']} seats right now. "
                        "I can take you back to the concierge.")
        agent.set_param("static_greeting", opening)
        agent.set_param("static_greeting_no_barge", True)

    def _options(self, trip):
        flights = self.destinations[trip["destination"]]["flights"]
        return [f for f in flights if f["seats"] >= trip["travelers"]]

    def _numbered(self, trip):
        """Code numbers the bookable flights; the model only ever sees and picks a number."""
        return {str(n): f for n, f in enumerate(self._options(trip), 1)}

    @staticmethod
    def _read(options, trip):
        return " ".join(f"Option {n}: departing {spoken(f['depart'])}, {money(f['price'] * trip['travelers'])} "
                        f"total for {trip['travelers']}." for n, f in options.items())

    @AgentBase.tool(name="search_flights", description="List flights for the trip in the handoff.",
                    parameters={"type": "object", "properties": {}})
    def search_flights(self, args, raw_data):
        trip = (raw_data.get("global_data") or {}).get("trip")
        if not trip:
            return FunctionResult("There's no trip on file. Offer to go back to the concierge.")
        options = self._numbered(trip)
        if not options:
            return FunctionResult(f"No flights to {trip['destination_name']} have {trip['travelers']} seats. "
                                  "Offer to go back to the concierge.")
        lines = self._read(options, trip)
        # say(): the platform speaks the options verbatim. The step text carries them for the model
        # (${global_data.options_read}). Keep this response short: on live calls 55b18265 and
        # cc96320f the platform logged longer tool results as empty, and the model then guessed.
        return FunctionResult("Options read aloud. Wait for the pick, then call hold_flight.") \
            .say(f"{lines} Which option would you like?") \
            .update_global_data({"options": options, "options_read": lines})

    @AgentBase.tool(name="hold_flight", description="Hold seats on one option from search_flights.",
                    parameters={"type": "object", "required": ["option"], "properties": {
                        "option": {"type": "integer", "description": "The option number, e.g. 2"}}})
    def hold_flight(self, args, raw_data):
        gd = raw_data.get("global_data") or {}
        trip, options = gd.get("trip"), gd.get("options") or {}
        if not trip:
            return FunctionResult("There's no trip on file. Offer to go back to the concierge.")
        if not options:
            return FunctionResult("Call search_flights first and read the options.")
        flight = options.get(str(args.get("option")).strip())
        if not flight or flight not in self._options(trip):          # the stored option, still bookable
            return FunctionResult(f"Option {args.get('option')} isn't one of the options. "
                                  f"Ask the caller to pick 1 to {len(options)}.")
        flight_id = flight["id"]
        total = flight["price"] * trip["travelers"]
        booking = {"ref": f"R-{(gd.get('handoff_id') or 'direct')[:6].upper()}", "flight_id": flight_id,
                   "travelers": trip["travelers"], "total": total,
                   "readback": f"{trip['travelers']} seats on {flight_id} to {trip['destination_name']}, "
                               f"departing {spoken(flight['depart'])}, {money(total)} total"}
        config.BOOKINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with config.BOOKINGS_FILE.open("a") as f:
            f.write(json.dumps({"call_id": raw_data.get("call_id"), **booking}) + "\n")
        # The readback and the "anything else?" question are spoken by the platform. The done step
        # then waits: return_to_concierge refuses until the caller has answered.
        return FunctionResult(f"Held {flight_id}, read back already. Wait for the caller's answer.") \
            .say(f"Done. I've held {booking['readback']}, reference {booking['ref']}. "
                 "Is there anything else you need for this booking?") \
            .update_global_data({"booking": booking}).swml_change_step("done")

    @AgentBase.tool(name="return_to_concierge", description="Send the caller back to the concierge.",
                    parameters={"type": "object", "properties": {}})
    def return_to_concierge(self, args, raw_data):
        gd = raw_data.get("global_data") or {}
        if gd.get("booking") and caller_spoke_after(raw_data, "hold_flight") is False:
            # Code, not the prompt: no hand-back in the same breath as the hold.
            return FunctionResult("The caller hasn't answered yet. Wait for them to say they're done, "
                                  "then call return_to_concierge.")
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
