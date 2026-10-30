"""Appointment reminder caller: the agent that dialer.py dials each contact into.

Governance points:
- Nothing about the appointment is in the prompt or global_data until the
  confirm_identity handler hears "yes, this is them". A wrong person gets only a
  callback number, then the handler hangs up.
- The manage tools never take an appointment id from the model. They act on the
  id the dialer put in the SWML URL, so a caller can't touch someone else's booking.
- opt_out writes the do-not-call list (which dialer.py checks) and ends the call.
"""
from datetime import datetime

from signalwire import AgentBase, FunctionResult

import calendar_ics as cal
import config
import contacts

if config.CALENDAR_BACKEND != "ics":
    # TODO(blocked: no Google service account to build and test a Google Calendar adapter)
    raise SystemExit(f"CALENDAR_BACKEND={config.CALENDAR_BACKEND} is not built yet; use ics")


def appointment_for(raw_data: dict) -> tuple[str | None, dict | None]:
    appt_id = (raw_data or {}).get("global_data", {}).get("appointment_id")
    return appt_id, (cal.get_event(appt_id) if appt_id else None)


def configure(query_params, body_params, headers, agent):
    """Per call: only the appointment id and the contact's first name go into global_data."""
    contact = contacts.load_contacts().get(query_params.get("appt", ""))
    if contact:
        agent.set_global_data({"appointment_id": contact["appointment_id"],
                               "first_name": contact["first_name"]})


class ReminderAgent(AgentBase):
    def __init__(self, **kwargs):
        super().__init__(name="appointment-reminder", route=config.ROUTE, port=config.PORT, **kwargs)
        self.add_language("English", config.LANGUAGE_CODE, config.VOICE)
        self.prompt_add_section(
            "Role",
            f"You are calling on behalf of {config.BUSINESS_NAME} about an appointment. "
            "Be brief and polite. Never mention health details.",
        )
        self.set_dynamic_config_callback(configure)

        ctx = self.define_contexts().add_context("default")
        ctx.add_step("confirm_identity") \
            .set_text(
                f"Say you are calling from {config.BUSINESS_NAME} and ask to speak with "
                "${global_data.first_name}. Do not say why you are calling. Call confirm_identity "
                "with is_contact true only if the person says they are ${global_data.first_name}, "
                "otherwise false."
            ) \
            .set_functions(["confirm_identity"]) \
            .set_valid_steps([])
        ctx.add_step("manage") \
            .set_text(
                "Remind them of ${global_data.appointment.summary} on ${global_data.appointment.when}. "
                "Ask if they can make it. Use confirm_appointment, reschedule_appointment, "
                "cancel_appointment, or opt_out if they ask not to be called again."
            ) \
            .set_functions(["confirm_appointment", "reschedule_appointment",
                            "cancel_appointment", "opt_out"]) \
            .set_valid_steps([])
        ctx.add_step("wrap_up").set_text("Thank them and say goodbye.").set_functions([]) \
            .set_valid_steps([])  # last step: no next_step tool (recipe 12 looped on next_step("next") live)

    @AgentBase.tool(
        name="confirm_identity",
        description="Record whether the person on the phone is the contact.",
        parameters={"type": "object", "properties": {"is_contact": {
            "type": "boolean", "description": "True only if the person said they are the contact"}},
                    "required": ["is_contact"]},
    )
    def confirm_identity(self, args, raw_data):
        appt_id, event = appointment_for(raw_data)
        if args.get("is_contact") is not True or not event:
            return FunctionResult(
                f"Say: no problem, please ask them to call {config.BUSINESS_NAME} at "
                f"{config.CALLBACK_NUMBER}. Then say goodbye. Share nothing else.",
            post_process=True,  # speak that line, then hang up
        ).hangup()
        return (FunctionResult("Identity confirmed.")
                .update_global_data({"appointment": {"summary": event["summary"],
                                                     "when": cal.spoken(event["start"])}})
                .swml_change_step("manage"))

    @AgentBase.tool(name="confirm_appointment", description="The contact will attend.",
                    parameters={"type": "object", "properties": {}})
    def confirm_appointment(self, args, raw_data):
        appt_id, event = appointment_for(raw_data)
        if not event:
            return FunctionResult("I can't find that appointment.").hangup()
        cal.set_status(appt_id, "CONFIRMED")
        return FunctionResult("Confirmed. Tell them we look forward to seeing them.") \
            .swml_change_step("wrap_up")

    @AgentBase.tool(
        name="reschedule_appointment",
        description="Move the appointment to a new local date and time the contact asked for.",
        parameters={"type": "object", "properties": {
            "new_start": {"type": "string", "description": "Local time, YYYY-MM-DD HH:MM (24h)"},
        }, "required": ["new_start"]},
    )
    def reschedule_appointment(self, args, raw_data):
        appt_id, event = appointment_for(raw_data)
        if not event:
            return FunctionResult("I can't find that appointment.").hangup()
        tz = event["start"].tzinfo
        new_start = cal.parse_local(str(args.get("new_start", "")), tz)
        if not new_start or not cal.is_open_slot(new_start, datetime.now(tz)):
            lo, hi = config.OPEN_HOURS
            return FunctionResult(f"That time isn't available. We book weekdays, on the hour or "
                                  f"half hour, from {lo}:00 to {hi}:00. Ask for another time.")
        cal.reschedule(appt_id, new_start)
        return (FunctionResult(f"Moved to {cal.spoken(new_start)}. Read that back to them.")
                .update_global_data({"appointment": {"summary": event["summary"],
                                                     "when": cal.spoken(new_start)}})
                .swml_change_step("wrap_up"))

    @AgentBase.tool(name="cancel_appointment", description="Cancel the appointment.",
                    parameters={"type": "object", "properties": {}})
    def cancel_appointment(self, args, raw_data):
        appt_id, event = appointment_for(raw_data)
        if not event:
            return FunctionResult("I can't find that appointment.").hangup()
        cal.set_status(appt_id, "CANCELLED")
        return FunctionResult("Cancelled. Tell them they can call to book again.") \
            .swml_change_step("wrap_up")

    @AgentBase.tool(name="opt_out", description="The contact asks not to be called again.",
                    parameters={"type": "object", "properties": {}})
    def opt_out(self, args, raw_data):
        appt_id, _ = appointment_for(raw_data)
        contact = contacts.load_contacts().get(appt_id or "")
        if contact:
            contacts.add_dnc(contact["phone"])
        return FunctionResult("Say: you won't get these calls again. Goodbye.",
                              post_process=True).hangup()


agent = ReminderAgent()

if __name__ == "__main__":
    agent.run()
