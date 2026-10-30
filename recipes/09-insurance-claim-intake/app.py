"""AI Insurance Claim Intake: first notice of loss, then a screened handoff to an adjuster.

Governance point: the adjuster is briefed before the bridge completes, and the model never
drives the handoff. Gather collects the claim one question at a time, and code checks every
answer: a per-question check_* tool rejects a bad answer with a re-ask, and submit_claim
checks the whole record again before filing anything. submit_claim (the only
tool in `submit`) writes the claim record, holds the caller and rpc_dials the adjuster with
a dest_swml that speaks a briefing built from the record and waits for a keypress. The hold
decides where the caller lands: `connected` if the adjuster pressed 1 (their SWML releases
the hold), `callback` if the hold timed out. Each of those steps has exactly one tool.
"""
import json

from fastapi import Request
from fastapi.responses import JSONResponse

from signalwire import AgentBase, FunctionResult

import answers
import claims
import config


class ClaimIntakeAgent(AgentBase):
    def __init__(self, **kwargs):
        super().__init__(name="claim-intake", route=config.ROUTE, port=config.PORT, **kwargs)
        self.add_language("English", config.LANGUAGE_CODE, config.VOICE)
        self.set_prompt_llm_params(model=config.MODEL, temperature=0.2)
        self.prompt_add_section(
            "Role",
            f"You take first notice of loss calls for {config.COMPANY_NAME} insurance. "
            "Be calm, brief and kind. Never promise coverage or a payout. Ask only the "
            "question you are given, one at a time. You already have the caller's phone "
            "number from the call, so never ask for it or for anything else not asked here.",
        )
        for key in ("policy_number", "incident_date", "location", "injuries"):
            self.define_tool(name=f"check_{key}", handler=self._checker(key),
                             description=f"Check the caller's answer for the {key.replace('_', ' ')}"
                                         " before submitting it. Pass their exact words.",
                             parameters={"words": {"type": "string",
                                                   "description": "The caller's exact words"}},
                             required=["words"])

        def check_first(key, extra=""):
            return (f"Before submitting, call check_{key} with the caller's exact words. Submit "
                    f"only the value it accepts{extra}. If it rejects the answer, ask what it says.")

        ctx = self.define_contexts().add_context("default")
        ctx.add_step("intake") \
            .set_text("Collect the claim details by asking the questions one at a time.") \
            .set_functions([]) \
            .set_valid_steps([]) \
            .set_gather_info(output_key="fnol", completion_action="submit", isolated=True,
                             prompt="I'm sorry that happened. I'll take a few details.") \
            .add_gather_question(key="policy_number", functions=["check_policy_number"],
                                 question="What is your policy number? It starts with P O L "
                                          f"and then {config.POLICY_DIGITS} digits.",
                                 prompt=check_first("policy_number")) \
            .add_gather_question(key="incident_date", confirm=True,
                                 question="On what date did the incident happen?",
                                 functions=["check_incident_date"],
                                 prompt=check_first("incident_date", ", as YYYY-MM-DD, after "
                                                    "reading the date back")) \
            .add_gather_question(key="location", functions=["check_location"],
                                 question="Where did the incident happen? A street, "
                                          "intersection or city is fine.",
                                 prompt=check_first("location")) \
            .add_gather_question(key="description", question="In a sentence or two, what happened?") \
            .add_gather_question(key="injuries", type="boolean", confirm=True,
                                 question="Was anyone hurt? Please answer yes or no.",
                                 functions=["check_injuries"], prompt=check_first("injuries"))
        ctx.add_step("submit") \
            .set_text("Tell the caller you are filing the claim, then call submit_claim. If it "
                      "says an answer was not accepted, ask exactly the question it gives and "
                      "call submit_claim again with the caller's words as `answer`.") \
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
    def _checker(self, key):
        def check(args, raw_data):
            value, reason = answers.CHECKS[key](args.get("words", ""))
            if reason:
                return FunctionResult(f"Not accepted. Do not submit it. Ask the caller: {reason}")
            said = f" Read it back as {answers.spoken_date(value)}." if key == "incident_date" else ""
            return FunctionResult(f"Accepted.{said} Submit exactly this value: {json.dumps(value)}.")
        return check

    @AgentBase.tool(
        name="submit_claim",
        description="File the claim from the details already collected and find an adjuster.",
        parameters={"type": "object", "properties": {"answer": {
            "type": "string", "description": "Only when re-asking: the caller's exact words"}}},
    )
    def submit_claim(self, args, raw_data):
        gd = raw_data.get("global_data") or {}
        if gd.get("claim_id"):
            return FunctionResult(f"Claim {gd['claim_id']} is already filed.")
        fnol = dict(gd.get("fnol") or {})
        if gd.get("fix_field") and str(args.get("answer", "")).strip():
            fnol[gd["fix_field"]] = args["answer"]  # code chose which answer is being corrected
        clean = {}
        for key in claims.FIELDS:  # gather_submit answers are caller input: check them again
            clean[key], reason = answers.CHECKS[key](fnol.get(key, ""))
            if reason:
                return FunctionResult(
                    f"Not filed yet: the {key.replace('_', ' ')} was not accepted. Ask the "
                    f"caller: {reason} Then call submit_claim with their words as answer.",
                ).update_global_data({"fnol": fnol, "fix_field": key})

        claim = claims.create(clean, raw_data.get("caller_id_num", ""))  # caller ID, never asked
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
