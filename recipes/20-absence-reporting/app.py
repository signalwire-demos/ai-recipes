"""Absence reporting line: grammar filling.

Governance point: the caller fills six slots in any order, in any number of
turns, and the model can't decide it's done. `collect` has one tool and no
navigation (valid_steps=[]). record_slots merges each turn into global_data,
validates every value in code, and only changes step to `confirm` when nothing
is missing. submit_report exists only in `confirm`, and re-checks the slots
before it writes anything.
"""
import json
import re
import uuid

from signalwire import AgentBase, FunctionResult

import config
from slots import fill

SLOTS = config.SLOTS
ONE_DAY = re.compile(r"\b(same|that|one|just the) day\b|\bjust (that|one|the one) day\b", re.I)


def summary(report: dict) -> str:
    days = report["start_date"] if report["start_date"] == report["end_date"] \
        else f"{report['start_date']} through {report['end_date']}"
    return (f"{report['name']}, ID {' '.join(report['id'])}, {report['org_type']} absence "
            f"on {days}, reason: {report['reason']}")


class AbsenceAgent(AgentBase):
    def __init__(self, **kwargs):
        super().__init__(name="absence-reporting", route=config.ROUTE, port=config.PORT, **kwargs)
        self.add_language("English", config.LANGUAGE_CODE, config.VOICE)
        self.prompt_add_section(
            "Role",
            f"You take absence reports for {config.ORG_NAME} by phone. Be brief and warm. "
            "Let the caller say things in any order. Never invent a value the caller didn't say.",
        )
        self.set_prompt_llm_params(model=config.MODEL)
        self.set_global_data({"absence": {}})

        ctx = self.define_contexts().add_context("default")
        ctx.add_step("collect") \
            .set_text(
                "Ask who will be absent and why. Whenever the caller gives any detail, call "
                "record_slots with every detail from that turn, using their exact words for dates, "
                "even a date that sounds unclear: the tool checks it and tells you what to ask. "
                "Then ask only for what the tool says is still missing."
            ) \
            .set_functions(["record_slots"]) \
            .set_valid_steps([])  # no next_step tool: only record_slots can open `confirm`
        ctx.add_step("confirm") \
            .set_text(
                "Read back this report: ${global_data.absence_summary}. Ask if it is right. "
                "If yes, call submit_report. If they correct something, call record_slots with "
                "only the corrected detail."
            ) \
            .set_functions(["record_slots", "submit_report"]) \
            .set_valid_steps([])
        ctx.add_step("done") \
            .set_text("Give the caller reference ${global_data.reference}, then say goodbye.") \
            .set_functions([]) \
            .set_valid_steps([]) \
            .set_end(True)  # explicit: no tools after submitting

        self.define_tool(
            name="record_slots",
            description="Record any absence details the caller just gave, in any order. "
                        "Leave out anything they didn't say.",
            parameters={name: {"type": "string", "description": desc} for name, (desc, _) in SLOTS.items()},
            required=[],
            handler=self.record_slots,
        )

    def record_slots(self, args, raw_data):
        saved = (raw_data.get("global_data") or {}).get("absence") or {}
        args = dict(args)
        one_day = bool(ONE_DAY.search(str(args.get("end_date") or "")))
        if one_day:
            args.pop("end_date")
        report, missing, problems = fill(saved, args, {k: v for k, (_, v) in SLOTS.items()})
        if one_day and report.get("start_date"):   # "just that day": the last day is the first
            report["end_date"] = report["start_date"]
            missing = [m for m in missing if m != "end_date"]
        if problems or missing:
            asks = [f"{name}: {question}" for name, question in problems.items()]
            asks += [name for name in missing if name not in problems]
            return FunctionResult(f"Not done yet. Ask the caller about: {'; '.join(asks)}.") \
                .update_global_data({"absence": report})
        return (FunctionResult(f"All details recorded: {summary(report)}.")
                .update_global_data({"absence": report, "absence_summary": summary(report)})
                .swml_change_step("confirm"))

    @AgentBase.tool(
        name="submit_report",
        description="Submit the absence report after the caller confirms the readback.",
        parameters={"type": "object", "properties": {}},
    )
    def submit_report(self, args, raw_data):
        report = (raw_data.get("global_data") or {}).get("absence") or {}
        missing = [name for name in SLOTS if not report.get(name)]
        if missing:  # belt and braces: the step can't be reached like this, but never write a partial
            return FunctionResult(f"Can't submit yet, missing {', '.join(missing)}.") \
                .swml_change_step("collect")
        reference = "AB-" + uuid.uuid4().hex[:6].upper()
        config.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        record = {"reference": reference, **{name: report[name] for name in SLOTS}}
        (config.REPORTS_DIR / f"{reference}.json").write_text(json.dumps(record, indent=2))
        return (FunctionResult(f"Submitted. The reference is {' '.join(reference)}.")
                .update_global_data({"reference": " ".join(reference)})
                .swml_change_step("done"))


agent = AbsenceAgent()

if __name__ == "__main__":
    agent.run()
