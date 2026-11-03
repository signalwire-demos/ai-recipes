"""Customer survey caller: the SurveyAgent prefab, configured from config.py.

The prefab brings the survey prompt, hints, a post-prompt summary and two tools
(validate_response, log_response). This recipe adds two things on top:

1. Both tools are overridden, with one shared schema, so the handler, not the
   model, decides what counts as an answer and what gets recorded: the answer is
   normalized and checked against the question (rating in range, as digits or
   words; option on the list; yes or no). Invalid answers are refused and never
   written. Valid ones are appended to data/results.jsonl by log_response.
2. The customer id comes from the dial URL (?customer=) via dynamic config, so
   the model never chooses whose survey a row belongs to.
"""
import copy
import json
import re
from datetime import datetime, timezone

from signalwire import AgentBase, FunctionResult
from signalwire.prefabs import SurveyAgent

import config

YES = {"yes", "y", "yeah", "yep", "sure"}
NUMBER_WORDS = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen "
    "fifteen sixteen seventeen eighteen nineteen twenty".split())}


def spoken_number(text: str) -> int | None:
    """The first number in the answer, as digits or as a word: "9", "nine", "a nine out of ten".

    The live call passed log_response("nine"), which int() can't read, so a valid rating was
    refused (call 46145b42).
    """
    m = re.search(r"\d+(?:\.\d+)?", text)
    if m:
        return int(float(m[0]))
    for word in re.findall(r"[a-z]+", text):
        if word in NUMBER_WORDS:
            return NUMBER_WORDS[word]
    return None
NO = {"no", "n", "nope", "nah"}


def normalize(question: dict, response) -> tuple:
    """Return (value, None) for a valid answer, or (None, reason) to refuse it."""
    text = str(response if response is not None else "").strip().lower().rstrip(".!")
    kind = question["type"]
    if kind == "rating":
        scale = question.get("scale", 5)
        value = spoken_number(text)
        if value is None:
            return None, f"That isn't a number. Ask for a number from 1 to {scale}."
        if not 1 <= value <= scale:
            return None, f"Ratings go from 1 to {scale}. Ask again."
        return value, None
    if kind == "multiple_choice":
        for option in question["options"]:
            if text == option.lower():
                return option, None
        return None, f"Not an option. Offer these again: {', '.join(question['options'])}."
    if kind == "yes_no":
        if text in YES:
            return "yes", None
        if text in NO:
            return "no", None
        return None, "Ask for a yes or a no."
    if not text and question.get("required", True):
        return None, "This question needs an answer."
    return str(response or "").strip(), None


# One schema for both tools, so validate_response and log_response agree on the answer. The
# question ids are the same config.QUESTIONS the handlers check; both fields are required.
ANSWER_PARAMS = {
    "type": "object",
    "properties": {
        "question_id": {
            "type": "string",
            "description": "ID of the question just answered, from the Survey Questions list.",
            "enum": [q["id"] for q in config.QUESTIONS],
        },
        "response": {
            "type": "string",
            "description": (
                "The caller's answer exactly as spoken: for a rating the number (digits or "
                "words), for multiple choice one of the listed options, for yes/no 'yes' or "
                "'no', otherwise their words; empty string if they decline an optional "
                "question. Never fill this in yourself; ask if the caller has not answered."
            ),
        },
    },
    "required": ["question_id", "response"],
}


class SurveyCaller(SurveyAgent):
    def __init__(self, **kwargs):
        super().__init__(
            survey_name=config.SURVEY_NAME,
            brand_name=config.BRAND_NAME,
            questions=copy.deepcopy(config.QUESTIONS),
            introduction=config.INTRODUCTION,
            conclusion=config.CONCLUSION,
            name="survey-caller",
            route=config.ROUTE,
            port=config.PORT,
            **kwargs,
        )
        self.add_language("English", config.LANGUAGE_CODE, config.VOICE)
        self.prompt_add_section(
            "Recording answers",
            "After each answer, call log_response with the question ID and the caller's "
            "answer. If it is refused, ask the question again. Never record an answer "
            "the caller did not give.",
        )
        self.set_dynamic_config_callback(self.per_call)

    @staticmethod
    def per_call(query_params, body_params, headers, agent):
        customer_id = str(query_params.get("customer") or "")
        if re.match(config.CUSTOMER_ID_PATTERN, customer_id):
            agent.update_global_data({"customer_id": customer_id})

    def _answer(self, args) -> tuple:
        """The question and answer the tool args name, or (None, None, what to ask for)."""
        question = next((q for q in self.questions if q["id"] == args.get("question_id")), None)
        if question is None:
            ids = ", ".join(q["id"] for q in self.questions)
            return None, None, f"Unknown question. Use one of: {ids}."
        if args.get("response") is None:
            return None, None, f"No answer was given. Ask the caller: {question['text']}"
        return question, args["response"], None

    @AgentBase.tool(
        name="validate_response",
        description="Check the caller's answer to one survey question before recording it.",
        parameters=ANSWER_PARAMS,
    )
    def validate_response(self, args, raw_data):
        # The prefab's version int()-parses ratings, so "nine" was invalid here and valid in
        # log_response (call 46145b42). Same schema, same normalize(): the two tools agree.
        question, response, error = self._answer(args)
        if error:
            return FunctionResult(error)
        value, error = normalize(question, response)
        if error:
            return FunctionResult(f"Not valid. {error}")
        return FunctionResult(f"Valid: {question['id']} = {value}. Call log_response with the answer.")

    @AgentBase.tool(
        name="log_response",
        description="Record the caller's answer to one survey question.",
        parameters=ANSWER_PARAMS,
    )
    def log_response(self, args, raw_data):
        question, response, error = self._answer(args)
        if error:
            return FunctionResult(error)
        value, error = normalize(question, response)
        if error:
            return FunctionResult(f"Not recorded. {error}")
        row = {
            "survey": config.SURVEY_NAME,
            "call_id": raw_data.get("call_id"),
            "customer_id": (raw_data.get("global_data") or {}).get("customer_id"),
            "question_id": question["id"],
            "answer": value,
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        config.RESULTS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with config.RESULTS_FILE.open("a") as f:
            f.write(json.dumps(row) + "\n")
        return FunctionResult(f"Recorded {question['id']} = {value}. Go to the next question.")


agent = SurveyCaller()

if __name__ == "__main__":
    agent.run()
