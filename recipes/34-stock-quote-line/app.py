"""AI stock quote line: two agents, one reusable skill.

Governance point: the quote logic lives in a skill (skills/stock_quote), not in
either agent. Each agent loads it with add_skill() and its own params. The skill
holds the provider call, the API key and the watchlist rule, so the stock-plan
line can only quote ACME however the caller asks, and neither model ever sees
the key.
"""
import signalwire
from signalwire import AgentBase, AgentServer

import config

signalwire.add_skill_directory(str(config.SKILLS_DIR))   # finds skills/stock_quote/skill.py


class QuoteLineAgent(AgentBase):
    """Agent 1: public quote line, any ticker the provider knows."""

    def __init__(self, **kwargs):
        super().__init__(name="quote-line", route=config.QUOTE_LINE_ROUTE, port=config.PORT, **kwargs)
        self.add_language("English", config.LANGUAGE_CODE, config.VOICE)
        self.prompt_add_section(
            "Role",
            f"You run the {config.QUOTE_LINE_NAME}. Ask which stock the caller wants, "
            "give the quote, and offer another. You don't give investment advice.",
        )
        self.add_skill("stock_quote", config.skill_params())


class StockPlanAgent(AgentBase):
    """Agent 2: employee stock-plan line. Same skill, scoped by its params."""

    def __init__(self, **kwargs):
        super().__init__(name="stock-plan", route=config.DESK_ROUTE, port=config.PORT, **kwargs)
        self.add_language("English", config.LANGUAGE_CODE, config.VOICE)
        self.prompt_add_section(
            "Role",
            f"You answer the {config.DESK_COMPANY} employee stock-plan line. Callers ask "
            "what the company's shares are worth today. Questions about vesting or "
            "selling go to the plan administrator.",
        )
        self.add_skill("stock_quote", config.skill_params(
            tool_name=config.DESK_TOOL_NAME, watchlist=config.DESK_TICKERS,
        ))


agent = QuoteLineAgent()

if __name__ == "__main__":
    server = AgentServer(port=config.PORT)
    server.register(agent)
    server.register(StockPlanAgent())
    server.run()
