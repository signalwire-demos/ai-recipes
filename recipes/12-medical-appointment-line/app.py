"""Medical appointment line: compliance as a state machine.

Governance point: the recording disclosure lives in the `consent` step's text, and that
step's only tool is record_consent. Nothing else is reachable until the handler moves the
call. Recording starts only inside that handler, and only on a yes. A "no" goes to an
unrecorded path that can place a tentative hold but cannot book. on_summary writes an
audit record (consent, time, disclosure version) built from handler-written global_data,
never from the transcript.
"""
import json
from datetime import datetime, timezone

from signalwire import AgentBase, FunctionResult

import config

SLOT_ID = {"type": "string", "description": "Slot id from find_slots, e.g. S-0101"}


def load_slots() -> list[dict]:
    return json.loads(config.SLOTS_FILE.read_text())


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class MedicalAppointmentAgent(AgentBase):
    def __init__(self, **kwargs):
        super().__init__(name="medical-appointments", route=config.ROUTE, port=config.PORT, **kwargs)
        self.slots = {s["id"]: s for s in load_slots()}
        self.taken: set[str] = set()

        self.add_language("English", config.LANGUAGE_CODE, config.VOICE)
        self.prompt_add_section(
            "Role",
            f"You book appointments for {config.CLINIC_NAME}. Be brief and warm.",
            bullets=[
                "Never ask for symptoms, diagnoses, medications, insurance or date of birth.",
                "If the caller offers medical details, say this line only handles booking.",
            ],
        )
        self.set_post_prompt('Return only JSON: {"outcome": "booked|held|none"}')

        ctx = self.define_contexts().add_context("default")
        ctx.add_step("consent") \
            .set_text(
                f'Greet the caller, then read this disclosure word for word: "{config.DISCLOSURE_TEXT}" '
                "When they answer, call record_consent with granted true or false. "
                "Do not help with anything else until you have called it."
            ) \
            .set_functions(["record_consent"]) \
            .set_valid_steps([])  # the only way out is the record_consent handler
        ctx.add_step("schedule") \
            .set_text(
                "This call is recorded with consent. Ask which day suits the caller, call "
                "find_slots, offer the options, and call book_slot for the one they choose."
            ) \
            .set_functions(["find_slots", "book_slot"]) \
            .set_valid_steps([])
        ctx.add_step("schedule_limited") \
            .set_text(
                "The caller declined recording, so this call is not recorded and you cannot "
                "confirm a booking. Call find_slots, and call hold_slot for the one they want. "
                "Explain that the front desk will call back to confirm the hold."
            ) \
            .set_functions(["find_slots", "hold_slot"]) \
            .set_valid_steps([])
        ctx.add_step("wrap_up") \
            .set_text("Read back ${global_data.booking.summary}. Ask if there is anything else, then say goodbye.") \
            .set_functions([])

    # --- consent gate -----------------------------------------------------

    @AgentBase.tool(
        name="record_consent",
        description="Record the caller's answer to the recording disclosure.",
        parameters={
            "type": "object",
            "properties": {"granted": {"type": "boolean", "description": "True if the caller agreed"}},
            "required": ["granted"],
        },
    )
    def record_consent(self, args, raw_data):
        granted = args.get("granted")
        if not isinstance(granted, bool):  # anything ambiguous is not consent, and not a refusal yet
            return FunctionResult("I didn't catch a clear yes or no. Ask the caller again.")
        consent = {"granted": granted, "time": now_iso(), "disclosure_version": config.DISCLOSURE_VERSION}
        if not granted:
            return (
                FunctionResult("Understood, this call will not be recorded.")
                .update_global_data({"consent": consent, "recorded": False})
                .swml_change_step("schedule_limited")
            )
        return (
            FunctionResult("Thank you. Recording has started.")
            .record_call(control_id="consented", stereo=True, format=config.RECORDING_FORMAT)
            .update_global_data({"consent": consent, "recorded": True})
            .swml_change_step("schedule")
        )

    # --- scheduling -------------------------------------------------------

    @AgentBase.tool(
        name="find_slots",
        description="List open appointment slots, optionally for one day of the week.",
        parameters={
            "type": "object",
            "properties": {"day": {"type": "string", "description": "Day of the week, e.g. Tuesday"}},
        },
    )
    def find_slots(self, args, raw_data):
        day = str(args.get("day") or "").strip().lower()
        open_slots = [
            s for s in self.slots.values()
            if s["id"] not in self.taken and (not day or s["day"].lower() == day)
        ]
        if not open_slots:
            return FunctionResult("No open slots for that day. Offer to check another day.")
        lines = "; ".join(f"{s['id']}: {s['day']} {s['time']} with {s['provider']}" for s in open_slots)
        return FunctionResult(f"Open slots: {lines}.")

    def _claim(self, args, status: str):
        slot = self.slots.get(str(args.get("slot_id", "")).strip().upper())
        if not slot or slot["id"] in self.taken:
            return None, FunctionResult("That slot isn't available. Call find_slots again.")
        self.taken.add(slot["id"])
        summary = f"{status} {slot['day']} at {slot['time']} with {slot['provider']}, reference {slot['id']}"
        return slot, summary

    @AgentBase.tool(name="book_slot", description="Book an open slot.",
                    parameters={"type": "object", "properties": {"slot_id": SLOT_ID}, "required": ["slot_id"]})
    def book_slot(self, args, raw_data):
        consent = (raw_data or {}).get("global_data", {}).get("consent", {})
        if consent.get("granted") is not True:  # belt and braces: the step scoping already hides this tool
            return FunctionResult("Booking needs a recorded call. Offer a hold instead.")
        slot, summary = self._claim(args, "Booked")
        if slot is None:
            return summary
        return (
            FunctionResult(f"{summary}.")
            .update_global_data({"booking": {"slot_id": slot["id"], "status": "booked", "summary": summary}})
            .swml_change_step("wrap_up")
        )

    @AgentBase.tool(name="hold_slot", description="Place a tentative hold on an open slot for the front desk to confirm.",
                    parameters={"type": "object", "properties": {"slot_id": SLOT_ID}, "required": ["slot_id"]})
    def hold_slot(self, args, raw_data):
        slot, summary = self._claim(args, "Held, pending a call back,")
        if slot is None:
            return summary
        return (
            FunctionResult(f"{summary}.")
            .update_global_data({"booking": {"slot_id": slot["id"], "status": "held", "summary": summary}})
            .swml_change_step("wrap_up")
        )

    # --- audit ------------------------------------------------------------

    def on_summary(self, summary, raw_data=None):
        """Write one audit line per call from handler-written global_data, not the transcript."""
        raw_data = raw_data or {}
        gd = raw_data.get("global_data") or {}
        consent = gd.get("consent") or {}
        record = {
            "logged_at": now_iso(),
            "call_id": raw_data.get("call_id"),
            "disclosure_version": consent.get("disclosure_version", config.DISCLOSURE_VERSION),
            "consent_granted": consent.get("granted"),  # None = caller never answered
            "consent_time": consent.get("time"),
            "recorded": gd.get("recorded", False),
            "booking": {k: v for k, v in (gd.get("booking") or {}).items() if k != "summary"},
        }
        config.AUDIT_FILE.parent.mkdir(parents=True, exist_ok=True)
        with config.AUDIT_FILE.open("a") as f:
            f.write(json.dumps(record) + "\n")
        return record


agent = MedicalAppointmentAgent()

if __name__ == "__main__":
    agent.run()
