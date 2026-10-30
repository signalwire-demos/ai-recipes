"""AI Compliance Call Monitor: required disclosures checked live, a supervisor alerted on a miss.

Built on recipe #21 (copied in, so this folder stands alone): the SWML starts
live_transcribe before anyone speaks and sends every event to your own consumer. Each
parsed segment also goes to a rule engine (rules.py) that checks the required phrases in
config.RULES were said within N seconds. A miss sends exactly one alert (alerts.py) by SMS
or webhook, with the call ID and the deadline. Rules are code, not a model's opinion.

Each call's clock starts when the platform answered it (channel_data.call_answer_date in
every transcript event), not when this server happened to hear about it.

TODO(blocked: conference behavior undocumented). Single-call dial-in, as in #21; the seam
is the `connect` branch in build_swml().
"""
import asyncio
import contextlib
import time
from urllib.parse import quote, urlparse

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from signalwire.core.swml_service import SWMLService

import config
from alerts import AlertSender
from consumer import Broker, TranscriptStore, basic_auth_checker, create_router
from rules import ComplianceMonitor


class MonitoredBroker(Broker):
    """The #21 broker, plus: every published segment is also fed to the rule engine."""

    def __init__(self, monitor: ComplianceMonitor):
        super().__init__()
        self.monitor = monitor

    def publish(self, seg) -> None:
        super().publish(seg)
        self.monitor.observe(seg)


def webhook_url(svc: SWMLService) -> str:
    if config.TRANSCRIPT_WEBHOOK_URL:
        return config.TRANSCRIPT_WEBHOOK_URL
    base = urlparse(config.PUBLIC_URL or f"http://localhost:{config.PORT}")
    user, password = svc.get_basic_auth_credentials()
    auth = f"{quote(user, safe='')}:{quote(password, safe='')}"
    return f"{base.scheme}://{auth}@{base.netloc}{base.path.rstrip('/')}{config.TRANSCRIPT_PATH}"


def build_swml(svc: SWMLService) -> None:
    svc.reset_document()
    svc.add_verb("answer", {})
    svc.add_verb("live_transcribe", {"action": {"start": {
        "lang": config.LANGUAGE_CODE,
        "direction": config.DIRECTION,
        "webhook": webhook_url(svc),
        "live_events": True,
        "speech_engine": config.SPEECH_ENGINE,
    }}})
    svc.add_verb("play", {"url": f"say:{config.GREETING}"})
    if config.BRIDGE_TO:
        bridge = {"to": config.BRIDGE_TO}
        if config.BRIDGE_FROM:
            bridge["from"] = config.BRIDGE_FROM
        svc.add_verb("connect", bridge)
    else:
        svc.add_verb("play", {"url": f"silence:{config.MAX_CALL_SECONDS}"})
    svc.add_verb("hangup", {})


def create_service() -> SWMLService:
    svc = SWMLService(name="compliance-call-monitor", route=config.ROUTE, port=config.PORT)
    build_swml(svc)
    return svc


def create_app(svc: SWMLService, store: TranscriptStore | None = None, sender: AlertSender | None = None,
               monitor: ComplianceMonitor | None = None) -> FastAPI:
    monitor = monitor or ComplianceMonitor(config.RULES, grace=config.ALERT_GRACE_SECONDS)
    store = store or TranscriptStore(config.TRANSCRIPT_DIR)
    sender = sender or AlertSender(config.ALERT_TARGET, config.ALERT_FROM, config.ALERT_LOG)
    check_auth = basic_auth_checker(*svc.get_basic_auth_credentials())

    async def ticker():  # deadlines pass in silence too, so they are checked on a clock
        while True:
            for alert in monitor.check_deadlines(time.time()):
                await asyncio.to_thread(sender.send, alert)
            await asyncio.sleep(config.DEADLINE_CHECK_SECONDS)

    @contextlib.asynccontextmanager
    async def lifespan(_app):
        task = asyncio.create_task(ticker())
        yield
        task.cancel()

    app = FastAPI(title="Compliance call monitor", lifespan=lifespan)
    app.include_router(create_router(store, MonitoredBroker(monitor), check_auth,
                                     config.SSE_KEEPALIVE_SECONDS, config.TRANSCRIPT_PATH))

    @app.get("/calls/{call_id}/compliance")
    async def compliance(call_id: str, request: Request):
        if not check_auth(dict(request.headers)):
            raise HTTPException(401, headers={"WWW-Authenticate": "Basic"})
        return {"call_id": call_id, "rules": monitor.status(call_id)}

    app.include_router(svc.as_router())  # SWML on POST / (basic auth, checked by the SDK)
    return app


service = create_service()  # swaig-test --dump-swml finds this
app = create_app(service)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=config.PORT)
