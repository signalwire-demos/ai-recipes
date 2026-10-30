"""AI Meeting Transcription Line: a dial-in number whose live transcript goes to YOUR consumer.

Governance point: the call flow is code, not a prompt. The SWML below starts
live_transcribe before the caller can speak, sends every event to a webhook you own
(consumer.py), and contains no `ai` verb: no model is in the call path, and the transcript
lands in your storage before anything else can read it.

TODO(blocked: conference behavior undocumented). The card asks for a conference. No source
documents live_transcribe on a leg inside join_conference, so this version is a single-call
dial-in (dictation, or a two-party bridge with MEETING_BRIDGE_NUMBER). The seam is
build_swml(): put `join_conference` where `connect` is once a live test confirms it.
"""
from urllib.parse import quote, urlparse

import uvicorn
from fastapi import FastAPI
from signalwire.core.swml_service import SWMLService

import config
from consumer import Broker, TranscriptStore, basic_auth_checker, create_router


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
    svc = SWMLService(name="meeting-transcription-line", route=config.ROUTE, port=config.PORT)
    build_swml(svc)
    return svc


def create_app(svc: SWMLService, store: TranscriptStore | None = None) -> FastAPI:
    store = store or TranscriptStore(config.TRANSCRIPT_DIR)
    app = FastAPI(title="Meeting transcription line")
    app.include_router(create_router(store, Broker(), basic_auth_checker(*svc.get_basic_auth_credentials()),
                                     config.SSE_KEEPALIVE_SECONDS, config.TRANSCRIPT_PATH))
    app.include_router(svc.as_router())  # SWML on POST / (basic auth, checked by the SDK)
    return app


service = create_service()  # swaig-test --dump-swml finds this
app = create_app(service)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=config.PORT)
