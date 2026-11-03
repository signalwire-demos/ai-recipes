"""Transcript consumer: receives live_transcribe webhooks, stores them, re-broadcasts over SSE.

  POST /transcript              the platform's webhook (platform auth only); always answers 200
  GET  /calls                   call ids with a stored transcript (platform auth only)
  GET  /calls/{call_id}         the merged transcript (finals in time order, open partials last)
  GET  /events?call_id=...      Server-Sent Events, one `segment` event per parsed segment

Two credentials. The platform pair (the SWML basic auth) can do everything; the viewer pair
(VIEWER_USER / VIEWER_PASSWORD) can only read one call it names, and can never write.
"""
import asyncio
import base64
import hmac
import json
import re
import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from adapter import Segment, call_id_of, parse_event


def merge(segments: list[Segment]) -> list[Segment]:
    """Order by event time; each partial replaces the open partial for its speaker (or
    segment id), a final closes it. Returns finals in time order, then open partials."""
    finals, open_partials = [], {}
    for seg in sorted(segments, key=lambda s: s.ts):  # stable: arrival order breaks ties
        key = seg.segment_id or seg.speaker
        if seg.is_final:
            finals.append(seg)
            open_partials.pop(key, None)
        else:
            open_partials[key] = seg
    return finals + sorted(open_partials.values(), key=lambda s: s.ts)


class TranscriptStore:
    """One JSONL file per call. Replace this class to deliver to a database or queue."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, call_id: str, suffix: str) -> Path:
        return self.root / f"{re.sub(r'[^A-Za-z0-9_.-]', '_', call_id)}{suffix}"

    def add_raw(self, call_id: str, body) -> None:
        with self._path(call_id, ".raw.jsonl").open("a") as fh:
            fh.write(json.dumps({"received_at": time.time(), "body": body}) + "\n")

    def add(self, seg: Segment) -> None:
        with self._path(seg.call_id, ".jsonl").open("a") as fh:
            fh.write(json.dumps(seg.to_dict()) + "\n")

    def segments(self, call_id: str) -> list[Segment]:
        path = self._path(call_id, ".jsonl")
        if not path.exists():
            return []
        rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        return [Segment(**{k: v for k, v in r.items() if k != "delay_ms"}) for r in rows]

    def calls(self) -> list[str]:
        return sorted(p.name[:-6] for p in self.root.glob("*.jsonl") if not p.name.endswith(".raw.jsonl"))


class Broker:
    """Fan-out to SSE subscribers. Each subscriber gets its own bounded queue; one that falls
    `maxsize` segments behind is disconnected (EventSource reconnects and gets the replay)."""

    def __init__(self, maxsize: int = 256):
        self.maxsize = maxsize
        self.queues: dict[asyncio.Queue, str | None] = {}  # queue -> call_id filter

    def publish(self, seg: Segment) -> None:
        for q, call_id in list(self.queues.items()):
            if call_id is not None and seg.call_id != call_id:
                continue
            try:
                q.put_nowait(seg)
            except asyncio.QueueFull:  # slow consumer: drop it rather than grow without bound
                self.queues.pop(q, None)
                q.get_nowait()
                q.put_nowait(None)

    async def stream(self, call_id: str | None, keepalive: float, replay: list[Segment] = ()):
        q: asyncio.Queue = asyncio.Queue(self.maxsize)
        self.queues[q] = call_id
        try:
            for seg in replay:
                yield f"event: segment\ndata: {json.dumps(seg.to_dict())}\n\n"
            while True:
                try:
                    seg = await asyncio.wait_for(q.get(), timeout=keepalive)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                if seg is None:
                    return
                yield f"event: segment\ndata: {json.dumps(seg.to_dict())}\n\n"
        finally:
            self.queues.pop(q, None)


def basic_auth_checker(user: str, password: str):
    if not (user and password):  # unset credentials match nothing
        return lambda headers: False
    expected = "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()
    return lambda headers: hmac.compare_digest(headers.get("authorization", ""), expected)


def create_router(store: TranscriptStore, broker: Broker, check_platform, check_viewer=None,
                  keepalive: float = 15, path: str = "/transcript", verify_signature=None) -> APIRouter:
    """check_platform / check_viewer take the request headers; verify_signature (optional)
    takes (headers, raw_body) and is applied to the webhook POST."""
    check_viewer = check_viewer or (lambda headers: False)

    def role(request: Request) -> str:  # transcripts are private: every route needs auth
        headers = dict(request.headers)
        if check_platform(headers):
            return "platform"
        if check_viewer(headers):
            return "viewer"
        raise HTTPException(401, headers={"WWW-Authenticate": "Basic"})

    def platform_only(request: Request):
        if role(request) != "platform":
            raise HTTPException(403, "viewer credentials are read-only")

    router = APIRouter(dependencies=[Depends(role)])

    @router.post(path, dependencies=[Depends(platform_only)])
    async def receive(request: Request):
        received_at = time.time()
        raw = await request.body()
        if verify_signature and not verify_signature(dict(request.headers), raw.decode(errors="replace")):
            raise HTTPException(403, "bad signature")
        try:
            body = json.loads(raw or b"null")
        except ValueError:
            body = None
        segments = parse_event(body, received_at)
        store.add_raw(call_id_of(body), body)  # always keep the raw body (see adapter.py)
        for seg in segments:
            store.add(seg)
            broker.publish(seg)
        return {"ok": True, "segments": len(segments)}  # 200 even when nothing parsed

    @router.get("/calls", dependencies=[Depends(platform_only)])  # listing every call is admin-only
    async def calls():
        return {"calls": store.calls()}

    @router.get("/calls/{call_id}")
    async def transcript(call_id: str):
        return {"call_id": call_id, "segments": [s.to_dict() for s in merge(store.segments(call_id))]}

    @router.get("/events")
    async def events(request: Request, call_id: str | None = None):
        if not call_id and role(request) != "platform":  # no all-calls firehose for viewers
            raise HTTPException(403, "call_id is required")
        replay = merge(store.segments(call_id)) if call_id else []
        return StreamingResponse(broker.stream(call_id, keepalive, replay),
                                 media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    return router
