# State machine

**Problem.** "Don't progress to X until Y." Put that in a prompt and the model will, sooner
or later, deal the cards before the bet is placed.

**Snippet** ([snippet.py](snippet.py), a minimal blackjack table):

```python
ctx = agent.define_contexts().add_context("default")
ctx.add_step("bet").set_text("Ask how many chips the caller bets, then call place_bet.") \
    .set_functions(["place_bet"]).set_valid_steps([])
ctx.add_step("play").set_text("Call deal, then tell the caller their two cards.") \
    .set_functions(["deal"]).set_valid_steps([])

def place_bet(args, raw_data):
    chips = (raw_data.get("global_data") or {}).get("chips", 0)
    amount = args.get("amount")
    if type(amount) is not int or not 1 <= amount <= chips:
        return FunctionResult(f"Bets are 1 to {chips} chips. Ask again.")
    return (FunctionResult(f"{amount} chips on the table.")
            .update_global_data({"bet": amount, "chips": chips - amount})
            .swml_change_step("play"))
```

**Why it holds.** `set_valid_steps([])` means the model gets no `next_step` tool, so it has no
way to change step by itself. `set_functions(["place_bet"])` means `deal` doesn't exist in
`bet`. The only transition to `play` is the `swml_change_step` (wire name `change_step`) in
the valid-bet branch of a handler, and the chip balance it checks comes from `global_data`,
not from the model. `deal` also re-checks for a bet and sends the call back if there isn't one.
Call `set_functions` on every step: a step without it inherits the previous step's tools.

**Test.** `pytest patterns/state-machine`: invalid bets never change step, and the dumped
SWML shows `bet` has `valid_steps == []` and no `deal` tool.

**Used by.** #8, #11, #12.
