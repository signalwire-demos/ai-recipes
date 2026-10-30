"""The fixed extraction schema, the post_prompt built from it, and strict validation.

One source of truth: the schema below is what the post_prompt asks for and what every stored
summary is checked against. A summary that doesn't match is flagged with its errors, never
repaired or guessed at.
"""
import json

import jsonschema_rs

import config

SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": ["outcome", "reasons", "competitor", "objections"],
    "properties": {
        "outcome": {"enum": config.OUTCOMES},
        "reasons": {"type": "array", "minItems": 1, "maxItems": config.MAX_REASONS,
                    "uniqueItems": True, "items": {"enum": config.REASONS}},
        "competitor": {"type": ["string", "null"], "minLength": 1},
        "objections": {"type": "array", "items": {"type": "string", "minLength": 1}},
    },
}
_validator = jsonschema_rs.validator_for(SCHEMA)

POST_PROMPT = (
    "Analyze the interview above. Return ONLY a JSON object, no prose and no code fences, "
    "with exactly these keys:\n"
    f'- "outcome": one of {json.dumps(config.OUTCOMES)} (did they buy {config.COMPANY_NAME}?)\n'
    f'- "reasons": 1 to {config.MAX_REASONS} of {json.dumps(config.REASONS)}, the main reasons '
    "for the outcome, most important first\n"
    '- "competitor": the other vendor they chose or compared most closely, or null\n'
    '- "objections": short phrases for each concern they raised about us, or []\n'
    "Use only what the prospect said. If they did not say, use null or []."
)


def parse(summary) -> tuple[dict | None, list[str]]:
    """(record, errors). Accepts what on_summary receives: a parsed dict, a raw string, or None."""
    if summary is None:
        return None, ["no summary returned"]
    if isinstance(summary, str):
        try:
            summary = json.loads(summary)
        except json.JSONDecodeError as exc:
            return None, [f"not JSON: {exc.msg}"]
    if not isinstance(summary, dict):
        return None, [f"expected an object, got {type(summary).__name__}"]
    errors = [f"{'/'.join(map(str, e.instance_path)) or '(root)'}: {e.message}"
              for e in _validator.iter_errors(summary)]
    return (None, errors) if errors else (summary, [])


def competitor_name(raw: str | None) -> str | None:
    if not raw:
        return None
    return config.COMPETITOR_ALIASES.get(raw.strip().lower(), raw.strip())
