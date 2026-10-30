"""Hiring phone screen: a voice form the candidate can't reorder or skip.

Governance point: the `screen` step is a gather. The platform asks the questions
in config.QUESTIONS one at a time, in order, and while it gathers the only callable
tool is gather_submit (confirm=True questions need a read-back first). When the
last answer lands, completion_action moves the call to `submit`, whose one tool
reads the answers from global_data and writes data/candidates/<id>.json. The
model never chooses the candidate id: it comes from the dial URL.
"""
import json
import re
from datetime import datetime, timezone

from signalwire import AgentBase, FunctionResult

import config

ID_PATTERN = re.compile(config.CANDIDATE_ID_PATTERN)


def safe_id(value) -> str | None:
    value = str(value or "")
    return value if ID_PATTERN.match(value) else None


def build_record(global_data: dict, call_id: str | None) -> dict:
    answers = global_data.get(config.OUTPUT_KEY) or {}
    keys = [q["key"] for q in config.QUESTIONS]
    candidate_id = safe_id(global_data.get("candidate_id")) or f"call-{str(call_id or 'unknown')[:8]}"
    return {
        "candidate_id": candidate_id,
        "call_id": call_id,
        "role": config.ROLE_TITLE,
        "submitted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "complete": all(k in answers for k in keys),
        "missing": [k for k in keys if k not in answers],
        "answers": {k: answers.get(k) for k in keys},
    }


class HiringScreenAgent(AgentBase):
    def __init__(self, **kwargs):
        super().__init__(name="hiring-screen", route=config.ROUTE, port=config.PORT, **kwargs)
        self.add_language("English", config.LANGUAGE_CODE, config.VOICE)
        self.prompt_add_section(
            "Role",
            f"You are a recruiting assistant for {config.COMPANY_NAME}, running a short phone "
            f"screen for the {config.ROLE_TITLE} role. Be warm and brief. Do not give "
            "opinions on the answers or say whether the candidate will move forward.",
        )
        self.add_internal_filler("next_step", config.LANGUAGE_CODE, ["Thanks, one moment."])

        ctx = self.define_contexts().add_context("default")
        screen = ctx.add_step("screen") \
            .set_text("Run the screening questions exactly as given, one at a time.") \
            .set_functions([]) \
            .set_valid_steps([]) \
            .set_gather_info(
                output_key=config.OUTPUT_KEY,
                completion_action="submit",
                prompt=f"Introduce yourself, say this is a {len(config.QUESTIONS)}-question screen "
                       f"for the {config.ROLE_TITLE} role, then begin.",
            )
        for q in config.QUESTIONS:
            screen.add_gather_question(**q)
        ctx.add_step("submit") \
            .set_text("Tell the candidate you are saving their answers and call submit_screen.") \
            .set_functions(["submit_screen"]) \
            .set_valid_steps([])
        ctx.add_step("wrap_up") \
            .set_text("Thank the candidate, say a recruiter will follow up within two "
                      "business days, and say goodbye.") \
            .set_functions([]) \
            .set_valid_steps([])

        self.set_dynamic_config_callback(self.per_call)

    @staticmethod
    def per_call(query_params, body_params, headers, agent):
        """The dial URL carries ?candidate=<id>; keep it in global_data, out of the model's hands."""
        candidate_id = safe_id(query_params.get("candidate"))
        if candidate_id:
            agent.set_global_data({"candidate_id": candidate_id})

    @AgentBase.tool(
        name="submit_screen",
        description="Save the candidate's screening answers.",
        parameters={"type": "object", "properties": {}},
    )
    def submit_screen(self, args, raw_data):
        record = build_record(raw_data.get("global_data") or {}, raw_data.get("call_id"))
        config.CANDIDATES_DIR.mkdir(parents=True, exist_ok=True)
        path = config.CANDIDATES_DIR / f"{record['candidate_id']}.json"
        path.write_text(json.dumps(record, indent=2) + "\n")
        return (
            FunctionResult("The answers are saved.")
            .update_global_data({"submitted": record["candidate_id"]})
            .swml_change_step("wrap_up")
        )


agent = HiringScreenAgent()

if __name__ == "__main__":
    agent.run()
