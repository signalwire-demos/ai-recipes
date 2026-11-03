"""Answering service: an AI agent that is only on the line after hours.

Governance point: code decides whether the AI exists on a call at all. A dynamic config
callback checks the office clock on every call. During business hours it renders SWML that
connects straight to the office line, with no AI verb. After hours the AI collects the
caller's details with one tool, and the submit_call handler applies the urgency rule: urgent
calls are connected to on-call, everything else is texted to the owner. The model never
chooses between the two, and it has no connect or SMS tool.
"""
import json
import re
import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from signalwire import AgentBase, FunctionResult

import config

DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
_last_sms: dict[str, float] = {}    # caller ID -> monotonic time of the last owner text
_sms_lock = threading.Lock()


def parse_hours(spec: str) -> dict:
    """'mon-fri 09:00-17:00; sat 10:00-14:00' -> {0: ('09:00', '17:00'), ..., 5: (...)}"""
    hours = {}
    for part in filter(None, (p.strip() for p in spec.lower().split(";"))):
        days, span = part.split()
        first, _, last = days.partition("-")
        opens, closes = span.split("-")
        for d in range(DAYS.index(first), DAYS.index(last or first) + 1):
            hours[d] = (opens, closes)
    return hours


def is_open(now: datetime, hours: dict, holidays: list) -> bool:
    if now.date().isoformat() in holidays or now.weekday() not in hours:
        return False
    opens, closes = hours[now.weekday()]
    return opens <= now.strftime("%H:%M") < closes


def is_urgent(text: str) -> bool:
    """The urgency rule. Whole-word match on config.URGENT_KEYWORDS."""
    text = text.lower()
    return any(re.search(rf"\b{re.escape(k)}\b", text) for k in config.URGENT_KEYWORDS)


def phone_number(text: str) -> str | None:
    """Spoken or typed callback number -> E.164, or None. NANP: 10 digits, or 11 starting with 1."""
    digits = re.sub(r"[\s().-]", "", str(text))
    if re.fullmatch(r"\+?1?[2-9]\d{2}[2-9]\d{6}", digits):
        return "+1" + digits[-10:]
    return digits if re.fullmatch(r"\+[2-9]\d{7,14}", digits) else None


def sms_allowed(caller_id: str, now: float | None = None) -> bool:
    """One owner text per caller ID per SMS_THROTTLE_MINUTES (anonymous callers share one slot)."""
    now = time.monotonic() if now is None else now
    with _sms_lock:
        last = _last_sms.get(caller_id)
        if last is not None and now - last < config.SMS_THROTTLE_MINUTES * 60:
            return False
        _last_sms[caller_id] = now
        return True


def office_swml() -> dict:
    """Business hours: ring the office. No AI verb in the document."""
    return {"version": "1.0.0", "sections": {"main": [
        {"connect": {"to": config.OFFICE_NUMBER, "from": config.FROM_NUMBER,
                     "timeout": config.CONNECT_TIMEOUT}},
        {"hangup": {}},
    ]}}


class AnsweringService(AgentBase):
    def __init__(self, clock=None, **kwargs):
        super().__init__(name="answering-service", route=config.ROUTE, port=config.PORT, **kwargs)
        self.clock = clock or (lambda: datetime.now(ZoneInfo(config.TZ)))
        self.hours = parse_hours(config.HOURS)
        self.holidays = json.loads(config.HOLIDAYS_FILE.read_text())
        self.swml_override = None

        self.add_language("English", config.LANGUAGE_CODE, config.VOICE)
        self.prompt_add_section(
            "Role",
            f"You answer the phone for {config.BUSINESS_NAME} after hours. The office is closed. "
            "Be calm and brief. You can't book work, give prices or promise a callback time.",
        )
        ctx = self.define_contexts().add_context("default")
        ctx.add_step("intake") \
            .set_text("Say the office is closed. Ask for, one at a time: the caller's name, a callback "
                      "number, and what the call is about. Put the caller's own words in `message`. "
                      "Never fill in a value the caller did not give. Then call submit_call.") \
            .set_functions(["submit_call"]) \
            .set_valid_steps([])
        ctx.add_step("wrap_up") \
            .set_text(f"Tell the caller their message was sent to {config.OWNER_NAME}, who will call "
                      "them back during business hours. Say goodbye.") \
            .set_functions([])

        self.set_dynamic_config_callback(self.per_call)

    # --- per call: decide whether the AI is on this call at all ---------------------
    def per_call(self, query_params, body_params, headers, agent):
        now = self.clock()
        if is_open(now, self.hours, self.holidays):
            agent.swml_override = office_swml()
        else:
            agent.set_global_data({"closed_at": now.isoformat(timespec="minutes")})

    def render_document(self) -> str:
        if self.swml_override is not None:
            return json.dumps(self.swml_override)
        return super().render_document()

    # --- after hours: one tool; the handler routes ------------------------------------
    @AgentBase.tool(
        name="submit_call",
        description="Submit the caller's details once you have their name, number and reason.",
        parameters={"type": "object", "required": ["name", "callback_number", "message"], "properties": {
            "name": {"type": "string", "description": "The caller's name, as they said it. Ask if not provided."},
            "callback_number": {"type": "string", "pattern": "^\\+?[0-9]{7,15}$",
                                "description": "Phone number to call the caller back, digits only, e.g. "
                                               "5551234567. Ask the caller for it; never assume it is the "
                                               "number they called from."},
            "message": {"type": "string",
                        "description": "What the call is about, verbatim in the caller's own words; do not "
                                       "summarize or reword, the urgency check matches their words. Ask if "
                                       "not provided."},
        }},
    )
    def submit_call(self, args, raw_data):
        missing = [k for k in ("name", "callback_number", "message") if not str(args.get(k) or "").strip()]
        if missing:
            return FunctionResult(f"Still need: {', '.join(missing)}. Ask for it.")
        if is_urgent(args["message"]):
            return self.forward_urgent(args)
        return self.take_message(args, raw_data)

    def forward_urgent(self, args):
        return FunctionResult("This sounds urgent. Tell the caller you're connecting them to the "
                              "on-call technician now.") \
            .connect(config.ONCALL_NUMBER, final=True, from_addr=config.FROM_NUMBER)

    def take_message(self, args, raw_data):
        number = phone_number(args["callback_number"])   # an emergency is never held up by this
        if not number:
            return FunctionResult("That callback_number isn't a full phone number. Ask for it again, "
                                  "area code first.")
        caller_id = raw_data.get("caller_id_num") or "unknown"
        if not sms_allowed(caller_id):
            return FunctionResult(f"A message from this number already reached {config.OWNER_NAME} a few "
                                  "minutes ago, so no new text was sent.").swml_change_step("wrap_up")
        body = (f"After-hours message for {config.BUSINESS_NAME}: {args['name']}, call back "
                f"{number} (caller ID {caller_id}). \"{args['message']}\"")
        return FunctionResult("Message sent.") \
            .send_sms(to_number=config.OWNER_NUMBER, from_number=config.SMS_FROM, body=body) \
            .swml_change_step("wrap_up")


agent = AnsweringService()

if __name__ == "__main__":
    agent.run()
