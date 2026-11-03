"""Front desk receptionist: one phone line, four personas that can't share tools.

Governance point: sales, support and billing are isolated contexts. Each step
whitelists only its own department's tools with set_functions, so issue_refund
does not exist anywhere outside billing. valid_contexts is the routing graph:
the model's change_context tool only offers the routes config.DEPARTMENTS allows.
The refund amount comes from the invoice record, never from the model, and only an
invoice the caller unlocked with its billing ZIP can be refunded.
"""
import json
import re
import time

from signalwire import AgentBase, FunctionResult

import config


def load(path) -> dict:
    return json.loads(path.read_text())


def append_jsonl(path, row: dict) -> None:
    with path.open("a") as f:
        f.write(json.dumps(row) + "\n")


def invoice_key(spoken) -> str:
    """Normalize an invoice number the way speech recognition hands it over.

    The live call heard "INV-1001" as "Inv1001"; "inv 1001" and "1001" are just as likely.
    Keep letters and digits only, then put the dash back: INV1001 -> INV-1001.
    """
    raw = re.sub(r"[^A-Z0-9]", "", str(spoken or "").upper())
    m = re.fullmatch(r"(?:INV)?(\d+)", raw)
    return f"INV-{m[1]}" if m else raw


def refunded_ids() -> set:
    if not config.REFUNDS_FILE.exists():
        return set()
    return {json.loads(line)["invoice_id"] for line in config.REFUNDS_FILE.read_text().splitlines() if line}


# Tool-schema enums come from the same files the handlers read, built once at import so the
# decorators below can use them. The invoice pattern is the canonical form the model should
# send; invoice_key() still normalizes whatever speech recognition hands over.
PLANS = list(load(config.PLANS_FILE))
SERVICES = list(load(config.STATUS_FILE))
INVOICE_PATTERN = "^(INV-)?[0-9]{4}$"


class FrontDeskAgent(AgentBase):
    def __init__(self, **kwargs):
        super().__init__(name="front-desk", route=config.ROUTE, port=config.PORT, **kwargs)
        self.prompt_add_section(
            "Instructions",
            f"You answer the phone for {config.BUSINESS_NAME}. Follow the newest Role. "
            "Keep answers short. Never invent prices, outages or invoice amounts.",
        )
        self.add_internal_filler("change_context", config.LANGUAGE_CODE, ["One moment, please."])

        contexts = self.define_contexts()
        for dept in config.DEPARTMENTS:
            language = f"English-{dept['persona']}"
            self.add_language(language, config.LANGUAGE_CODE, dept["voice"])
            ctx = contexts.add_context(dept["name"]).set_isolated(True)
            ctx.add_section("Role", dept["role"])
            ctx.add_section("Voice", f"Use the {language} language.")
            ctx.add_enter_filler(config.LANGUAGE_CODE, [dept["enter_filler"]])
            ctx.set_valid_contexts(dept["routes"])
            ctx.add_step("main") \
                .set_text(
                    f"Introduce yourself as {dept['persona']} and help the caller. "
                    "If they need another department, use change_context."
                ) \
                .set_functions(dept["tools"]) \
                .set_valid_contexts(dept["routes"]) \
                .set_valid_steps([])

    # --- sales ---------------------------------------------------------------
    @AgentBase.tool(
        name="get_plan_price",
        description="Get the monthly price and speed of an internet plan.",
        parameters={"type": "object",
                    "properties": {"plan": {
                        "type": "string", "enum": PLANS,
                        "description": "Which plan the caller is asking about. Ask if not provided."}},
                    "required": ["plan"]},
    )
    def get_plan_price(self, args, raw_data):
        plans = load(config.PLANS_FILE)
        plan = str(args.get("plan", "")).strip().lower()
        if plan not in plans:
            return FunctionResult(f"We have these plans: {', '.join(plans)}. Ask which one.")
        p = plans[plan]
        return FunctionResult(f"The {plan} plan is {p['speed']} for ${p['monthly']:.2f} a month.")

    # --- support -------------------------------------------------------------
    @AgentBase.tool(
        name="check_service_status",
        description="Check whether a service has a known outage.",
        parameters={"type": "object",
                    "properties": {"service": {
                        "type": "string", "enum": SERVICES,
                        "description": "Which service the caller is asking about. Ask if not provided."}},
                    "required": ["service"]},
    )
    def check_service_status(self, args, raw_data):
        status = load(config.STATUS_FILE)
        service = str(args.get("service", "")).strip().lower()
        if service not in status:
            return FunctionResult(f"I can check {', '.join(status)}. Ask which one.")
        s = status[service]
        if s["status"] == "ok":
            return FunctionResult(f"There are no known problems with {service}.")
        return FunctionResult(f"{service.capitalize()} is {s['status']}. {s['note']}")

    @AgentBase.tool(
        name="open_ticket",
        description="Open a support ticket with a one-sentence summary of the problem.",
        parameters={"type": "object",
                    "properties": {"summary": {
                        "type": "string",
                        "description": "One-sentence summary of the problem in the caller's own words. "
                                       "Ask the caller to describe the problem if they have not."}},
                    "required": ["summary"]},
    )
    def open_ticket(self, args, raw_data):
        summary = str(args.get("summary", "")).strip()
        if not summary:
            return FunctionResult("Ask the caller to describe the problem first.")
        ticket_id = f"T-{int(time.time()) % 100000:05d}"
        append_jsonl(config.TICKETS_FILE, {"ticket_id": ticket_id, "summary": summary,
                                           "call_id": raw_data.get("call_id")})
        return FunctionResult(f"Ticket {ticket_id} is open. Read the number back to the caller.")

    # --- billing -------------------------------------------------------------
    # An invoice number is sequential and guessable, so it is never enough on its own: the
    # billing ZIP on the record is the second factor. The match is remembered in global_data,
    # which the model can't write, and issue_refund refunds only that invoice.
    @AgentBase.tool(
        name="get_invoice",
        description="Look up an invoice by its number (for example INV-1001) and the billing ZIP code.",
        parameters={"type": "object",
                    "properties": {"invoice_id": {
                        "type": "string", "pattern": INVOICE_PATTERN,
                        "description": "The caller's invoice number, normalized to INV-#### (for example "
                                       "INV-1001). Ask for it if not provided."},
                                   "zip_code": {
                        "type": "string", "pattern": "^[0-9]{5}$",
                        "description": "The 5-digit billing ZIP code on the account. Ask for it if not "
                                       "provided; never guess it."}},
                    "required": ["invoice_id", "zip_code"]},
    )
    def get_invoice(self, args, raw_data):
        failures = int((raw_data.get("global_data") or {}).get("billing_failures", 0))
        if failures >= config.MAX_LOOKUP_FAILURES:
            return FunctionResult("Too many failed lookups on this call. Don't look up invoices again; "
                                  "offer to take the caller back to the front desk.")
        invoice_id = invoice_key(args.get("invoice_id"))
        zip_code = re.sub(r"\D", "", str(args.get("zip_code") or ""))
        if not str(args.get("invoice_id") or "").strip() or not zip_code:   # nothing to check yet: not a miss
            return FunctionResult("Ask the caller for the invoice number and the billing ZIP code.")
        inv = load(config.INVOICES_FILE).get(invoice_id)
        if not inv or not zip_code or zip_code != inv["zip"]:   # one answer for both: nothing to probe
            return FunctionResult("That invoice number and ZIP code don't match. Ask the caller to "
                                  "check both.").update_global_data({"billing_failures": failures + 1})
        status = "refunded" if invoice_id in refunded_ids() else inv["status"]
        return FunctionResult(f"Invoice {invoice_id} is ${inv['amount']:.2f}, status {status}.") \
            .update_global_data({"billing_verified": invoice_id})

    @AgentBase.tool(
        name="issue_refund",
        description="Refund the invoice found with get_invoice, in full. Only call after the caller confirms.",
        parameters={"type": "object", "properties": {}, "required": []},
    )
    def issue_refund(self, args, raw_data):
        invoice_id = (raw_data.get("global_data") or {}).get("billing_verified")  # never from the model
        inv = load(config.INVOICES_FILE).get(invoice_id) if invoice_id else None
        if not inv:
            return FunctionResult("Look the invoice up with get_invoice first, so no refund was made.")
        if inv["status"] == "refunded" or invoice_id in refunded_ids():
            return FunctionResult(f"Invoice {invoice_id} has already been refunded.")
        amount = inv["amount"]  # from the record, never from the model
        if amount > config.REFUND_LIMIT:
            return FunctionResult(
                f"Refunds over ${config.REFUND_LIMIT:.0f} need a billing manager. "
                "Tell the caller someone will call them back within one business day."
            )
        append_jsonl(config.REFUNDS_FILE, {"invoice_id": invoice_id, "amount": amount,
                                           "call_id": raw_data.get("call_id")})
        return FunctionResult(f"Refunded ${amount:.2f} on invoice {invoice_id}. "
                              "It reaches the card in 3 to 5 business days.")


agent = FrontDeskAgent()

if __name__ == "__main__":
    agent.run()
