"""AI Trivia Hotline: the model hosts, the code keeps score.

Governance point: the answer key never leaves this server. The model sees only
the current question (${global_data.question}). submit_answer grades in Python,
keeps round and score in global_data, and loads the next question, so the model
tracks nothing and can't leak, guess or retry an answer. After ROUNDS questions
the handler moves the call to final_score, which has zero tools.
"""
import json
import random
import re
from difflib import SequenceMatcher

from signalwire import AgentBase, FunctionResult

import config

FILLER_WORDS = {"the", "a", "an", "um", "uh"}


def load_questions() -> dict:
    questions = {q["id"]: q for q in json.loads(config.QUESTIONS_FILE.read_text())}
    if config.ROUNDS > len(questions):
        raise ValueError(f"ROUNDS={config.ROUNDS} but only {len(questions)} questions in the file")
    return questions


def words(text: str) -> list[str]:
    tokens = re.sub(r"[^a-z0-9 ]", " ", str(text).lower()).split()
    return [t for t in tokens if t not in FILLER_WORDS]


def is_correct(guess: str, accepted: list[str]) -> bool:
    """True if any accepted answer matches the guess, or a same-length run of its words,
    within FUZZY_TOLERANCE. "I think it's shakespear" matches "Shakespeare"."""
    said = words(guess)
    for answer in accepted:
        want = " ".join(words(answer))
        if not want:
            continue
        n = len(want.split())
        for i in range(max(1, len(said) - n + 1)):
            window = " ".join(said[i:i + n])
            if SequenceMatcher(None, window, want).ratio() >= config.FUZZY_TOLERANCE:
                return True
    return False


def model_state(questions: dict, order: list[str], round_no: int, score: int) -> dict:
    """The only game state the model sees: question text, ids, round and score."""
    qid = order[0] if order else ""
    return {"round": round_no, "score": score, "question_id": qid,
            "question": questions[qid]["question"] if qid else "", "queue": order[1:]}


class TriviaAgent(AgentBase):
    def __init__(self, **kwargs):
        super().__init__(name="trivia-hotline", route=config.ROUTE, port=config.PORT, **kwargs)
        self.questions = load_questions()
        self.set_dynamic_config_callback(self.start_game)

        self.add_language("English", config.LANGUAGE_CODE, config.VOICE)
        self.prompt_add_section(
            "Role",
            f"You host {config.SHOW_NAME}, a phone trivia game of {config.ROUNDS} questions. "
            "Be upbeat and quick. You do not know the answers: never hint at, guess or "
            "confirm an answer yourself. The scorekeeper tool submit_answer grades every "
            "answer and tells you the result and the next question.",
        )

        ctx = self.define_contexts().add_context("default")
        ctx.add_step("play") \
            .set_text(
                "This is round ${global_data.round}. Ask exactly this question: "
                "${global_data.question} When the caller answers (or gives up), call "
                "submit_answer with their words. Read out the result it returns, then "
                "ask the next question it gives you."
            ) \
            .set_functions(["submit_answer"]) \
            .set_valid_steps([])  # only the handler can end the game
        ctx.add_step("final_score") \
            .set_text(
                f"The game is over. Tell the caller they scored ${{global_data.score}} out "
                f"of {config.ROUNDS}, thank them for playing and say goodbye."
            ) \
            .set_functions([]) \
            .set_valid_steps([]) \
            .set_end(True)
        # zero tools (steps inherit them otherwise), and no next_step: without valid_steps the
        # platform offers next_step to "next", which doesn't exist after the last step. Live call
        # 943ed374 looped on next_step("next") and then on hangup before it said goodbye.

    def start_game(self, query_params, body_params, headers, agent) -> None:
        """Per call: pick this call's questions and put the first one in global_data."""
        order = list(self.questions)
        if config.SHUFFLE:
            random.shuffle(order)
        agent.set_global_data(model_state(self.questions, order[:config.ROUNDS], 1, 0))

    @AgentBase.tool(
        name="submit_answer",
        description="Submit the caller's answer to the current question for grading.",
        parameters={
            "type": "object",
            "properties": {
                "answer": {"type": "string", "description": "What the caller said, verbatim"},
            },
            "required": ["answer"],
        },
    )
    def submit_answer(self, args, raw_data):
        state = (raw_data or {}).get("global_data") or {}
        question = self.questions.get(state.get("question_id", ""))
        if not question:
            return FunctionResult("There is no question in play.")

        correct = is_correct(args.get("answer", ""), question["answers"])
        score = int(state.get("score", 0)) + (1 if correct else 0)
        round_no = int(state.get("round", 1))
        if correct:
            verdict = "Correct!"
        elif config.REVEAL_ANSWER_ON_MISS:
            verdict = f"Not quite. The answer was {question['answers'][0]}."
        else:
            verdict = "Not quite."

        queue = list(state.get("queue", []))
        if round_no >= config.ROUNDS or not queue:
            return (
                FunctionResult(f"{verdict} That was the last question. Final score: {score}.")
                .update_global_data(model_state(self.questions, [], round_no, score))
                .swml_change_step("final_score")
            )
        nxt = model_state(self.questions, queue, round_no + 1, score)
        return (
            FunctionResult(f"{verdict} Score: {score}. Round {round_no + 1}: {nxt['question']}")
            .update_global_data(nxt)
        )


agent = TriviaAgent()

if __name__ == "__main__":
    agent.run()
