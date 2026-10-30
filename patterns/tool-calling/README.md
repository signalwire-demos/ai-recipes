# Tool calling

**Problem.** The model needs a fact it can't know (an order status), and later steps need
that fact too. Asking the model to remember it in conversation is fragile.

**Snippet** ([snippet.py](snippet.py)):

```python
@agent.tool(name="lookup_order", description="Look up the status of one order by its order number.",
            parameters={"type": "object",
                        "properties": {"order_id": {"type": "string", "description": "Order number, e.g. A-0101"}},
                        "required": ["order_id"]})
def lookup_order(args, raw_data):
    order_id = str(args.get("order_id", "")).strip().upper().replace(" ", "-")
    status = ORDERS.get(order_id)
    if status is None:
        return FunctionResult(f"There is no order {order_id}. Ask the caller to read it again.")
    return (FunctionResult(f"Order {order_id} is {status}.")
            .update_global_data({"order_id": order_id, "order_status": status}))
```

**Why it holds.** The JSON Schema types and requires the argument, so the platform sends a
string every time. The handler normalizes it before the lookup. The response tells the model
what to say, and `update_global_data` (wire name `set_global_data`) stores the fact where
`${global_data.order_status}` in a later step's text and every later handler can read it. The
not-found branch stores nothing, so a bad lookup can't leak into later steps.

**Test.** `pytest patterns/tool-calling`: the handler returns the expected actions, and the
dumped SWML declares the tool with a typed, required `order_id`.

**Used by.** #1 and, in some form, every recipe.
