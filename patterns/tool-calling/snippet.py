"""Tool calling: the smallest SWAIG function.

Typed args in, a FunctionResult out that both tells the model what to say and
stores a fact in global_data, where later steps and handlers can read it.
"""
from signalwire import AgentBase, FunctionResult

ORDERS = {"A-0101": "shipped", "A-0102": "being packed"}  # stand-in for your system of record

agent = AgentBase(name="tool-calling", route="/")
agent.add_language("English", "en-US", "rime.spore")
agent.prompt_add_section("Role", "Ask for the caller's order number, then call lookup_order.")


@agent.tool(
    name="lookup_order",
    description="Look up the status of one order by its order number.",
    parameters={"type": "object",
                "properties": {"order_id": {"type": "string", "description": "Order number, e.g. A-0101"}},
                "required": ["order_id"]},
)
def lookup_order(args, raw_data):
    order_id = str(args.get("order_id", "")).strip().upper().replace(" ", "-")
    status = ORDERS.get(order_id)
    if status is None:
        return FunctionResult(f"There is no order {order_id}. Ask the caller to read it again.")
    return (FunctionResult(f"Order {order_id} is {status}.")
            .update_global_data({"order_id": order_id, "order_status": status}))


if __name__ == "__main__":
    agent.run()
