"""Mock payment connector, served by the same app under /pay so it shares the one tunnel.

Contract (Docs: swml/reference/calling/pay): SignalWire POSTs JSON with transaction_id,
cardnumber, cvv, postal_code, expiry_month, expiry_year, chargeAmount, currency_code, ...
Reply 200 {"charge_id": ..., "error_code": null, "error_message": null} to approve, or a
non-200 with charge_id null and an error_code to decline (the caller hears payment-failed).

Card data rule: the request body is read into a local and never logged, stored or echoed.
Only the transaction id, the amount and the result are logged.
"""
import base64
import logging
import secrets

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

import config

log = logging.getLogger("pay_connector")


def decide(card_number: str) -> tuple[str, str] | None:
    """None = approve. Unknown cards decline: this mock never approves a real card."""
    digits = "".join(ch for ch in str(card_number) if ch.isdigit())
    if len(digits) < 4:
        return ("invalid_card", "Card number missing")
    return config.MOCK_CARDS.get(digits[-4:], ("card_not_supported", "Only test cards are accepted"))


def make_router(credentials: tuple[str, str], status_store: dict) -> APIRouter:
    router = APIRouter()
    expected = "Basic " + base64.b64encode(f"{credentials[0]}:{credentials[1]}".encode()).decode()

    def authorized(request: Request) -> bool:
        return secrets.compare_digest(request.headers.get("authorization", ""), expected)

    @router.post("/pay")
    async def charge(request: Request):
        if not authorized(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        try:
            body = await request.json()
        except ValueError:
            return JSONResponse({"charge_id": None, "error_code": "bad_request",
                                 "error_message": "Body must be JSON"}, status_code=400)
        txn = str(body.get("transaction_id", ""))[:64]
        outcome = decide(body.get("cardnumber", ""))
        log.info("pay txn=%s amount=%s result=%s", txn, body.get("chargeAmount"),
                 "approved" if outcome is None else outcome[0])
        if outcome is None:
            return {"charge_id": f"ch_mock_{txn[:12] or secrets.token_hex(6)}",
                    "error_code": None, "error_message": None}
        return JSONResponse({"charge_id": None, "error_code": outcome[0], "error_message": outcome[1]},
                            status_code=402)

    @router.post("/pay/status")
    async def status(request: Request):
        """pay status_url callback. Keep only the event name per call; drop every card field."""
        if not authorized(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        params = (await request.json()).get("params", {})
        call_id = str(params.get("call_id", ""))
        status_store[call_id] = {"for": params.get("for"), "error_type": params.get("error_type") or None}
        log.info("pay status call=%s for=%s", call_id, params.get("for"))
        return {"ok": True}

    return router
