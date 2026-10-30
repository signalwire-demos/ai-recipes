"""Utility bill payment line: payment isolation with recording paused around the card.

Governance point: card digits never reach the model, the recording, or this app's logs.
take_payment takes no arguments. Its handler reads the amount from global_data (written
by verify_account from the billing record), stops the recording, then hands the caller
to the SWML pay verb, which collects the card by DTMF and posts it straight to the
payment connector. The model only ever hears ${pay_result}. A follow-up step, whose only
tool is resume_recording, turns the recording back on before the call goes on.
"""
import json
from urllib.parse import urlsplit, urlunsplit

from signalwire import AgentBase, FunctionResult

import config
from connector import make_router


def load_accounts() -> dict:
    return json.loads(config.ACCOUNTS_FILE.read_text())


class BillPaymentAgent(AgentBase):
    def __init__(self, **kwargs):
        super().__init__(name="bill-payment", route=config.ROUTE, port=config.PORT, **kwargs)
        self.accounts = load_accounts()
        self.pay_status: dict[str, dict] = {}  # call_id -> last pay status event (no card fields)

        self.add_language("English", config.LANGUAGE_CODE, config.VOICE)
        self.prompt_add_section(
            "Role",
            f"You take bill payments for {config.UTILITY_NAME}. Be brief and friendly.",
            bullets=["Never ask for, repeat or write down card numbers. The keypad collects them."],
        )

        ctx = self.define_contexts().add_context("default")
        ctx.add_step("verify") \
            .set_text("Ask for the account number and the service ZIP code, then call verify_account.") \
            .set_functions(["verify_account"]) \
            .set_valid_steps([])  # only the verify_account handler can open the bill
        ctx.add_step("bill") \
            .set_text(
                "The caller is ${global_data.account.name}. The balance due is "
                "${global_data.account.balance_due} dollars. Ask if they want to pay it in full by card "
                "now. If yes, call take_payment. If not, move to wrap_up."
            ) \
            .set_functions(["take_payment"]) \
            .set_valid_steps(["wrap_up"])
        ctx.add_step("after_payment") \
            .set_text("The keypad payment has finished. Call resume_recording before saying anything else.") \
            .set_functions(["resume_recording"]) \
            .set_valid_steps([])
        ctx.add_step("wrap_up") \
            .set_text("Ask if there is anything else, then say goodbye.") \
            .set_functions([])

    def _register_routes(self, router):
        router.include_router(make_router(self.get_basic_auth_credentials(), self.pay_status))
        super()._register_routes(router)

    def connector_urls(self) -> tuple[str, str]:
        """The mock connector sits behind this app's basic auth, carried in the URL."""
        user, password = self.get_basic_auth_credentials()
        base = urlsplit(config.PUBLIC_URL)
        authed = urlunsplit(base._replace(netloc=f"{user}:{password}@{base.netloc}"))
        return (config.PAY_CONNECTOR_URL or f"{authed}/pay",
                config.PAY_STATUS_URL or f"{authed}/pay/status")

    @AgentBase.tool(
        name="verify_account",
        description="Verify the caller by account number and service ZIP code.",
        parameters={
            "type": "object",
            "properties": {
                "account_number": {"type": "string", "description": "Six-digit account number"},
                "service_zip": {"type": "string", "description": "ZIP code of the service address"},
            },
            "required": ["account_number", "service_zip"],
        },
    )
    def verify_account(self, args, raw_data):
        number = "".join(ch for ch in str(args.get("account_number", "")) if ch.isdigit())
        acct = self.accounts.get(number)
        if not acct or acct["service_zip"] != str(args.get("service_zip", "")).strip():
            return FunctionResult("That didn't match our records. Ask the caller to check both and try again.")
        return (
            FunctionResult("Verified. This call is recorded from here on.")
            .record_call(control_id=config.RECORDING_CONTROL_ID, stereo=True, format="mp3")
            .update_global_data({"account": {"id": number, "name": acct["name"],
                                             "balance_due": f"{acct['balance_due']:.2f}"}})
            .swml_change_step("bill")
        )

    @AgentBase.tool(
        name="take_payment",
        description="Collect a card payment for the full balance due on the keypad.",
        parameters={"type": "object", "properties": {}},  # no amount: the model can't set it
    )
    def take_payment(self, args, raw_data):
        account = ((raw_data or {}).get("global_data") or {}).get("account") or {}
        amount = float(account.get("balance_due") or 0)
        if amount <= 0:
            return FunctionResult("There is nothing to pay on this account.").swml_change_step("wrap_up")
        connector_url, status_url = self.connector_urls()
        return (
            FunctionResult("I'll take your card on the keypad now. The recording is paused.")
            .stop_record_call(control_id=config.RECORDING_CONTROL_ID)
            .pay(
                payment_connector_url=connector_url,
                status_url=status_url,
                charge_amount=f"{amount:.2f}",  # from global_data, never from model arguments
                description=f"{config.UTILITY_NAME} bill",
                security_code=config.PAY_SECURITY_CODE,
                postal_code=config.PAY_POSTAL_CODE,
                max_attempts=config.PAY_MAX_ATTEMPTS,
                valid_card_types=config.PAY_CARD_TYPES,
                parameters=[{"name": "account_id", "value": account.get("id", "")}],
                ai_response=(
                    "The payment result is ${pay_result}. Call resume_recording now. Then tell the "
                    "caller: success means the payment went through; anything else means no "
                    "money was taken and they can try again later."
                ),
            )
            .swml_change_step("after_payment")
        )

    @AgentBase.tool(
        name="resume_recording",
        description="Turn the call recording back on after the keypad payment.",
        parameters={"type": "object", "properties": {}},
    )
    def resume_recording(self, args, raw_data):
        event = self.pay_status.get(str((raw_data or {}).get("call_id", "")), {})
        return (
            FunctionResult("Recording resumed. Now tell the caller the payment result.")
            .record_call(control_id=config.RECORDING_CONTROL_ID, stereo=True, format="mp3")
            .update_global_data({"payment": {"status_event": event.get("for", "unknown")}})
            .swml_change_step("wrap_up")
        )


agent = BillPaymentAgent()

if __name__ == "__main__":
    agent.run()
