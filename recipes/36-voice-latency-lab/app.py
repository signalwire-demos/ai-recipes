"""Voice latency lab: one agent, N configurations, measured from the platform's own timings.

Governance point: model choice is a configuration change, not a code change. The
dynamic config callback picks a configuration from a server-side whitelist
(config.CONFIGS, chosen by ?config=) and changes only two things: the LLM model
(set_prompt_llm_params) and the TTS voice (add_language). Prompt, tool and step are
identical for every configuration, so the lab compares like with like. Every call's
post-prompt payload, which carries the per-turn timing stamps, is saved for lab/.
"""
import json
import re

from signalwire import AgentBase, FunctionResult

import config

DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
DEFAULT_CONFIG = next(iter(config.CONFIGS))
SAFE_ID = re.compile(r"[^A-Za-z0-9_-]")


def pick_config(query_params: dict) -> str:
    name = str((query_params or {}).get("config", ""))
    return name if name in config.CONFIGS else DEFAULT_CONFIG  # never a model name from the URL


def configure(query_params, body_params, headers, agent):
    """Per request: apply exactly one whitelisted configuration to a copy of the agent."""
    name = pick_config(query_params)
    cfg = config.CONFIGS[name]
    agent.add_language("English", "en-US", cfg["voice"])
    agent.set_prompt_llm_params(model=cfg["model"], temperature=config.TEMPERATURE)
    agent.set_global_data({"lab_config": name})  # comes back in the post-prompt payload


class LatencyLabAgent(AgentBase):
    def __init__(self, **kwargs):
        super().__init__(name="latency-lab", route=config.ROUTE, port=config.PORT, **kwargs)
        self.hours = json.loads(config.HOURS_FILE.read_text())

        self.prompt_add_section(
            "Role",
            f"You answer the phone for {config.BUSINESS_NAME}. Keep every reply to one short "
            "sentence. When the caller says goodbye, say goodbye.",
        )
        ctx = self.define_contexts().add_context("default")
        ctx.add_step("answer") \
            .set_text("Answer questions about opening hours. For any day, call check_hours.") \
            .set_functions(["check_hours"]) \
            .set_valid_steps([])
        self.set_post_prompt('Return only JSON: {"answered_hours": true|false}')
        self.set_dynamic_config_callback(configure)

    @AgentBase.tool(
        name="check_hours",
        description="Look up opening hours for one day of the week.",
        parameters={
            "type": "object",
            "properties": {"day": {"type": "string", "description": "Day of the week, e.g. monday"}},
            "required": ["day"],
        },
    )
    def check_hours(self, args, raw_data):
        day = str(args.get("day", "")).strip().lower()
        if day not in DAYS:
            return FunctionResult("That isn't a day of the week. Ask which day they mean.")
        slot = self.hours.get(day)
        return FunctionResult(f"{day}: " + (f"open {slot['open']} to {slot['close']}" if slot else "closed"))

    def on_summary(self, summary, raw_data=None):
        """Save the whole post-prompt payload, filed under the configuration that served it."""
        raw_data = raw_data or {}
        name = (raw_data.get("global_data") or {}).get("lab_config")
        if name not in config.CONFIGS:
            return
        call_id = SAFE_ID.sub("", str(raw_data.get("call_id") or "unknown"))[:64]
        out = config.RUNS_DIR / name / f"{call_id}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(raw_data, indent=1, sort_keys=True))


agent = LatencyLabAgent()

if __name__ == "__main__":
    agent.run()
