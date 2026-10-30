"""AI Order Status Line: verify-then-expand data projection.

Governance point: the handler loads the full order record into global_data, but
the step text projects only a curated slice (config.CURATED_FIELDS). Risk flags,
refund history and the refund thresholds are read only inside request_refund,
which narrates an outcome ("a credit is on its way" or "connecting you") and
never the rule that decided it. The verification step is the same shape as
recipe 08: one tool, valid_steps=[], and the third failure jumps to escalate.
"""
import re

from signalwire import AgentBase, FunctionResult

import config
import crm


def items_text(order: dict) -> str:
    return ", ".join(f"{i['qty']} x {i['name']}" for i in order["items"])


def curated_step_text() -> str:
    """The only order facts the model sees: ${global_data.order.<field>} for curated fields."""
    facts = " ".join(f"{label}: ${{global_data.order.{field}}}." for field, label in config.CURATED_FIELDS.items())
    return (f"The caller is verified. Their order: {facts} Answer questions about this order only. "
            "If they want a refund, call request_refund. When they are done, move to wrap_up.")


def refund_decision(order: dict) -> bool:
    """True = auto-credit. The rule lives here, server side, and is never described to the model."""
    return (not order.get("risk_flag")
            and order.get("total", 0) <= config.AUTO_CREDIT_LIMIT
            and order.get("prior_refunds", 0) <= config.MAX_PRIOR_REFUNDS
            and order.get("status") in config.REFUNDABLE_STATUSES)


class OrderStatusAgent(AgentBase):
    def __init__(self, **kwargs):
        super().__init__(name="order-status-line", route=config.ROUTE, port=config.PORT, **kwargs)
        self.add_language("English", config.LANGUAGE_CODE, config.VOICE)
        self.prompt_add_section(
            "Role",
            f"You answer the order line for {config.STORE_NAME}. Be brief and friendly. "
            "You only know what the current step tells you about an order.",
        )

        ctx = self.define_contexts().add_context("default")
        ctx.add_step("verify_identity") \
            .set_text("Greet the caller. Ask for their order number and the ZIP code it ships to, then "
                      "call verify_identity. Don't discuss any order before that.") \
            .set_functions(["verify_identity"]) \
            .set_valid_steps([])  # no next_step tool: only the handler opens the order
        ctx.add_step("order_status") \
            .set_text(curated_step_text()) \
            .set_functions(["request_refund"]) \
            .set_valid_steps(["wrap_up"])
        ctx.add_step("wrap_up") \
            .set_text("Thank the caller and say goodbye.") \
            .set_functions([]) \
            .set_valid_steps([])
        ctx.add_step("escalate") \
            .set_text("Tell the caller, kindly, that you are handing them to a specialist. "
                      "Then call escalate_call.") \
            .set_functions(["escalate_call"]) \
            .set_valid_steps([])

    # --- verify_identity step (same shape as recipe 08) ----------------------

    @AgentBase.tool(
        name="verify_identity",
        description="Check the caller's order number and shipping ZIP code.",
        parameters={
            "type": "object",
            "properties": {
                "order_number": {"type": "string", "description": "The order number, digits only"},
                "postal_code": {"type": "string", "description": "Five-digit shipping ZIP code"},
            },
            "required": ["order_number", "postal_code"],
        },
    )
    def verify_identity(self, args, raw_data):
        number = re.sub(r"\D", "", str(args.get("order_number", "")))
        postal = re.sub(r"\D", "", str(args.get("postal_code", "")))
        order = crm.verify(number, postal) if number and postal else None
        if order:
            full = {**order, "items_text": items_text(order)}  # the full record, hidden by default
            return (
                FunctionResult(f"Verified. Greet {order['customer_name'].split()[0]} and ask what they "
                               "want to know about the order.")
                .update_global_data({"verified": True, "order": full})
                .swml_change_step("order_status")
            )

        failures = int((raw_data.get("global_data") or {}).get("verify_failures", 0)) + 1
        result = FunctionResult().update_global_data({"verify_failures": failures})
        if failures >= config.MAX_VERIFY_ATTEMPTS:
            result.set_response("Those details still don't match. Stop asking for them.")
            return result.swml_change_step("escalate")
        result.set_response("Those details don't match an order. Ask the caller to check both and try again.")
        return result

    # --- order_status step ---------------------------------------------------

    @AgentBase.tool(
        name="request_refund",
        description="Ask for a refund on the caller's verified order.",
        parameters={
            "type": "object",
            "properties": {"reason": {"type": "string", "description": "Why the caller wants a refund"}},
            "required": ["reason"],
        },
    )
    def request_refund(self, args, raw_data):
        gd = raw_data.get("global_data") or {}
        order = gd.get("order")
        if not gd.get("verified") or not order:
            return FunctionResult("The caller is not verified.")
        if refund_decision(order):
            ref = crm.issue_credit(order["id"], order["total"], str(args.get("reason", "")).strip())
            return FunctionResult(
                f"A credit of ${order['total']:,.2f} has been issued to the original payment method, "
                f"reference {ref}. Tell the caller it shows up in three to five business days."
            ).update_global_data({"refund": {"outcome": "credited", "ref": ref}})
        return (
            FunctionResult("This refund needs a specialist. Tell the caller you're connecting them; "
                           "don't guess at why.")
            .update_global_data({"refund": {"outcome": "transferred"}})
            .swml_change_step("escalate")
        )

    # --- escalate step -------------------------------------------------------

    @AgentBase.tool(
        name="escalate_call",
        description="Hand the caller to a specialist, or end the call politely.",
        parameters={"type": "object", "properties": {}},
    )
    def escalate_call(self, args, raw_data):
        if config.ESCALATION_NUMBER:
            return FunctionResult("Connecting you now.").connect(
                config.ESCALATION_NUMBER, final=True, from_addr=config.FROM_NUMBER
            )
        return (
            FunctionResult("No specialist line is configured.")
            .say("A specialist will email you within one business day. Goodbye.")
            .hangup()
        )


agent = OrderStatusAgent()

if __name__ == "__main__":
    agent.run()
