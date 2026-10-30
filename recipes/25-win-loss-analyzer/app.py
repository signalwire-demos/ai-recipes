"""AI Competitive Win/Loss Analyzer: the interview line that feeds analyze.py.

Governance point: the analysis is a pipeline you own, not a prompt you hope about. The
interviewer has no tools and cannot write anything. After the call, SignalWire's AI runs the
post_prompt (built from the schema in extraction.py) and posts the result to on_summary,
which validates it in code and appends it to data/runtime/calls.jsonl. A summary that fails
the schema is stored flagged with its errors, never repaired. analyze.py aggregates only
valid records into the report.
"""
import json
from datetime import datetime, timezone

from signalwire import AgentBase

import config
import extraction


class WinLossAgent(AgentBase):
    def __init__(self, **kwargs):
        super().__init__(name="win-loss", route=config.ROUTE, port=config.PORT, **kwargs)
        self.add_language("English", config.LANGUAGE_CODE, config.VOICE)
        self.prompt_add_section(
            "Role",
            f"You run short win/loss interviews for {config.COMPANY_NAME} with prospects who "
            "recently made a buying decision. Be curious and neutral. Never argue, sell, or "
            "defend the product. Ask one question at a time and keep the call under five minutes.",
        )

        ctx = self.define_contexts().add_context("default")
        ctx.add_step("interview") \
            .set_text(
                "Thank them for their time. Then ask, one at a time: did they choose "
                f"{config.COMPANY_NAME}; what mattered most in the decision; which other "
                "vendors they looked at and which one they picked; and any concerns they had "
                "about us. Ask one follow-up if an answer is vague."
            ) \
            .set_step_criteria("All four topics have been covered, or the prospect wants to stop.") \
            .set_functions([]) \
            .set_valid_steps(["wrap_up"])
        ctx.add_step("wrap_up") \
            .set_text("Thank them, say the feedback goes straight to the product team, and say goodbye.") \
            .set_functions([]) \
            .set_valid_steps([])

        # Extraction runs on SignalWire's AI after the call, against the fixed schema.
        self.set_post_prompt(extraction.POST_PROMPT)
        self.set_post_prompt_llm_params(temperature=config.POST_PROMPT_TEMPERATURE)

    def on_summary(self, summary, raw_data=None):
        """Validate the extraction and append one record per call. Bad output is flagged."""
        record, errors = extraction.parse(summary)
        raw_data = raw_data or {}
        row = {
            "call_id": raw_data.get("call_id"),
            "received_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "valid": not errors,
            "errors": errors,
            "summary": record,
            "raw": None if record else (raw_data.get("post_prompt_data") or {}).get("raw"),
        }
        config.CALLS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with config.CALLS_FILE.open("a") as f:
            f.write(json.dumps(row) + "\n")


agent = WinLossAgent()

if __name__ == "__main__":
    agent.run()
