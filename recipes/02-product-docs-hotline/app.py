"""AI Product Docs Hotline: answers product questions only from a bundled search index.

Governance point: grounding is enforced by the tool, not requested by the prompt. The
agent has exactly one tool, search_docs, which reads only data/knowledge.swsearch.
grounded_only() applies the similarity threshold in code before the model sees
anything, so an off-topic question returns the fixed NOT_IN_DOCS marker instead of
weak matches the model could stretch into an answer.
"""
from signalwire import AgentBase

import config

RULES = [
    f"For every question about {config.PRODUCT_NAME}, call {config.SEARCH_TOOL} first. "
    "Never answer from your own knowledge, even if you think you know.",
    f"Answer only with facts from the {config.SEARCH_TOOL} results. Keep it to two or three "
    "spoken sentences. Don't read out file names, scores or code.",
    f"If {config.SEARCH_TOOL} returns NOT_IN_DOCS, or the results don't answer the question, "
    f"say exactly: \"{config.REFUSAL}\" Then offer to help with something else.",
    "If the caller's question is unclear, ask one short clarifying question before searching.",
]


def grounded_only(response, results, **_):
    """The skill's response_format_callback: the gate between the index and the model.

    It keeps only chunks the embedding search itself scored at or above the threshold.
    We gate on vector_score instead of the skill's similarity_threshold because in
    3.7.5 a keyword-only hit (say, "states" in the 10DLC page for "what states do you
    serve?") can score past that threshold with no semantic match at all.
    """
    kept = [r for r in results if r.get("vector_score", 0.0) >= config.SIMILARITY_THRESHOLD]
    if not kept:
        return config.NOT_IN_DOCS
    excerpts = [f"[{r['metadata']['filename']}] {r['content'][:config.MAX_CHUNK_CHARS]}" for r in kept]
    return "Docs excerpts. Answer only from these:\n\n" + "\n\n".join(excerpts)


class DocsHotline(AgentBase):
    def __init__(self, **kwargs):
        super().__init__(name="docs-hotline", route=config.ROUTE, port=config.PORT, **kwargs)

        self.add_language("English", config.LANGUAGE_CODE, config.VOICE,
                          function_fillers=["Let me check the docs.", "One moment."])
        self.prompt_add_section(
            "Role",
            f"You are the {config.PRODUCT_NAME} docs hotline. Callers ask how the product works. "
            "You are friendly and brief.",
        )
        # The skill appends one bullet to a "Knowledge Search" section if it exists, or
        # creates its own that says "try another knowledge source". skip_prompt doesn't
        # stop that in 3.7.5, so we create the section first with our rules.
        self.prompt_add_section("Knowledge Search", bullets=RULES)

        # The only tool.
        self.add_skill("native_vector_search", {
            "tool_name": config.SEARCH_TOOL,
            "description": f"Search the {config.PRODUCT_NAME} product docs. "
                           "Pass the caller's question as the query.",
            "index_file": str(config.INDEX_FILE),
            "count": config.SEARCH_COUNT,
            "no_results_message": config.NOT_IN_DOCS,
            "response_format_callback": grounded_only,   # threshold enforced here
        })

    def search(self, query: str) -> str:
        """Run the search tool exactly as a call would. Used by tests and warm_up()."""
        result = self.on_function_call(config.SEARCH_TOOL, {"query": query}, {})
        return result.to_dict()["response"]

    def warm_up(self) -> None:
        """Load the embedding model before the first call, so caller #1 doesn't wait."""
        self.search("warm up")


agent = DocsHotline()

if __name__ == "__main__":
    agent.warm_up()
    agent.run()
