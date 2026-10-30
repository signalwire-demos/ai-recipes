"""AI sales call copilot: an ai_sidecar listens to both legs and pushes objection cards.

Governance point: the sidecar joins the call without owning it. It has no voice and one
tool, flag_objection, which hands the customer's words to a plain-code classifier. Code,
not the model, picks the objection category, and the talk tracks in config.PLAYBOOK go
straight to the rep's screen. The model never sees them.
"""
import asyncio
import base64
import json
import re
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

RULES = {cat: [re.compile(p, re.I) for p in spec["patterns"]] for cat, spec in config.PLAYBOOK.items()}


def classify(text: str) -> list[str]:
    """Deterministic objection classifier: every playbook category whose regex matches."""
    return [cat for cat, rules in RULES.items() if any(r.search(text or "") for r in rules)]


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


class SalesCopilot(SWMLService):
    def __init__(self, **kwargs):
        super().__init__(name="sales-copilot", route="/", port=config.PORT, **kwargs)
        self.feed = Feed(config.FEED_SIZE)
        self.last_seen: dict = {}   # (call_id, category) -> time the card was last shown

        self.define_tool(
            name="flag_objection",
            description="Report a customer objection or concern. Pass the customer's exact words.",
            parameters={"customer_quote": {"type": "string", "description": "What the customer said, verbatim"}},
            required=["customer_quote"],
            handler=self.flag_objection,
            secure=False,  # the sidecar has no per-call token; basic auth in web_hook_url guards /swaig
        )

        self.add_verb("answer", {})
        self.add_verb("ai_sidecar", self.sidecar_config())
        self.add_verb("connect", {"to": config.REP_NUMBER, "from": config.FROM_NUMBER,
                                  "answer_on_bridge": True})
        self.add_verb("hangup", {})

    def base_url(self) -> str:
        user, password = self.get_basic_auth_credentials()
        url = urlsplit(config.PUBLIC_URL)
        return f"{url.scheme}://{user}:{password}@{url.netloc}{url.path}"

    def sidecar_config(self) -> dict:
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
            "url": f"{self.base_url()}/events",
            "hints": config.COMPETITORS,
            "SWAIG": {"defaults": {"web_hook_url": f"{self.base_url()}/swaig"}, "functions": functions},
        }
        if config.SIDECAR_MODEL:
            cfg["model"] = config.SIDECAR_MODEL
        return cfg

    def objection_cards(self, text: str, call_id: str, source: str) -> list[dict]:
        cards, now = [], time.time()
        for cat in classify(text):
            if now - self.last_seen.get((call_id, cat), 0) < config.REPEAT_AFTER_S:
                continue
            self.last_seen[(call_id, cat)] = now
            spec = config.PLAYBOOK[cat]
            cards.append(self.feed.push({"kind": "objection", "category": cat, "title": spec["title"],
                                         "tips": spec["tips"], "quote": text, "call_id": call_id,
                                         "source": source}))
        return cards

    def flag_objection(self, args, raw_data):
        quote = str(args.get("customer_quote", "")).strip()
        call_id = (raw_data or {}).get("call_id", "unknown")
        if not classify(quote):
            return FunctionResult("That is not a playbook objection. Give one line of advice or call sidecar_skip.")
        self.objection_cards(quote, call_id, source="sidecar")
        # The response names nothing from the playbook: the talk track is for the rep only.
        return FunctionResult("The rep has the playbook card. Call sidecar_skip.")

    def on_event(self, body: dict) -> list[dict]:
        """Consume one ai_sidecar callback. The event is nested under sidecar_event (per the docs)."""
        event = body.get("sidecar_event") or {}
        call_id = (body.get("call_info") or {}).get("call_id", "unknown")
        kind = event.get("type")
        if kind == "insight" and event.get("raw"):
            return [self.feed.push({"kind": "insight", "text": event["raw"], "call_id": call_id})]
        if kind == "final":
            return [self.feed.push({"kind": "final", "text": event.get("stop_reason", "ended"),
                                    "call_id": call_id})]
        # TODO(blocked: per-type callback fields are at docs apis/rest/webhooks/ai-sidecar-callback,
        # not verified). Transcript events are classified only if they carry a string "text".
        if kind in config.TRANSCRIPT_EVENT_TYPES and isinstance(event.get("text"), str):
            return self.objection_cards(event["text"], call_id, source="transcript")
        return []


def build_app(svc: SalesCopilot) -> FastAPI:
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
            body = await request.json()
        except json.JSONDecodeError:
            body = {}
        svc.on_event(body if isinstance(body, dict) else {})
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


sidecar = SalesCopilot()

if __name__ == "__main__":
    import uvicorn

    print(f"Rep page: {config.PUBLIC_URL}/rep/  (basic auth)")
    uvicorn.run(build_app(sidecar), host="0.0.0.0", port=config.PORT)
