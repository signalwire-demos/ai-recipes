"""AI Bank Balance Line: progressive trust.

Governance point: the account tools do not exist in the model's world until a
handler unlocks them. `verify_identity` exposes one tool and no navigation
(valid_steps=[]). Only the verify_identity handler can open `account_menu`, and
the third failed attempt sends the call to `escalate` whatever the caller says.
"""
import re
from datetime import datetime

from signalwire import AgentBase, FunctionResult

import config
import crm

DOB_FORMATS = ["%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y", "%B %d %Y", "%b %d %Y", "%d %B %Y"]


def normalize_dob(text: str) -> str | None:
    """Turn the caller's date of birth into YYYY-MM-DD, or None if it doesn't parse."""
    cleaned = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", str(text)).replace(",", " ")
    cleaned = " ".join(cleaned.split())
    for fmt in DOB_FORMATS:
        try:
            return datetime.strptime(cleaned, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def money(amount: float) -> str:
    return f"${abs(amount):,.2f}"


class BankBalanceAgent(AgentBase):
    def __init__(self, **kwargs):
        super().__init__(name="bank-balance-line", route=config.ROUTE, port=config.PORT, **kwargs)
        self.add_language("English", config.LANGUAGE_CODE, config.VOICE)
        self.prompt_add_section(
            "Role",
            f"You answer the phone for {config.BANK_NAME}. Be brief, calm and professional. "
            "Never read out a full account number.",
        )

        ctx = self.define_contexts().add_context("default")
        ctx.add_step("verify_identity") \
            .set_text(
                "Greet the caller. Ask for their account number and date of birth, then call "
                "verify_identity. You cannot discuss balances, transactions or disputes yet."
            ) \
            .set_functions(["verify_identity"]) \
            .set_valid_steps([])  # no next_step tool: only the handler can open the account menu
        ctx.add_step("account_menu") \
            .set_text(
                "The caller is verified as ${global_data.customer.name}. Help with their balance, "
                "recent transactions, or disputing a transaction. When they are done, move to wrap_up."
            ) \
            .set_functions(["get_balance", "list_transactions", "open_dispute"]) \
            .set_valid_steps(["wrap_up"])
        ctx.add_step("wrap_up") \
            .set_text("Thank the caller and say goodbye.") \
            .set_functions([]) \
            .set_valid_steps([])
        ctx.add_step("escalate") \
            .set_text(
                "Tell the caller, kindly, that you could not verify their identity on this call "
                "and that you will hand them over. Then call escalate_call."
            ) \
            .set_functions(["escalate_call"]) \
            .set_valid_steps([])

    # --- verify_identity step ----------------------------------------------

    @AgentBase.tool(
        name="verify_identity",
        description="Check the caller's account number and date of birth.",
        parameters={
            "type": "object",
            "properties": {
                "account_number": {"type": "string", "description": "The account number, digits only"},
                "date_of_birth": {"type": "string", "description": "Date of birth as the caller said it"},
            },
            "required": ["account_number", "date_of_birth"],
        },
    )
    def verify_identity(self, args, raw_data):
        number = re.sub(r"\D", "", str(args.get("account_number", "")))
        dob = normalize_dob(args.get("date_of_birth", ""))
        acct = crm.verify(number, dob) if number and dob else None
        if acct:
            return (
                FunctionResult(f"Verified. Greet {acct['name'].split()[0]} by name and ask what they need.")
                .update_global_data({"verified": True, "customer": {"id": acct["id"], "name": acct["name"]}})
                .swml_change_step("account_menu")
            )

        failures = int((raw_data.get("global_data") or {}).get("verify_failures", 0)) + 1
        result = FunctionResult().update_global_data({"verify_failures": failures})
        if failures >= config.MAX_VERIFY_ATTEMPTS:
            result.set_response("Those details still don't match. Stop asking for them.")
            return result.swml_change_step("escalate")
        # Don't say which factor was wrong: that would help someone guessing.
        result.set_response("Those details don't match our records. Ask the caller to check both and try again.")
        return result

    # --- account_menu step ---------------------------------------------------

    def _account(self, raw_data) -> dict | None:
        """Defense in depth: handlers re-check verification instead of trusting the step."""
        gd = raw_data.get("global_data") or {}
        return crm.get(gd["customer"]["id"]) if gd.get("verified") and gd.get("customer") else None

    @AgentBase.tool(
        name="get_balance",
        description="Get the verified caller's available and current balance.",
        parameters={"type": "object", "properties": {}},
    )
    def get_balance(self, args, raw_data):
        acct = self._account(raw_data)
        if not acct:
            return FunctionResult("The caller is not verified.")
        return FunctionResult(
            f"Available balance {money(acct['available_balance'])}, "
            f"current balance {money(acct['current_balance'])}."
        )

    @AgentBase.tool(
        name="list_transactions",
        description="List the verified caller's most recent transactions, newest first.",
        parameters={
            "type": "object",
            "properties": {"count": {"type": "integer", "description": "How many to list"}},
        },
    )
    def list_transactions(self, args, raw_data):
        acct = self._account(raw_data)
        if not acct:
            return FunctionResult("The caller is not verified.")
        try:
            count = int(args.get("count") or 3)
        except (TypeError, ValueError):
            count = 3
        count = max(1, min(count, config.MAX_TRANSACTIONS))
        lines = [
            f"{t['id']}: {t['date']}, {t['description']}, "
            f"{'credit' if t['amount'] > 0 else 'debit'} of {money(t['amount'])}"
            for t in acct["transactions"][:count]
        ]
        return FunctionResult("Recent transactions: " + "; ".join(lines) + ".")

    @AgentBase.tool(
        name="open_dispute",
        description="Open a dispute on one of the verified caller's transactions.",
        parameters={
            "type": "object",
            "properties": {
                "transaction_id": {"type": "string", "description": "Transaction id, e.g. T-9005"},
                "reason": {"type": "string", "description": "Why the caller disputes it"},
            },
            "required": ["transaction_id", "reason"],
        },
    )
    def open_dispute(self, args, raw_data):
        acct = self._account(raw_data)
        if not acct:
            return FunctionResult("The caller is not verified.")
        txn_id = str(args.get("transaction_id", "")).strip().upper()
        if txn_id not in {t["id"] for t in acct["transactions"]}:
            return FunctionResult("That transaction isn't on this account. List transactions and ask which one.")
        ref = crm.open_dispute(acct["id"], txn_id, str(args.get("reason", "")).strip())
        return FunctionResult(f"Dispute {ref} opened on {txn_id}. A specialist reviews it within 10 business days.")

    # --- escalate step -------------------------------------------------------

    @AgentBase.tool(
        name="escalate_call",
        description="Hand the unverified caller to a specialist, or end the call politely.",
        parameters={"type": "object", "properties": {}},
    )
    def escalate_call(self, args, raw_data):
        if config.ESCALATION_NUMBER:
            return FunctionResult("Connecting you now.").connect(
                config.ESCALATION_NUMBER, final=True, from_addr=config.FROM_NUMBER
            )
        return (
            FunctionResult("No specialist line is configured.")
            .say("Please call back from a phone on file, or visit a branch with photo ID. Goodbye.")
            .hangup()
        )


agent = BankBalanceAgent()

if __name__ == "__main__":
    agent.run()
