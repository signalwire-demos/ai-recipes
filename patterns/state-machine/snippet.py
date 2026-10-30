"""State machine: "don't deal until there's a valid bet."

Two steps, both with valid_steps=[], so the model has no next_step tool. The
only way from `bet` to `play` is place_bet's swml_change_step, and place_bet
only takes it for a bet the caller can cover. A minimal blackjack table.
"""
import random

from signalwire import AgentBase, FunctionResult

RANKS = "ace 2 3 4 5 6 7 8 9 10 jack queen king".split()

agent = AgentBase(name="state-machine", route="/")
agent.add_language("English", "en-US", "rime.spore")
agent.prompt_add_section("Role", "You are a blackjack dealer. Keep it short.")
agent.set_global_data({"chips": 100})

ctx = agent.define_contexts().add_context("default")
ctx.add_step("bet").set_text("Ask how many chips the caller bets, then call place_bet.") \
    .set_functions(["place_bet"]).set_valid_steps([])      # X is unreachable from here...
ctx.add_step("play").set_text("Call deal, then tell the caller their two cards.") \
    .set_functions(["deal"]).set_valid_steps([])           # ...except through the handler


@agent.tool(name="place_bet", description="Place the caller's bet in chips.",
            parameters={"type": "object", "properties": {"amount": {"type": "integer"}}, "required": ["amount"]})
def place_bet(args, raw_data):
    chips = (raw_data.get("global_data") or {}).get("chips", 0)
    amount = args.get("amount")
    if type(amount) is not int or not 1 <= amount <= chips:
        return FunctionResult(f"Bets are 1 to {chips} chips. Ask again.")      # Y not met: stay put
    return (FunctionResult(f"{amount} chips on the table.")
            .update_global_data({"bet": amount, "chips": chips - amount})
            .swml_change_step("play"))                                          # Y met: open X


@agent.tool(name="deal", description="Deal the caller's first two cards.",
            parameters={"type": "object", "properties": {}})
def deal(args, raw_data):
    bet = (raw_data.get("global_data") or {}).get("bet")
    if not bet:                                     # belt and braces: never deal without a bet
        return FunctionResult("There is no bet yet.").swml_change_step("bet")
    a, b = random.choice(RANKS), random.choice(RANKS)
    return FunctionResult(f"The caller has {a} and {b}, with {bet} chips bet.")


if __name__ == "__main__":
    agent.run()
