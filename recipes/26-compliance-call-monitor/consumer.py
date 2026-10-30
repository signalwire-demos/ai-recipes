"""Transcript consumer: receives live_transcribe webhooks, stores them, re-broadcasts over SSE.

  POST /transcript              the platform's webhook (basic auth); always answers 200
  GET  /calls                   call ids with a stored transcript
  GET  /calls/{call_id}         the merged transcript (finals in time order, open partials last)
  GET  /events[?call_id=...]    Server-Sent Events, one `segment` event per parsed segment
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
    """Fan-out to SSE subscribers. Each subscriber gets its own queue."""

    def __init__(self):
        self.queues: set[asyncio.Queue] = set()

    def publish(self, seg: Segment) -> None:
        for q in list(self.queues):
            q.put_nowait(seg)

    async def stream(self, call_id: str | None, keepalive: float, replay: list[Segment] = ()):
        q: asyncio.Queue = asyncio.Queue()
        self.queues.add(q)
        try:
            for seg in replay:
                yield f"event: segment\ndata: {json.dumps(seg.to_dict())}\n\n"
            while True:
                try:
                    seg = await asyncio.wait_for(q.get(), timeout=keepalive)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                if call_id is None or seg.call_id == call_id:
                    yield f"event: segment\ndata: {json.dumps(seg.to_dict())}\n\n"
        finally:
            self.queues.discard(q)


def basic_auth_checker(user: str, password: str):
    expected = "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()
    return lambda headers: hmac.compare_digest(headers.get("authorization", ""), expected)


def create_router(store: TranscriptStore, broker: Broker, check_auth, keepalive: float = 15,
                  path: str = "/transcript") -> APIRouter:
    def require_auth(request: Request):  # transcripts are private: every route needs auth
        if not check_auth(dict(request.headers)):
            raise HTTPException(401, headers={"WWW-Authenticate": "Basic"})

    router = APIRouter(dependencies=[Depends(require_auth)])

    @router.post(path)
    async def receive(request: Request):
        received_at = time.time()
        try:
            body = json.loads(await request.body() or b"null")
        except ValueError:
            body = None
        segments = parse_event(body, received_at)
        store.add_raw(call_id_of(body), body)  # always keep the raw body (see adapter.py)
        for seg in segments:
            store.add(seg)
            broker.publish(seg)
        return {"ok": True, "segments": len(segments)}  # 200 even when nothing parsed

    @router.get("/calls")
    async def calls():
        return {"calls": store.calls()}

    @router.get("/calls/{call_id}")
    async def transcript(call_id: str):
        return {"call_id": call_id, "segments": [s.to_dict() for s in merge(store.segments(call_id))]}

    @router.get("/events")
    async def events(call_id: str | None = None):
        replay = merge(store.segments(call_id)) if call_id else []
        return StreamingResponse(broker.stream(call_id, keepalive, replay),
                                 media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    return router
