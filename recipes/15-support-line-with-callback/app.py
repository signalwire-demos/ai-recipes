"""AI Support Line With Callback: triage, then a human now or a human on the return call.

Governance point: context survives the queue and the return call without the model carrying
it. request_human (the only tool in `triage`) checks the rota in code and either transfers or
moves the call to `offer_callback`. schedule_callback writes the record from the caller's
real number and the triage the handler stored. When the worker dials the customer back into
/callback?id=..., a dynamic config callback loads that record into global_data before the
model says a word, and connect_human is the only tool on the return call.
"""
from signalwire import AgentBase, AgentServer, FunctionResult

import config
import rota
import store

NO_ARGS = {"type": "object", "properties": {}}


class SupportAgent(AgentBase):
    """Inbound line: triage, then transfer or offer a callback."""

    def __init__(self, **kwargs):
        super().__init__(name="support", route=config.ROUTE, **kwargs)
        self.add_language("English", config.LANGUAGE_CODE, config.VOICE)
        self.prompt_add_section(
            "Role", f"You answer the {config.COMPANY_NAME} support line. Be brief and friendly. "
                    "You do not fix problems yourself; you get the caller to a specialist.")
        ctx = self.define_contexts().add_context("default")
        ctx.add_step("triage") \
            .set_text("Find out what the problem is. Once you understand it, call request_human "
                      "with a one-line issue and a two-sentence summary.") \
            .set_functions(["request_human"]) \
            .set_valid_steps([])  # only the handler leaves triage
        ctx.add_step("offer_callback") \
            .set_text("Every specialist is busy. Offer a callback to the number they are calling "
                      "from about: ${global_data.ticket.issue}. If they accept, ask when suits "
                      "them and call schedule_callback. If they decline, say goodbye.") \
            .set_functions(["schedule_callback"]) \
            .set_valid_steps([])

    @AgentBase.tool(
        name="request_human",
        description="Hand the caller to a human specialist with the triaged issue.",
        parameters={
            "type": "object",
            "properties": {
                "issue": {"type": "string", "description": "One line, e.g. 'router drops wifi nightly'"},
                "summary": {"type": "string", "description": "Two sentences of context for the human"},
            },
            "required": ["issue", "summary"],
        },
    )
    def request_human(self, args, raw_data):
        issue, summary = str(args.get("issue", "")).strip(), str(args.get("summary", "")).strip()
        if not issue:
            return FunctionResult("Ask the caller what the problem is first.")
        result = FunctionResult().update_global_data({"ticket": {"issue": issue, "summary": summary}})
        if rota.human_available() and config.HUMAN_NUMBER:
            return result.set_response("A specialist is free. Tell the caller you're connecting them.") \
                .connect(config.HUMAN_NUMBER, final=True, from_addr=config.FROM_NUMBER or None)
        return result.set_response("Nobody is free right now.").swml_change_step("offer_callback")

    @AgentBase.tool(
        name="schedule_callback",
        description="Book a callback for this caller at the time they prefer.",
        parameters={
            "type": "object",
            "properties": {
                "preferred_time": {"type": "string", "description": "e.g. 'today after 4pm'"},
            },
            "required": ["preferred_time"],
        },
    )
    def schedule_callback(self, args, raw_data):
        preferred = str(args.get("preferred_time", "")).strip()
        ticket = (raw_data.get("global_data") or {}).get("ticket") or {}
        number = raw_data.get("caller_id_num", "")
        if not preferred:
            return FunctionResult("Ask the caller when a callback would suit them.")
        if not number or not ticket.get("issue"):
            return FunctionResult("I can't book a callback on this call. Apologize and say goodbye.")
        rec = store.create(number, ticket["issue"], ticket.get("summary", ""), preferred)
        return FunctionResult(
            f"Callback {rec['id']} booked for {preferred}. Confirm the time, tell them a specialist "
            "will call this number back, and say goodbye.", post_process=True,
        ).hangup()


class CallbackAgent(AgentBase):
    """The return call. The worker dials the customer into /callback?id=CB-0001."""

    def __init__(self, **kwargs):
        super().__init__(name="callback", route=config.CALLBACK_ROUTE, **kwargs)
        self.add_language("English", config.LANGUAGE_CODE, config.VOICE)
        self.prompt_add_section(
            "Role", f"You are {config.COMPANY_NAME} support, returning a call the customer asked for.")
        ctx = self.define_contexts().add_context("default")
        ctx.add_step("returning") \
            .set_text("Say you are returning their call about: ${global_data.issue}. Confirm they "
                      "still need help, then call connect_human. If they no longer need help, "
                      "thank them and say goodbye.") \
            .set_functions(["connect_human"]) \
            .set_valid_steps([])
        self.set_dynamic_config_callback(self.load_context)

    @staticmethod
    def load_context(query_params, body_params, headers, agent):
        """Per request: the saved record becomes global_data. The model never sees the store."""
        rec = store.get(query_params.get("id", ""))
        if rec is None:
            agent.set_global_data({"callback_id": None, "issue": "an earlier support request"})
            return
        agent.set_global_data({"callback_id": rec["id"], "issue": rec["issue"],
                               "summary": rec["summary"], "preferred_time": rec["preferred_time"]})

    @AgentBase.tool(name="connect_human", description="Connect the customer to a specialist.",
                    parameters=NO_ARGS)
    def connect_human(self, args, raw_data):
        record_id = (raw_data.get("global_data") or {}).get("callback_id")
        if not config.HUMAN_NUMBER:
            return FunctionResult("No specialist line is set up. Apologize and say goodbye.")
        if store.get(record_id):
            store.update(record_id, status="connected", connected_at=store.now())
        return FunctionResult("Connecting you to a specialist now.") \
            .connect(config.HUMAN_NUMBER, final=True, from_addr=config.FROM_NUMBER or None)


support = SupportAgent()
callback = CallbackAgent()

if __name__ == "__main__":
    server = AgentServer(port=config.PORT)
    server.register(support, config.ROUTE)
    server.register(callback, config.CALLBACK_ROUTE)
    server.run()
