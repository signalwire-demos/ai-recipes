"""Lead qualification line: BANT-style questions, scored after the call.

Governance point: the CRM record is built only from typed values that tool
handlers wrote into global_data. on_summary never reads the transcript or the
model's summary, so the model can't talk a lead into a better score.
"""
from signalwire import AgentBase, FunctionResult

import config
import disposition


def record(raw_data: dict, key: str, value, spoken: str) -> FunctionResult:
    """Write one field. When all fields are in, the handler (not the model) ends qualifying."""
    known = {**(raw_data or {}).get("global_data", {}), key: value}
    result = FunctionResult(f"Recorded: {spoken}.").update_global_data({key: value})
    if all(k in known for k in config.FIELDS):
        result.swml_change_step("wrap_up")
    return result


class LeadQualificationAgent(AgentBase):
    def __init__(self, **kwargs):
        super().__init__(name="lead-qualification", route=config.ROUTE, port=config.PORT, **kwargs)
        self.add_language("English", config.LANGUAGE_CODE, config.VOICE)
        self.prompt_add_section(
            "Role",
            f"You answer the sales line for {config.BUSINESS_NAME}. Be warm and brief. "
            "Ask one question at a time. Never promise pricing or discounts.",
        )

        ctx = self.define_contexts().add_context("default")
        ctx.add_step("qualify") \
            .set_text(
                "Learn four things, in any order, and record each with its tool as soon as you "
                "hear it: budget (record_budget), timeline (record_timeline), whether the caller "
                "signs off on the purchase (record_authority), and what they need (record_need)."
            ) \
            .set_functions(["record_budget", "record_timeline", "record_authority", "record_need"]) \
            .set_valid_steps([])  # only the last record_* handler moves the call
        ctx.add_step("wrap_up") \
            .set_text("Thank the caller, say a specialist will follow up soon, and say goodbye.") \
            .set_functions([])

        # The platform POSTs the post-prompt payload to on_summary when the call ends.
        self.set_post_prompt("Summarize the call in one sentence.")

    @AgentBase.tool(
        name="record_budget",
        description="Record the caller's budget for this purchase, in US dollars.",
        parameters={"type": "object", "properties": {
            "amount_usd": {"type": "integer", "description": "Whole dollars. 0 if no budget yet."},
        }, "required": ["amount_usd"]},
    )
    def record_budget(self, args, raw_data):
        try:
            amount = int(args.get("amount_usd"))
        except (TypeError, ValueError):
            return FunctionResult("I need the budget as a dollar amount. Ask again.")
        if amount < 0:
            return FunctionResult("A budget can't be negative. Ask again.")
        return record(raw_data, "budget_usd", amount, f"budget {amount} dollars")

    @AgentBase.tool(
        name="record_timeline",
        description="Record how many months until the caller wants to buy.",
        parameters={"type": "object", "properties": {
            "months": {"type": "integer",
                       "description": f"0 = this month. {config.MAX_TIMELINE_MONTHS} if just researching."},
        }, "required": ["months"]},
    )
    def record_timeline(self, args, raw_data):
        try:
            months = int(args.get("months"))
        except (TypeError, ValueError):
            return FunctionResult("I need the timeline as a number of months. Ask again.")
        months = max(0, min(months, config.MAX_TIMELINE_MONTHS))
        return record(raw_data, "timeline_months", months, f"timeline {months} months")

    @AgentBase.tool(
        name="record_authority",
        description="Record whether the caller makes or signs off on the buying decision.",
        parameters={"type": "object", "properties": {
            "is_decision_maker": {"type": "boolean"},
        }, "required": ["is_decision_maker"]},
    )
    def record_authority(self, args, raw_data):
        value = args.get("is_decision_maker")
        if not isinstance(value, bool):
            return FunctionResult("I need a yes or no on who signs off. Ask again.")
        return record(raw_data, "is_decision_maker", value,
                      "decision maker" if value else "not the decision maker")

    @AgentBase.tool(
        name="record_need",
        description="Record the main thing the caller needs.",
        parameters={"type": "object", "properties": {
            "need": {"type": "string", "enum": config.NEEDS},
        }, "required": ["need"]},
    )
    def record_need(self, args, raw_data):
        need = str(args.get("need", "")).strip().lower()
        if need not in config.NEEDS:
            return FunctionResult(f"Pick the closest of: {', '.join(config.NEEDS)}.")
        return record(raw_data, "need", need, f"need {need.replace('_', ' ')}")

    def on_summary(self, summary, raw_data=None):
        """Build the disposition from global_data only. `summary` is deliberately unused."""
        raw_data = raw_data or {}
        disposition.send(disposition.build_disposition(
            raw_data.get("global_data") or {}, call_id=raw_data.get("call_id")))


agent = LeadQualificationAgent()

if __name__ == "__main__":
    agent.run()
