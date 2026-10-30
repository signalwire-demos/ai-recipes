"""Template recipe: an office-hours line in two steps.

Governance point: the caller can't skip ahead. The `lookup` step exposes one
tool and has no navigation (valid_steps=[]), so only the check_hours handler can
move the call to `wrap_up`, and `wrap_up` has no tools at all.
"""
import json

from signalwire import AgentBase, FunctionResult

import config

DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def load_hours() -> dict:
    return json.loads(config.HOURS_FILE.read_text())


class TemplateAgent(AgentBase):
    def __init__(self, **kwargs):
        super().__init__(name="template", route=config.ROUTE, port=config.PORT, **kwargs)
        self.hours = load_hours()

        self.add_language("English", config.LANGUAGE_CODE, config.VOICE)
        self.prompt_add_section(
            "Role",
            f"You answer the phone for {config.BUSINESS_NAME}. Be brief and friendly.",
        )

        ctx = self.define_contexts().add_context("default")
        ctx.add_step("lookup") \
            .set_text("Ask which day the caller wants to visit, then call check_hours with that day.") \
            .set_functions(["check_hours"]) \
            .set_valid_steps([])  # the model cannot leave this step; only the handler can
        ctx.add_step("wrap_up") \
            .set_text(
                "Tell the caller the hours for ${global_data.day}: ${global_data.hours}. "
                "Ask if there is anything else, then say goodbye."
            ) \
            .set_functions([])  # explicit: no tools here (steps inherit tools otherwise)

    @AgentBase.tool(
        name="check_hours",
        description="Look up opening hours for one day of the week.",
        parameters={
            "type": "object",
            "properties": {
                "day": {"type": "string", "description": "Day of the week, e.g. monday"},
            },
            "required": ["day"],
        },
    )
    def check_hours(self, args, raw_data):
        day = str(args.get("day", "")).strip().lower()
        if day not in DAYS:
            return FunctionResult("That isn't a day of the week. Ask the caller which day they mean.")

        slot = self.hours.get(day)
        hours = f"{slot['open']} to {slot['close']}" if slot else "closed"
        return (
            FunctionResult(f"On {day} we are {'open ' + hours if slot else 'closed'}.")
            .update_global_data({"day": day, "hours": hours})
            .swml_change_step("wrap_up")
        )


agent = TemplateAgent()

if __name__ == "__main__":
    agent.run()
