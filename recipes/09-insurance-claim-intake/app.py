"""AI Insurance Claim Intake: first notice of loss, then a screened handoff to an adjuster.

Governance point: the adjuster is briefed before the bridge completes, and the model never
drives the handoff. Gather collects the claim with tools locked. submit_claim (the only
tool in `submit`) writes the claim record, holds the caller and rpc_dials the adjuster with
a dest_swml that speaks a briefing built from the record and waits for a keypress. The hold
decides where the caller lands: `connected` if the adjuster pressed 1 (their SWML releases
the hold), `callback` if the hold timed out. Each of those steps has exactly one tool.
"""
from fastapi import Request
from fastapi.responses import JSONResponse

from signalwire import AgentBase, FunctionResult

import claims
import config


class ClaimIntakeAgent(AgentBase):
    def __init__(self, **kwargs):
        super().__init__(name="claim-intake", route=config.ROUTE, port=config.PORT, **kwargs)
        self.add_language("English", config.LANGUAGE_CODE, config.VOICE)
        self.prompt_add_section(
            "Role",
            f"You take first notice of loss calls for {config.COMPANY_NAME} insurance. "
            "Be calm, brief and kind. Never promise coverage or a payout.",
        )

        ctx = self.define_contexts().add_context("default")
        ctx.add_step("intake") \
            .set_text("Collect the claim details by asking the questions one at a time.") \
            .set_functions([]) \
            .set_valid_steps([]) \
            .set_gather_info(output_key="fnol", completion_action="submit",
                             prompt="I'm sorry that happened. I'll take a few details.") \
            .add_gather_question(key="policy_number", question="What is your policy number?",
                                 confirm=True) \
            .add_gather_question(key="incident_date", question="What date did it happen?") \
            .add_gather_question(key="location", question="Where did it happen?") \
            .add_gather_question(key="description", question="Briefly, what happened?") \
            .add_gather_question(key="injuries", question="Was anyone injured?",
                                 type="boolean", confirm=True)
        ctx.add_step("submit") \
            .set_text("Tell the caller you are filing the claim, then call submit_claim.") \
            .set_functions(["submit_claim"]) \
            .set_valid_steps([])  # only the hold (set by the handler) moves the caller on
        ctx.add_step("connected") \
            .set_text("An adjuster accepted claim ${global_data.claim_id}. Tell the caller "
                      "you are connecting them now, then call join_adjuster.") \
            .set_functions(["join_adjuster"]) \
            .set_valid_steps([])
        ctx.add_step("callback") \
            .set_text("No adjuster is free right now. Apologize, tell the caller claim "
                      "${global_data.claim_id} is filed, and ask when an adjuster should call "
                      "them back. Then call promise_callback.") \
            .set_functions(["promise_callback"]) \
            .set_valid_steps([])

    # --- the adjuster's leg: rpc_dial fetches this as dest_swml ----------------
    def _register_routes(self, router):
        super()._register_routes(router)

        @router.api_route("/brief", methods=["GET", "POST"])
        async def brief(request: Request):
            if not self._check_basic_auth(request):
                return JSONResponse({"error": "unauthorized"}, status_code=401)
            claim = claims.get(request.query_params.get("claim", ""))
            if claim is None:
                return JSONResponse({"error": "unknown claim"}, status_code=404)
            return JSONResponse(claims.adjuster_swml(claim, request.query_params.get("call", "")))

    def brief_url(self, claim_id: str, call_id: str) -> str:
        base = self.get_full_url(include_auth=True).rstrip("/")
        return f"{base}/brief?claim={claim_id}&call={call_id}"

    # --- tools ----------------------------------------------------------------
    @AgentBase.tool(
        name="submit_claim",
        description="File the claim from the details already collected and find an adjuster.",
        parameters={"type": "object", "properties": {}},
    )
    def submit_claim(self, args, raw_data):
        gd = raw_data.get("global_data") or {}
        if gd.get("claim_id"):
            return FunctionResult(f"Claim {gd['claim_id']} is already filed.")
        fnol = gd.get("fnol") or {}
        missing = [k for k in claims.FIELDS if fnol.get(k) in (None, "")]
        if missing:
            return FunctionResult(f"Some details are missing: {', '.join(missing)}. Ask for them.")

        claim = claims.create(fnol, raw_data.get("caller_id_num", ""))
        result = FunctionResult().update_global_data({"claim_id": claim["claim_id"]})
        adjuster = config.pick_adjuster(claim)
        if not adjuster or not config.FROM_NUMBER:
            return result.set_response(f"Claim {claim['claim_id']} is filed.") \
                .swml_change_step("callback")
        return (
            result.hold(f"Claim {claim['claim_id']} is filed. Tell the caller you are getting "
                        "an adjuster on the line and to please hold.",
                        config.HOLD_TIMEOUT, step="connected", timeout_step="callback")
            .rpc_dial(to_number=adjuster, from_number=config.FROM_NUMBER,
                      dest_swml=self.brief_url(claim["claim_id"], raw_data.get("call_id", "")))
        )

    @AgentBase.tool(
        name="join_adjuster",
        description="Connect the caller to the adjuster who accepted the claim.",
        parameters={"type": "object", "properties": {}},
    )
    def join_adjuster(self, args, raw_data):
        claim = claims.get((raw_data.get("global_data") or {}).get("claim_id", ""))
        if claim is None:
            return FunctionResult("I can't find the claim.").swml_change_step("callback")
        claims.save({**claim, "status": "bridged"})
        return FunctionResult("Connecting you to the adjuster now.") \
            .join_conference(claim["conference"], end_on_exit=True)

    @AgentBase.tool(
        name="promise_callback",
        description="Record when the caller wants an adjuster to call them back.",
        parameters={
            "type": "object",
            "properties": {
                "preferred_time": {"type": "string",
                                   "description": "When to call back, e.g. 'tomorrow after 2pm'"},
            },
            "required": ["preferred_time"],
        },
    )
    def promise_callback(self, args, raw_data):
        preferred = str(args.get("preferred_time", "")).strip()
        if not preferred:
            return FunctionResult("Ask the caller when a callback would suit them.")
        claim = claims.get((raw_data.get("global_data") or {}).get("claim_id", ""))
        if claim is None:
            return FunctionResult("I can't find the claim. Apologize and say goodbye.").hangup()
        callback = {"number": claim["caller"], "preferred_time": preferred,
                    "promised_at": claims.now()}
        claims.save({**claim, "status": "callback_promised", "callback": callback})
        return FunctionResult(
            f"Callback booked for {preferred} on claim {claim['claim_id']}. Confirm that, "
            "thank the caller, and say goodbye.", post_process=True,
        ).hangup()


agent = ClaimIntakeAgent()

if __name__ == "__main__":
    agent.run()
