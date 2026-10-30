"""Bilingual support line: English and Spanish from one agent.

Governance point: language is configuration, not code. Each language is one
add_language() call (its own voice and fillers, from config.LANGUAGES). Tool
handlers never write sentences: they return language-neutral JSON, and the model
voices it in whatever language the caller is using, so switching mid-call needs
no second code path. Steps scope the tools: `identify` has only lookup_account and
no navigation, so only its handler can open the account tools in `help`.
"""
import json

from signalwire import AgentBase, FunctionResult

import config

PUBLIC_FIELDS = ("first_name", "plan")  # the model never sees risk flags or billing notes


def load_db() -> dict:
    return json.loads(config.ACCOUNTS_FILE.read_text())


def data(payload: dict) -> FunctionResult:
    """A tool result is data, never prose: the model voices it in the caller's language."""
    return FunctionResult(json.dumps(payload, sort_keys=True))


class BilingualSupportAgent(AgentBase):
    def __init__(self, **kwargs):
        super().__init__(name="bilingual-support", route=config.ROUTE, port=config.PORT, **kwargs)
        self.db = load_db()

        for lang in config.LANGUAGES:
            self.add_language(lang["name"], lang["code"], lang["voice"],
                              speech_fillers=lang["speech_fillers"],
                              function_fillers=lang["function_fillers"])
            self.add_internal_filler("next_step", lang["code"], lang["step_fillers"])
        self.set_params({"languages_enabled": True})

        names = " and ".join(lang["name"] for lang in config.LANGUAGES)
        self.prompt_add_section(
            "Role",
            f"You answer the support line for {config.BUSINESS_NAME}, an internet provider. "
            "Be brief and friendly.",
        )
        self.prompt_add_section("Language", bullets=[
            f"You speak {names}. Open in {config.LANGUAGES[0]['name']} and offer the other "
            "language in one short phrase.",
            "Always reply in the language the caller last spoke. If they switch, switch with them "
            "and keep going; do not restart or repeat questions they already answered.",
            "Tool results are JSON data. Never read keys, codes or JSON aloud. Say amounts, dates "
            "and times naturally in the current language.",
        ])

        ctx = self.define_contexts().add_context("default")
        ctx.add_step("identify") \
            .set_text("Ask for the six-digit account number and the service ZIP code, "
                      "then call lookup_account.") \
            .set_functions(["lookup_account"]) \
            .set_valid_steps([])  # only the lookup_account handler can leave this step
        ctx.add_step("help") \
            .set_text("Greet ${global_data.account.first_name} by name. Help with an outage "
                      "check or the balance due. When they are done, move to wrap_up.") \
            .set_functions(["check_outage", "get_balance"]) \
            .set_valid_steps(["wrap_up"])
        ctx.add_step("wrap_up") \
            .set_text("Thank the caller and say goodbye in their current language.") \
            .set_functions([])

    @AgentBase.tool(
        name="lookup_account",
        description="Find the caller's account by account number and service ZIP code.",
        parameters={
            "type": "object",
            "properties": {
                "account_number": {"type": "string", "description": "Six-digit account number"},
                "zip": {"type": "string", "description": "Five-digit service ZIP code"},
            },
            "required": ["account_number", "zip"],
        },
    )
    def lookup_account(self, args, raw_data):
        number = "".join(c for c in str(args.get("account_number", "")) if c.isdigit())
        zip_code = "".join(c for c in str(args.get("zip", "")) if c.isdigit())
        acct = self.db["accounts"].get(number)
        if not acct or acct["zip"] != zip_code:
            return data({"found": False, "reason": "no_match"})
        public = {k: acct[k] for k in PUBLIC_FIELDS}
        return (
            data({"found": True, **public})
            .update_global_data({"account_id": number, "account": public})
            .swml_change_step("help")
        )

    def _account(self, raw_data):
        account_id = (raw_data or {}).get("global_data", {}).get("account_id")
        return self.db["accounts"].get(account_id or "")

    @AgentBase.tool(
        name="check_outage",
        description="Check for a service outage at the caller's verified service address.",
        parameters={"type": "object", "properties": {}},
    )
    def check_outage(self, args, raw_data):
        acct = self._account(raw_data)  # the ZIP comes from the verified account, not the model
        if not acct:
            return data({"error": "not_verified"})
        outage = self.db["outages"].get(acct["zip"])
        if not outage:
            return data({"outage": False})
        return data({"outage": True, "cause": outage["cause"], "restore_eta": outage["restore_eta"]})

    @AgentBase.tool(
        name="get_balance",
        description="Get the balance due and due date on the caller's verified account.",
        parameters={"type": "object", "properties": {}},
    )
    def get_balance(self, args, raw_data):
        acct = self._account(raw_data)
        if not acct:
            return data({"error": "not_verified"})
        return data({"amount_due": acct["amount_due"], "currency": "USD", "due_date": acct["due_date"]})


agent = BilingualSupportAgent()

if __name__ == "__main__":
    agent.run()
