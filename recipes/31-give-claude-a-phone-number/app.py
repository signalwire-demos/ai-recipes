"""Give Claude a phone number: one set of tools, two front doors.

Governance point: the voice agent's tools are also an MCP server at /mcp, but
code decides which ones. config.MCP_TOOLS is an allowlist: lookup_customer and
book_callback are shared, transfer_to_human (it moves a live call) stays
voice-only and can't be listed or called over MCP. The handlers enforce their
own rules (known account, business hours) because an MCP client has no steps,
and they never return the CRM's internal fields on either channel.
"""
import calendar
import json
import re
from datetime import datetime

from signalwire import AgentBase, FunctionResult

import config


def load_customers() -> dict:
    return json.loads(config.CUSTOMERS_FILE.read_text())


def normalize_phone(raw: str) -> str | None:
    digits = re.sub(r"\D", "", str(raw or ""))
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return f"+1{digits}" if len(digits) == 10 else None


def callback_window_text() -> str:
    """The booking window the handler enforces, worded for the help step from the same config."""
    days = list(config.CALLBACK_DAYS)
    names = [calendar.day_name[d] for d in days]
    contiguous = len(days) > 2 and days == list(range(days[0], days[-1] + 1))
    span = f"{names[0]} to {names[-1]}" if contiguous else ", ".join(names)
    start, end = config.CALLBACK_HOURS
    return f"Callbacks run {span}, {start}:00 to {end}:00 local time."


class PhoneAgent(AgentBase):
    def __init__(self, **kwargs):
        super().__init__(name="acme-support", route=config.ROUTE, port=config.PORT, **kwargs)
        self.customers = load_customers()
        self.enable_mcp_server()  # POST /mcp, behind the same basic auth as the SWML

        self.add_language("English", config.LANGUAGE_CODE, config.VOICE)
        self.prompt_add_section(
            "Role",
            f"You answer the support line for {config.BUSINESS_NAME}. Be brief and friendly.",
        )
        ctx = self.define_contexts().add_context("default")
        ctx.add_step("identify") \
            .set_text("Ask for the phone number on the account, then call lookup_customer.") \
            .set_functions(["lookup_customer"]) \
            .set_valid_steps([])  # only the lookup handler can move the call on
        ctx.add_step("help") \
            .set_text(
                callback_window_text()
                + " The caller is ${global_data.name}, account ${global_data.account_id}. "
                "Offer to book a callback. If they want one, ask for the day and then the time, "
                "one at a time; never assume today or pick a slot yourself. Then call "
                "book_callback. If they insist on a person now, call transfer_to_human."
            ) \
            .set_functions(["book_callback", "transfer_to_human"]) \
            .set_valid_steps([])

    # The one seam: the SDK's MCP endpoint lists and calls whatever this returns.
    def _mcp_tools(self):
        return {n: f for n, f in super()._mcp_tools().items() if n in config.MCP_TOOLS}

    @AgentBase.tool(
        name="lookup_customer",
        description="Find a customer account by the phone number on the account.",
        parameters={
            "type": "object",
            "properties": {
                "phone": {"type": "string", "pattern": r"^(\+?1)?\d{10}$",
                          "description": "The phone number on the caller's account, 10 US digits with "
                                         "no punctuation, e.g. 5555550101. Ask the caller for it; never "
                                         "use the caller ID."},
            },
            "required": ["phone"],
        },
    )
    def lookup_customer(self, args, raw_data):
        phone = normalize_phone(args.get("phone"))
        record = self.customers.get(phone) if phone else None
        if not record:
            return FunctionResult("No account matches that number. Ask for the number again.")
        public = {k: record[k] for k in ("account_id", "name", "plan")}  # never record["internal"]
        ticket = record.get("open_ticket")
        text = (f"Account {public['account_id']}: {public['name']}, plan {public['plan']}. "
                + (f"Open ticket: {ticket}." if ticket else "No open tickets."))
        return FunctionResult(text).update_global_data(public).swml_change_step("help")

    @AgentBase.tool(
        name="book_callback",
        description="Book a support callback for an account at a given local date and time.",
        parameters={
            "type": "object",
            "properties": {
                "account_id": {"type": "string",
                               "description": "The account_id returned by lookup_customer "
                                              "(global_data.account_id), e.g. ACME-1001. Never ask the "
                                              "caller for it or invent one."},
                "when": {"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$",
                         "description": "Callback date and time, local, 24-hour clock, exactly "
                                        "YYYY-MM-DD HH:MM (e.g. 2026-11-10 14:30). Ask the caller for "
                                        "the day and the time; never assume today or pick a slot yourself."},
                "reason": {"type": "string",
                           "description": "Short reason for the callback, in the caller's own words. "
                                          "Ask if not provided."},
            },
            "required": ["account_id", "when"],
        },
    )
    def book_callback(self, args, raw_data):
        account_id = str(args.get("account_id", "")).strip().upper()
        record = next((c for c in self.customers.values() if c["account_id"] == account_id), None)
        if not record:
            return FunctionResult(f"There is no account {account_id or '(blank)'}. Look the customer up first.")
        try:
            when = datetime.strptime(str(args.get("when", "")).strip(), "%Y-%m-%d %H:%M")
        except ValueError:
            return FunctionResult("I need the time as YYYY-MM-DD HH:MM. Ask for the date and time again.")
        start, end = config.CALLBACK_HOURS
        if when <= datetime.now() or when.weekday() not in config.CALLBACK_DAYS or not start <= when.hour < end:
            return FunctionResult(
                f"Callbacks run weekdays from {start}:00 to {end}:00 and must be in the future. Offer another time."
            )
        booking = {"account_id": account_id, "when": when.strftime("%Y-%m-%d %H:%M"),
                   "reason": str(args.get("reason", "")).strip()[:200]}
        config.CALLBACKS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with config.CALLBACKS_FILE.open("a") as fh:
            fh.write(json.dumps(booking) + "\n")
        spoken = when.strftime("%A %B %d at %I:%M %p").replace(" 0", " ")
        return FunctionResult(f"Booked a callback for {record['name']} on {spoken}.") \
            .update_global_data({"callback": booking})

    @AgentBase.tool(
        name="transfer_to_human",
        description="Transfer the live call to a support person.",
        parameters={"type": "object", "properties": {}},
    )
    def transfer_to_human(self, args, raw_data):
        return FunctionResult("Connecting you to a support specialist now.") \
            .connect(config.HUMAN_NUMBER, final=True)


agent = PhoneAgent()

if __name__ == "__main__":
    agent.run()
