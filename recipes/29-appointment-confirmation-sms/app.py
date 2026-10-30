"""Appointment confirmation over voice and SMS, with one booking record shared by both.

Governance points:
- The SMS text is built by the handler from the stored booking. The model never writes
  the date, time or confirmation number, and never chooses the destination number.
- reschedule_appointment changes the booking named in global_data, which dynamic config
  preloaded from the store. The model can't pick a different booking.
- book and reschedule have valid_steps=[]: only handlers move the call, and confirmed has no tools.
"""
import asyncio
import json
import re
from urllib.parse import parse_qsl
from xml.sax.saxutils import escape

from fastapi import APIRouter, Request, Response
from signalwire import AgentBase, FunctionResult
from signalwire.core.security import validate_webhook_signature

import config

SLOT = {
    "date": {"type": "string", "description": "Slot date, YYYY-MM-DD, from the open slots list"},
    "time": {"type": "string", "description": "Slot time, HH:MM, from the open slots list"},
}


# --- booking store (data/bookings.json; swap for your scheduling system) ----

def load_bookings() -> list:
    return json.loads(config.BOOKINGS_FILE.read_text()) if config.BOOKINGS_FILE.exists() else []


def save_bookings(rows: list) -> None:
    config.BOOKINGS_FILE.write_text(json.dumps(rows, indent=2) + "\n")


def find_booking(phone: str = "", confirmation: str = "") -> dict | None:
    """The newest booking for a phone number, or the one with this confirmation number."""
    for row in reversed(load_bookings()):
        if (phone and row["phone"] == phone) or (confirmation and row["confirmation"] == confirmation):
            return row
    return None


def next_confirmation(rows: list) -> str:
    nums = [int(r["confirmation"].removeprefix(config.CONFIRMATION_PREFIX)) for r in rows] or [1000]
    return f"{config.CONFIRMATION_PREFIX}{max(nums) + 1}"


def sms_body(booking: dict) -> str:
    return config.SMS_TEMPLATE.format(business=config.BUSINESS_NAME, **booking)


EMPTY_CXML = '<?xml version="1.0" encoding="UTF-8"?><Response></Response>'


def cxml_reply(text: str) -> str:
    return f'<?xml version="1.0" encoding="UTF-8"?><Response><Message>{escape(text)}</Message></Response>'


class ConfirmationAgent(AgentBase):
    def __init__(self, **kwargs):
        super().__init__(name="appointment-confirmation", route=config.ROUTE, port=config.PORT, **kwargs)
        self.slots = json.loads(config.SLOTS_FILE.read_text())

        self.add_language("English", config.LANGUAGE_CODE, config.VOICE)
        self.prompt_add_section("Role", f"You book appointments for {config.BUSINESS_NAME}. Be brief.")
        self.prompt_add_section(
            "Open slots", bullets=[f"{d}: {', '.join(times)}" for d, times in self.slots.items()]
        )

        ctx = self.define_contexts().add_context("default")
        ctx.add_step("book") \
            .set_text("Ask for the caller's name and which open slot they want, then call book_appointment.") \
            .set_functions(["book_appointment"]) \
            .set_valid_steps([])
        ctx.add_step("reschedule") \
            .set_text(
                "You called ${global_data.booking.name} back because they texted about booking "
                "${global_data.booking.confirmation} on ${global_data.booking.date} at "
                "${global_data.booking.time}. Ask which open slot they want instead, then call "
                "reschedule_appointment."
            ) \
            .set_functions(["reschedule_appointment"]) \
            .set_valid_steps([])
        ctx.add_step("confirmed") \
            .set_text(
                "Tell the caller they're booked for ${global_data.booking.date} at "
                "${global_data.booking.time}, confirmation ${global_data.booking.confirmation}, "
                "and that the details are on their phone by text. Then say goodbye."
            ) \
            .set_functions([]) \
            .set_valid_steps([]) \
            .set_end(True)

        self.set_dynamic_config_callback(self.preload)
        self.mount(self.sms_router())

    # --- per-call setup: who is on the line, and which booking (if any) ---------

    def preload(self, query_params, body_params, headers, agent):
        call = body_params.get("call")
        if not isinstance(call, dict):
            return  # a tool call: global_data is already on the call
        booking = find_booking(confirmation=query_params.get("booking", ""))
        if booking:  # the REST dial-back: start in reschedule with the booking loaded
            agent.set_global_data({"caller": booking["phone"], "booking": booking})
            agent.define_contexts().get_context("default").set_initial_step("reschedule")
        else:
            agent.set_global_data({"caller": call.get("from", "")})

    # --- tools -----------------------------------------------------------------

    def slot_problem(self, date: str, time: str, keep: str = "") -> str | None:
        if time not in self.slots.get(date, []):
            return "That isn't an open slot. Offer the caller one from the open slots list."
        if any(r["date"] == date and r["time"] == time and r["confirmation"] != keep for r in load_bookings()):
            return "That slot was just taken. Offer the caller a different one."
        return None

    def confirm(self, booking: dict, said: str) -> FunctionResult:
        return (
            FunctionResult(f"{said} I've texted the details to the caller's phone.")
            .update_global_data({"booking": booking})
            .send_sms(to_number=booking["phone"], from_number=config.SMS_FROM, body=sms_body(booking))
            .swml_change_step("confirmed")
        )

    @AgentBase.tool(
        name="book_appointment",
        description="Book an open slot for the caller.",
        parameters={"type": "object", "required": ["name", "date", "time"],
                    "properties": {"name": {"type": "string", "description": "Caller's name"}, **SLOT}},
    )
    def book_appointment(self, args, raw_data):
        date, time = str(args.get("date", "")).strip(), str(args.get("time", "")).strip()
        if problem := self.slot_problem(date, time):
            return FunctionResult(problem)
        phone = (raw_data.get("global_data") or {}).get("caller") or raw_data.get("caller_id_num", "")
        rows = load_bookings()
        booking = {"confirmation": next_confirmation(rows), "phone": phone,
                   "name": str(args.get("name", "")).strip(), "date": date, "time": time}
        save_bookings(rows + [booking])
        return self.confirm(booking, "Booked.")

    @AgentBase.tool(name="reschedule_appointment", description="Move the caller's booking to another open slot.",
                    parameters={"type": "object", "properties": SLOT, "required": ["date", "time"]})
    def reschedule_appointment(self, args, raw_data):
        current = (raw_data.get("global_data") or {}).get("booking") or {}
        rows = load_bookings()
        row = next((r for r in rows if r["confirmation"] == current.get("confirmation")), None)
        if row is None:
            return FunctionResult("I can't find that booking. Apologize and say the office will call back.")
        date, time = str(args.get("date", "")).strip(), str(args.get("time", "")).strip()
        if problem := self.slot_problem(date, time, keep=row["confirmation"]):
            return FunctionResult(problem)
        row.update(date=date, time=time)
        save_bookings(rows)
        return self.confirm(row, "Rescheduled.")

    # --- inbound SMS (laml_webhooks: a form-encoded cXML-style POST) ------------

    def dial_request(self, booking: dict) -> dict:
        """REST calling.dial kwargs: call the customer and run this agent with the booking preloaded."""
        url = f"{self.get_full_url(include_auth=True).rstrip('/')}{config.ROUTE}?booking={booking['confirmation']}"
        return {"from_": config.DIAL_FROM, "to": booking["phone"], "url": url}

    def dial_back(self, booking: dict) -> dict:
        from signalwire.rest import RestClient  # creds from SIGNALWIRE_* env
        return RestClient().calling.dial(**self.dial_request(booking))

    def handle_sms(self, sender: str, body: str) -> str:
        booking = find_booking(phone=sender)
        if booking is None:
            return f"{config.BUSINESS_NAME}: we couldn't find a booking for this number. Call us to book."
        if set(re.findall(r"[a-z]+", body.lower())) & set(config.ESCALATE_WORDS):
            self.dial_back(booking)
            return f"{config.BUSINESS_NAME}: we're calling you now to change {booking['confirmation']}."
        return sms_body(booking)

    def sms_router(self) -> APIRouter:
        router = APIRouter()

        @router.post(config.SMS_ROUTE)
        async def inbound_sms(request: Request) -> Response:
            raw = (await request.body()).decode()
            signature = request.headers.get("X-SignalWire-Signature", "")
            if config.SIGNING_KEY and not validate_webhook_signature(
                config.SIGNING_KEY, signature, config.PUBLIC_URL.rstrip("/") + config.SMS_ROUTE, raw
            ):
                return Response(status_code=403)
            form = dict(parse_qsl(raw))
            if form.get("From", "") == config.SMS_FROM:
                # Our own text (a number texting itself, or a reply echoed back): answering it
                # would start an auto-reply loop. Return cXML with no <Message>.
                return Response(EMPTY_CXML, media_type="application/xml")
            reply = await asyncio.to_thread(self.handle_sms, form.get("From", ""), form.get("Body", ""))
            return Response(cxml_reply(reply), media_type="application/xml")

        return router


agent = ConfirmationAgent()

if __name__ == "__main__":
    agent.run()
