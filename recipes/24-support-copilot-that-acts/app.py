"""AI support copilot that acts: an ai_sidecar runs scoped tools while the human rep talks.

Governance point: the sidecar has exactly two tools. The credit cap lives in the
issue_credit handler; it is never in the prompt, a tool description or a tool response,
and every refusal gets the same answer, so the model can't probe for it. The rep sees
full results on a web page; the model gets only what it needs to keep advising.
"""
import asyncio
import base64
import json
import secrets
import threading
import time
from collections import deque
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from signalwire import FunctionResult
from signalwire.core.swml_service import SWMLService

import config

REFUSED = "Credit not issued. The reason is on the rep's screen. Call sidecar_skip."


def load_orders() -> dict:
    """The order backend. Replace with a call to your order API."""
    return json.loads(config.ORDERS_FILE.read_text())["orders"]


def credited_orders() -> set:
    if not config.CREDIT_LEDGER.is_file():
        return set()
    return {json.loads(line)["order_id"] for line in config.CREDIT_LEDGER.read_text().splitlines() if line}


class Feed:
    """Cards for the rep page. Thread-safe; tool handlers run in worker threads."""

    def __init__(self, size: int):
        self.cards: deque = deque(maxlen=size)
        self.lock = threading.Lock()
        self.next_id = 1

    def push(self, card: dict) -> dict:
        with self.lock:
            card = {"id": self.next_id, "ts": time.time(), **card}
            self.next_id += 1
            self.cards.append(card)
        return card

    def since(self, last_id: int) -> list[dict]:
        with self.lock:
            return [c for c in self.cards if c["id"] > last_id]


class SupportCopilot(SWMLService):
    def __init__(self, **kwargs):
        super().__init__(name="support-copilot", route="/", port=config.PORT, **kwargs)
        self.feed = Feed(config.FEED_SIZE)
        self.ledger_lock = threading.Lock()
        order_id = {"order_id": {"type": "string", "description": "Order number, e.g. A-1001"}}
        # secure=False: the sidecar has no per-call token; basic auth in web_hook_url guards /swaig.
        self.define_tool(name="lookup_order", description="Look up an order's status, items and total.",
                         parameters=order_id, required=["order_id"], handler=self.lookup_order, secure=False)
        self.define_tool(
            name="issue_credit",
            description="Issue a credit on an order after the rep has offered it to the customer.",
            parameters={**order_id,
                        "amount": {"type": "number", "description": f"Credit amount in {config.CURRENCY}, as the rep stated it"},
                        "reason": {"type": "string", "description": "Short reason for the credit"}},
            required=["order_id", "amount", "reason"], handler=self.issue_credit, secure=False)

        self.add_verb("answer", {})
        self.add_verb("ai_sidecar", self.sidecar_config())
        self.add_verb("connect", {"to": config.REP_NUMBER, "from": config.FROM_NUMBER,
                                  "answer_on_bridge": True})
        self.add_verb("hangup", {})

    def sidecar_config(self) -> dict:
        user, password = self.get_basic_auth_credentials()
        url = urlsplit(config.PUBLIC_URL)
        base = f"{url.scheme}://{user}:{password}@{url.netloc}{url.path}"
        functions = []
        for fn in self._tool_registry.get_all_functions().values():
            spec = fn.to_swaig(base_url="")
            spec.pop("web_hook_url", None)   # every tool uses SWAIG.defaults.web_hook_url
            functions.append(spec)
        cfg = {
            "prompt": config.SIDECAR_PROMPT,
            "lang": config.LANGUAGE_CODE,
            "direction": ["remote-caller", "local-caller"],   # both legs: required for sidecar mode
            "customer_role": config.CUSTOMER_ROLE,
            "url": f"{base}/events",
            "hints": config.HINTS,
            "SWAIG": {"defaults": {"web_hook_url": f"{base}/swaig"}, "functions": functions},
        }
        if config.SIDECAR_MODEL:
            cfg["model"] = config.SIDECAR_MODEL
        return cfg

    def lookup_order(self, args, raw_data):
        order_id = str(args.get("order_id", "")).strip().upper()
        call_id = (raw_data or {}).get("call_id", "unknown")
        order = load_orders().get(order_id)
        if not order:
            self.feed.push({"kind": "order", "order_id": order_id, "found": False, "call_id": call_id})
            return FunctionResult(f"No order {order_id}. Suggest the rep confirms the number.")
        self.feed.push({"kind": "order", "order_id": order_id, "found": True, "call_id": call_id, **order})
        # The model gets status, items and total; the customer's phone and the notes stay on the rep's screen.
        eta = f", expected {order['eta']}" if order.get("eta") else ""
        return FunctionResult(f"Order {order_id}: {order['status']}{eta}. Items: {', '.join(order['items'])}. "
                              f"Total {order['total']:.2f} {config.CURRENCY}.")

    def credit_refusal(self, order_id: str, amount: float) -> str | None:
        """Return why a credit must be refused, or None. The rules the model never sees."""
        order = load_orders().get(order_id)
        if not order:
            return f"No order {order_id}."
        if amount <= 0:
            return "The amount must be more than zero."
        if amount > config.CREDIT_CAP_USD:
            return f"{amount:.2f} is over the copilot cap of {config.CREDIT_CAP_USD:.2f}. Escalate to a supervisor."
        if amount > order["total"]:
            return f"{amount:.2f} is more than the order total of {order['total']:.2f}."
        if order_id in credited_orders():
            return f"Order {order_id} already has a credit."
        return None

    def issue_credit(self, args, raw_data):
        order_id = str(args.get("order_id", "")).strip().upper()
        call_id = (raw_data or {}).get("call_id", "unknown")
        reason = str(args.get("reason", "")).strip()[:200]
        try:
            amount = round(float(args.get("amount")), 2)
        except (TypeError, ValueError):
            amount = 0.0
        card = {"kind": "credit", "order_id": order_id, "amount": amount, "currency": config.CURRENCY,
                "reason": reason, "call_id": call_id}
        with self.ledger_lock:   # check and write under one lock: no double credit from parallel calls
            refusal = self.credit_refusal(order_id, amount)
            if refusal:
                self.feed.push({**card, "status": "refused", "detail": refusal})
                return FunctionResult(REFUSED)   # same answer for every refusal: nothing to probe
            with config.CREDIT_LEDGER.open("a") as f:
                f.write(json.dumps({"order_id": order_id, "amount": amount, "reason": reason,
                                    "call_id": call_id, "ts": time.time()}) + "\n")
        self.feed.push({**card, "status": "issued", "detail": f"Credited {amount:.2f} {config.CURRENCY}."})
        return FunctionResult(f"Credit of {amount:.2f} {config.CURRENCY} issued on {order_id}. Call sidecar_skip.")

    def on_event(self, body: dict) -> list[dict]:
        """Consume one ai_sidecar callback. The event is nested under sidecar_event (per the docs)."""
        event = body.get("sidecar_event") or {}
        call_id = (body.get("call_info") or {}).get("call_id", "unknown")
        kind = event.get("type")
        if kind == "insight" and event.get("raw"):
            return [self.feed.push({"kind": "insight", "text": event["raw"], "call_id": call_id})]
        if kind == "final":
            return [self.feed.push({"kind": "final", "text": event.get("stop_reason", "ended"), "call_id": call_id})]
        # TODO(blocked: per-type callback fields are at docs apis/rest/webhooks/ai-sidecar-callback, not verified)
        return []


def build_app(svc: SupportCopilot) -> FastAPI:
    app = FastAPI(redirect_slashes=False)
    user, password = svc.get_basic_auth_credentials()
    expected = "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()

    @app.middleware("http")
    async def rep_auth(request: Request, call_next):
        # /swaig and / check basic auth inside the SDK; guard our own routes the same way.
        if request.url.path.startswith(("/rep", "/events")) and not secrets.compare_digest(
                request.headers.get("authorization", ""), expected):
            return Response(status_code=401, headers={"WWW-Authenticate": 'Basic realm="rep"'})
        return await call_next(request)

    @app.post("/events")
    async def events(request: Request):
        try:
            svc.on_event(await request.json())
        except (json.JSONDecodeError, AttributeError):
            pass   # not a JSON object: acknowledge and drop
        return JSONResponse({"ok": True})

    @app.get("/rep/stream")
    async def stream(request: Request, last: int = 0, once: bool = False):
        async def gen():   # EventSource resends Last-Event-ID on reconnect: no card is shown twice
            last_id = int(request.headers.get("last-event-id") or last)
            while True:
                for card in svc.feed.since(last_id):
                    last_id = card["id"]
                    yield f"id: {card['id']}\ndata: {json.dumps(card)}\n\n"
                if once:
                    return
                await asyncio.sleep(0.5)
        return StreamingResponse(gen(), media_type="text/event-stream")

    app.mount("/rep", StaticFiles(directory=config.WEB_DIR, html=True), name="rep")
    app.include_router(svc.as_router())   # GET/POST / (SWML) and POST /swaig (tools)
    return app


sidecar = SupportCopilot()

if __name__ == "__main__":
    import uvicorn

    print(f"Rep page: {config.PUBLIC_URL}/rep/  (basic auth)")
    uvicorn.run(build_app(sidecar), host="0.0.0.0", port=config.PORT)
