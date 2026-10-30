"""AI Collections Agent: authority inversion.

Governance point: a business outcome overrides whatever the model or the caller
wants next. propose_plan is judged by policy.py, whose thresholds never reach the
model. On the Nth refusal the handler jumps the call to `hardship_options` with
swml_change_step, whatever arguments the model sent. Abuse or a request for a
person jumps to `escalate`.
"""
from signalwire import AgentBase, FunctionResult

import config
import ledger
import policy

# What the model hears when a plan is refused: a direction, never the number.
REFUSAL_HINTS = {
    policy.TOO_LOW: "We can't accept that monthly amount. Ask if the caller could manage more each month.",
    policy.TOO_LONG: "That plan runs longer than we can offer. Ask about a shorter plan.",
    policy.SHORT: "That plan wouldn't pay off the balance. Ask about a higher amount or more months.",
    policy.INVALID: "That isn't a plan we can set up. Ask for a monthly amount and a number of months.",
}


def gd(raw_data) -> dict:
    return raw_data.get("global_data") or {}


def to_hardship(refusals: int) -> FunctionResult:
    return (
        FunctionResult("Stop negotiating. Tell the caller you understand money is tight and "
                       "that there are other options.")
        .update_global_data({"refusals": refusals})
        .swml_change_step("hardship_options")
    )


class CollectionsAgent(AgentBase):
    def __init__(self, **kwargs):
        super().__init__(name="collections-agent", route=config.ROUTE, port=config.PORT, **kwargs)
        self.add_language("English", config.LANGUAGE_CODE, config.VOICE)
        self.prompt_add_section(
            "Role",
            f"You are a respectful account specialist at {config.COMPANY_NAME}. Never threaten, "
            "shame or argue. You don't know which plans are acceptable: the tools decide.",
        )
        offers = "; ".join(f"{k}: {v}" for k, v in config.HARDSHIP_OFFERS.items())

        ctx = self.define_contexts().add_context("default")
        ctx.add_step("identify") \
            .set_text("Ask for the reference number on the caller's letter and their ZIP code, "
                      "then call find_account. Discuss nothing about the account before that.") \
            .set_functions(["find_account"]) \
            .set_valid_steps([])
        ctx.add_step("negotiate") \
            .set_text(
                "You are speaking with ${global_data.account.name} about a balance of "
                "${global_data.account.balance_text} owed to ${global_data.account.creditor}. Ask what "
                "they can pay each month and for how many months, then call propose_plan. If they "
                "won't commit to any plan, call decline_plan. If they are abusive or ask for a "
                "person, call escalate."
            ) \
            .set_functions(["propose_plan", "decline_plan", "escalate"]) \
            .set_valid_steps([])  # only handlers leave this step
        ctx.add_step("hardship_options") \
            .set_text(f"Offer these options and ask which one fits: {offers}. Call "
                      "choose_hardship_option with the caller's pick. If they want a person, call escalate.") \
            .set_functions(["choose_hardship_option", "escalate"]) \
            .set_valid_steps([])
        ctx.add_step("wrap_up") \
            .set_text("Confirm what was agreed: ${global_data.outcome}. Thank the caller and say goodbye.") \
            .set_functions([]) \
            .set_valid_steps([])
        ctx.add_step("escalate") \
            .set_text("Tell the caller you are handing them to a member of the team, then call transfer_to_agent.") \
            .set_functions(["transfer_to_agent"]) \
            .set_valid_steps([])

    @AgentBase.tool(
        name="find_account",
        description="Look up the caller's account by reference number and ZIP code.",
        parameters={"type": "object", "properties": {
            "reference": {"type": "string", "description": "Reference number from the letter"},
            "postal_code": {"type": "string", "description": "Five-digit ZIP code"},
        }, "required": ["reference", "postal_code"]},
    )
    def find_account(self, args, raw_data):
        debt = ledger.find(str(args.get("reference", "")), str(args.get("postal_code", "")).strip())
        if not debt:
            return FunctionResult("No account matches. Ask the caller to read the reference number again.")
        account = {"id": debt["id"], "name": debt["name"], "creditor": debt["creditor"],
                   "balance": debt["balance"], "balance_text": f"${debt['balance']:,.2f}"}
        return (
            FunctionResult(f"Found the account. Greet {debt['name'].split()[0]} and explain the balance.")
            .update_global_data({"account": account, "refusals": 0})
            .swml_change_step("negotiate")
        )

    @AgentBase.tool(
        name="propose_plan",
        description="Submit the payment plan the caller is offering.",
        parameters={"type": "object", "properties": {
            "monthly_amount": {"type": "number", "description": "Dollars per month the caller offers"},
            "months": {"type": "integer", "description": "Number of monthly payments"},
        }, "required": ["monthly_amount", "months"]},
    )
    def propose_plan(self, args, raw_data):
        refusals = int(gd(raw_data).get("refusals", 0))
        if policy.refusals_exhausted(refusals):      # already over the line: arguments don't matter
            return to_hardship(refusals)
        verdict = policy.evaluate(float(gd(raw_data)["account"]["balance"]), args.get("monthly_amount"), args.get("months"))
        if verdict == policy.ACCEPT:
            monthly, months = float(args["monthly_amount"]), int(args["months"])
            summary = f"{months} monthly payments of ${monthly:,.2f}, the first one due in 30 days"
            ledger.record(gd(raw_data)["account"]["id"], "plan", monthly_amount=monthly, months=months)
            return (FunctionResult("The plan is approved.")
                    .update_global_data({"outcome": summary})
                    .swml_change_step("wrap_up"))
        return self._refuse(refusals, REFUSAL_HINTS[verdict])

    @AgentBase.tool(
        name="decline_plan",
        description="The caller won't commit to any payment plan right now.",
        parameters={"type": "object", "properties": {
            "reason": {"type": "string", "description": "What the caller said, briefly"},
        }},
    )
    def decline_plan(self, args, raw_data):
        return self._refuse(int(gd(raw_data).get("refusals", 0)),
                            "Acknowledge that. Ask if a smaller amount over a longer time could work.")

    def _refuse(self, refusals: int, hint: str) -> FunctionResult:
        refusals += 1
        if policy.refusals_exhausted(refusals):
            return to_hardship(refusals)
        return FunctionResult(hint).update_global_data({"refusals": refusals})

    @AgentBase.tool(
        name="choose_hardship_option",
        description="Record the hardship option the caller picked.",
        parameters={"type": "object", "properties": {
            "option": {"type": "string", "enum": list(config.HARDSHIP_OFFERS), "description": "Option key"},
        }, "required": ["option"]},
    )
    def choose_hardship_option(self, args, raw_data):
        option = args.get("option")
        if option not in config.HARDSHIP_OFFERS:
            return FunctionResult("That isn't one of the options. Offer them again.")
        ledger.record(gd(raw_data)["account"]["id"], "hardship", option=option)
        return (FunctionResult("Recorded.")
                .update_global_data({"outcome": config.HARDSHIP_OFFERS[option]})
                .swml_change_step("wrap_up"))

    @AgentBase.tool(
        name="escalate",
        description="Hand the call to a person: the caller asked for one, or is being abusive.",
        parameters={"type": "object", "properties": {
            "reason": {"type": "string", "enum": ["requested_person", "abuse"]},
        }, "required": ["reason"]},
    )
    def escalate(self, args, raw_data):
        account_id = (gd(raw_data).get("account") or {}).get("id", "unknown")
        ledger.record(account_id, "escalated", reason=str(args.get("reason", "requested_person")))
        return FunctionResult("Escalating.").swml_change_step("escalate")

    @AgentBase.tool(
        name="transfer_to_agent",
        description="Connect the caller to a human agent, or end the call politely.",
        parameters={"type": "object", "properties": {}},
    )
    def transfer_to_agent(self, args, raw_data):
        if config.AGENT_NUMBER:
            return FunctionResult("Connecting you now.").connect(
                config.AGENT_NUMBER, final=True, from_addr=config.FROM_NUMBER)
        return (FunctionResult("No agent line is configured.")
                .say("A member of our team will call you back. Goodbye.")
                .hangup())


agent = CollectionsAgent()

if __name__ == "__main__":
    agent.run()
