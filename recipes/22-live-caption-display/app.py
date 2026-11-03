"""AI Live Caption Display: live captions for a call, with the real delay shown per segment.

Built on recipe #21 (copied in, so this folder stands alone): the SWML starts
live_transcribe before the caller can speak and sends every event to your own consumer
(consumer.py). This recipe adds a static page at /captions that subscribes to the SSE
stream and draws partial segments grey and final segments solid, each with its measured
delay (platform event time vs. the moment the consumer received it, both stamped by
servers, never by the browser).

TODO(blocked: conference behavior undocumented). The card asks for a conference. No source
documents live_transcribe on a leg inside join_conference, so this version is a single-call
dial-in (dictation, or a two-party bridge with MEETING_BRIDGE_NUMBER). The seam is
build_swml(): put `join_conference` where `connect` is once a live test confirms it.
"""
import json
from urllib.parse import quote, urlparse

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from signalwire.core.security import validate_webhook_signature
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


def signature_verifier(svc: SWMLService):
    """None without a signing key. The signed URL is the webhook URL, tried with and without
    its user:pass@ part (which one the platform signs is not confirmed)."""
    if not config.SIGNING_KEY:
        return None
    url = urlparse(webhook_url(svc))
    urls = {url.geturl(), url._replace(netloc=url.netloc.rpartition("@")[2]).geturl()}
    return lambda headers, raw: any(validate_webhook_signature(
        config.SIGNING_KEY, headers.get("x-signalwire-signature", ""), u, raw) for u in urls)


def auth_checkers(svc: SWMLService):
    """(platform, viewer). The viewer login is off when unset or equal to the platform pair."""
    platform = svc.get_basic_auth_credentials()
    viewer = (config.VIEWER_USER, config.VIEWER_PASSWORD)
    return basic_auth_checker(*platform), basic_auth_checker(*(viewer if viewer != tuple(platform) else ("", "")))


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
    svc = SWMLService(name="live-caption-display", route=config.ROUTE, port=config.PORT)
    build_swml(svc)
    return svc


def create_app(svc: SWMLService, store: TranscriptStore | None = None) -> FastAPI:
    store = store or TranscriptStore(config.TRANSCRIPT_DIR)
    check_platform, check_viewer = auth_checkers(svc)
    app = FastAPI(title="Live caption display")
    app.include_router(create_router(store, Broker(config.SSE_QUEUE_MAX), check_platform, check_viewer,
                                     config.SSE_KEEPALIVE_SECONDS, config.TRANSCRIPT_PATH,
                                     signature_verifier(svc)))

    @app.get("/captions", response_class=HTMLResponse)
    async def captions(request: Request):
        headers = dict(request.headers)  # the viewer login is enough: the page only reads
        if not (check_viewer(headers) or check_platform(headers)):
            raise HTTPException(401, headers={"WWW-Authenticate": "Basic"})
        return captions_page()

    app.include_router(svc.as_router())  # SWML on POST / (basic auth, checked by the SDK)
    return app


def captions_page() -> str:
    settings = {"labels": config.SPEAKER_LABELS, "maxLines": config.MAX_CAPTION_LINES,
                "slowMs": config.DELAY_SLOW_MS, "lateMs": config.DELAY_LATE_MS}
    return config.CAPTIONS_PAGE.read_text().replace("__CAPTION_SETTINGS__", json.dumps(settings).replace("<", "\\u003c"))


service = create_service()  # swaig-test --dump-swml finds this
app = create_app(service)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=config.PORT)
