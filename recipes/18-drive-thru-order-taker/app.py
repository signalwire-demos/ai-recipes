"""Drive-thru order taker: the menu, the stock and the total live in code, not in the prompt.

Governance point: every order line goes through rules.check_line, which validates it against
data/menu.json and the live stock in data/stock.json. A stock-out moves the call to
`substitute_offer`, whose only tools accept a substitute the handler offered or decline.
The model never adds up prices: finish_order computes the total in integer cents.
"""
import json

from signalwire import AgentBase, FunctionResult

import config
from rules import check_line, key_of, label, load, money, substitutes, totals, unit_cents

LINE = {"type": "integer", "description": "Order line number, starting at 1"}
ITEM_PARAMS = {
    "item": {"type": "string", "description": "Menu item id, e.g. cheeseburger"},
    "size": {"type": "string", "description": "Size, e.g. large. Omit if the item has one size"},
    "quantity": {"type": "integer", "description": "How many. Default 1"},
    "modifiers": {"type": "array", "items": {"type": "string"}, "description": "e.g. [\"no onions\"]"},
    "side": {"type": "string", "description": "Combos only: the side item id"},
    "drink": {"type": "string", "description": "Combos only: the drink item id"},
}
NO_PARAMS = {"type": "object", "properties": {}}


def order_of(raw_data) -> list:
    return list((raw_data.get("global_data") or {}).get("order") or [])


class DriveThruAgent(AgentBase):
    def __init__(self, **kwargs):
        super().__init__(name="drive-thru", route=config.ROUTE, port=config.PORT, **kwargs)
        self.menu = load(config.MENU_FILE)
        self.add_language("English", config.LANGUAGE_CODE, config.VOICE)
        self.prompt_add_section(
            "Role",
            f"You take drive-thru orders for {config.BUSINESS_NAME}. Keep every reply short. "
            "Never quote, estimate or add up prices: prices and totals come only from tool results.",
        )
        self.prompt_add_section("Menu (item id: sizes; modifiers)", bullets=[
            f"{k}: {', '.join(v['sizes'])}; {', '.join(v['modifiers']) or 'none'}"
            + (f"; side from {v['combo']['side']}, drink from {v['combo']['drink']}" if "combo" in v else "")
            for k, v in self.menu.items()
        ])
        self.set_global_data({"order": []})

        ctx = self.define_contexts().add_context("default")
        ctx.add_step("take_order") \
            .set_text("Take the order. Call add_item for each item. Use modify_item or remove_item to "
                      "change a line. When the caller says that's everything, call finish_order.") \
            .set_functions(["add_item", "modify_item", "remove_item", "finish_order"]) \
            .set_valid_steps([])
        ctx.add_step("substitute_offer") \
            .set_text("Tell the caller we're out of ${global_data.pending.missing} and offer "
                      "${global_data.pending.offer}. If they pick one, call accept_substitute. "
                      "If they want none of them, call decline_substitute.") \
            .set_functions(["accept_substitute", "decline_substitute"]) \
            .set_valid_steps([])
        ctx.add_step("confirm") \
            .set_text("Read the order back exactly as written: ${global_data.readback}. Subtotal "
                      "${global_data.subtotal}, tax ${global_data.tax}, total ${global_data.total}. "
                      "Ask if that's right. Yes: call confirm_order. A change: call change_order.") \
            .set_functions(["confirm_order", "change_order"]) \
            .set_valid_steps([])
        ctx.add_step("done") \
            .set_text("Give the order number ${global_data.order_number} and the total, and ask them "
                      "to pull forward to the window.") \
            .set_functions([]) \
            .set_valid_steps([]) \
            .set_end(True)

    def _place(self, args, raw_data, replace=None, back=None):
        """Validate one line and add it (or replace line `replace`). Stock-outs jump."""
        order = order_of(raw_data)
        line, error, missing = check_line(self.menu, args)
        if missing:
            name = self.menu.get(missing, {}).get("name", missing)
            options = substitutes(missing)
            if options:
                pending = {"line": line, "missing": name, "token": missing, "options": options,
                           "offer": " or ".join(options).replace("_", " "), "replace": replace}
                return FunctionResult(f"We're out of {name}.") \
                    .update_global_data({"pending": pending}).swml_change_step("substitute_offer")
            error = f"We're out of {name} and have no substitute. Ask for something else."
        if error:
            result = FunctionResult(error)
        else:
            if replace is None:
                order.append(line)
            else:
                order[replace] = line
            n = len(order) if replace is None else replace + 1
            price = money(unit_cents(self.menu, line) * line["quantity"])
            result = FunctionResult(f"Line {n}: {label(self.menu, line)}, {price}. Ask what else.") \
                .update_global_data({"order": order})
        return result.swml_change_step(back) if back else result

    # --- take_order -------------------------------------------------------------------
    @AgentBase.tool(name="add_item", description="Add one item to the order.",
                    parameters={"type": "object", "properties": ITEM_PARAMS, "required": ["item"]})
    def add_item(self, args, raw_data):
        return self._place(args, raw_data)

    @AgentBase.tool(name="modify_item", description="Change the size, quantity or modifiers of a line.",
                    parameters={"type": "object", "required": ["line"], "properties": {
                        "line": LINE, "size": ITEM_PARAMS["size"], "quantity": ITEM_PARAMS["quantity"],
                        "add_modifiers": ITEM_PARAMS["modifiers"], "remove_modifiers": ITEM_PARAMS["modifiers"]}})
    def modify_item(self, args, raw_data):
        order, idx = order_of(raw_data), int(args.get("line") or 0) - 1
        if not 0 <= idx < len(order):
            return FunctionResult(f"There is no line {args.get('line')}. The order has {len(order)} lines.")
        old = order[idx]
        drop = {str(m).strip().lower() for m in args.get("remove_modifiers") or []}
        new = dict(old, size=args.get("size") or old["size"], quantity=args.get("quantity") or old["quantity"],
                   modifiers=[m for m in old["modifiers"] if m not in drop] + list(args.get("add_modifiers") or []))
        return self._place(new, raw_data, replace=idx)

    @AgentBase.tool(name="remove_item", description="Remove a line from the order.",
                    parameters={"type": "object", "properties": {"line": LINE}, "required": ["line"]})
    def remove_item(self, args, raw_data):
        order, idx = order_of(raw_data), int(args.get("line") or 0) - 1
        if not 0 <= idx < len(order):
            return FunctionResult(f"There is no line {args.get('line')}.")
        gone = order.pop(idx)
        return FunctionResult(f"Removed {label(self.menu, gone)}.").update_global_data({"order": order})

    @AgentBase.tool(name="finish_order", description="The caller has finished ordering.", parameters=NO_PARAMS)
    def finish_order(self, args, raw_data):
        order = order_of(raw_data)
        if not order:
            return FunctionResult("Nothing has been ordered yet. Ask what they'd like.")
        readback = "; ".join(f"{i}. {label(self.menu, ln)}" for i, ln in enumerate(order, 1))
        return FunctionResult("Read the order back.") \
            .update_global_data({"readback": readback, **totals(self.menu, order)}) \
            .swml_change_step("confirm")

    # --- substitute_offer ---------------------------------------------------------------
    @AgentBase.tool(name="accept_substitute", description="The caller picked one of the offered substitutes.",
                    parameters={"type": "object", "required": ["choice"],
                                "properties": {"choice": {"type": "string", "description": "Substitute id"}}})
    def accept_substitute(self, args, raw_data):
        pending = (raw_data.get("global_data") or {}).get("pending") or {}
        options = pending.get("options", [])
        choice = next((o for o in options if key_of(o) == key_of(args.get("choice"))), None)
        if not choice:
            return FunctionResult(f"{args.get('choice')} wasn't offered. Offer: {', '.join(options)}.")
        line, token = dict(pending["line"]), pending["token"]
        for slot in ("item", "side", "drink"):
            if line.get(slot) == token:
                line[slot] = key_of(choice)
        line["modifiers"] = [choice if m == token else m for m in line["modifiers"]]
        return self._place(line, raw_data, replace=pending.get("replace"), back="take_order")

    @AgentBase.tool(name="decline_substitute", description="The caller doesn't want any substitute.",
                    parameters=NO_PARAMS)
    def decline_substitute(self, args, raw_data):
        return FunctionResult("Nothing added. Ask what else they'd like.") \
            .remove_global_data(["pending"]).swml_change_step("take_order")

    # --- confirm ------------------------------------------------------------------------
    @AgentBase.tool(name="confirm_order", description="The caller confirmed the order as read back.",
                    parameters=NO_PARAMS)
    def confirm_order(self, args, raw_data):
        order, path = order_of(raw_data), config.ORDERS_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        number = 100 + (len(path.read_text().splitlines()) if path.exists() else 0)
        record = {"order_number": number, "call_id": raw_data.get("call_id"), "lines": order,
                  **totals(self.menu, order)}
        with path.open("a") as f:
            f.write(json.dumps(record) + "\n")
        return FunctionResult(f"Order {number} placed. Total {record['total']}.") \
            .update_global_data({"order_number": number}).swml_change_step("done")

    @AgentBase.tool(name="change_order", description="The caller wants to change the order.",
                    parameters=NO_PARAMS)
    def change_order(self, args, raw_data):
        return FunctionResult("Ask what they'd like to change.").swml_change_step("take_order")


agent = DriveThruAgent()

if __name__ == "__main__":
    agent.run()
