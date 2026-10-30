"""The ONE place that knows the shape of a live_transcribe webhook body.

TODO(blocked: payload undocumented). The SWML docs say only that "partial results are sent
as they occur" when live_events is on. No source gives field names for the text, the leg,
the partial/final flag or the timestamp. Until a live call confirms the shape:
  * every raw body is stored untouched (consumer.py, <call>.raw.jsonl), and
  * this adapter tries the candidate field names below, in order.
The candidates come from the closest documented SignalWire callback (ai_sidecar: a
`call_info` envelope with `call_id`, an event object with `type` and a `ts` in
microseconds) plus the field names the default engine (Deepgram) uses (`transcript`,
`is_final`, `speech_final`, `channel`). When a real body is captured, delete the guesses
and keep the fields that are actually there.
"""
from dataclasses import asdict, dataclass
from datetime import datetime


@dataclass
class Segment:
    call_id: str
    speaker: str
    text: str
    is_final: bool
    ts: float            # when the speech happened (epoch seconds), per the platform
    received_at: float   # when this consumer received it (epoch seconds)
    segment_id: str = ""

    @property
    def delay_ms(self) -> int:
        return max(0, round((self.received_at - self.ts) * 1000))

    def to_dict(self) -> dict:
        return {**asdict(self), "delay_ms": self.delay_ms}


EVENT_KEYS = ("transcribe_event", "transcription", "event", "params", "data")
TEXT_KEYS = ("text", "transcript", "utterance", "content")
SPEAKER_KEYS = ("direction", "speaker", "channel", "leg", "role")
TS_KEYS = ("ts", "timestamp", "event_time", "time", "start_time")


def _first(obj: dict, keys):
    return next((obj[k] for k in keys if obj.get(k) not in (None, "")), None)


def _epoch_seconds(value, fallback: float) -> float:
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return fallback
    if not isinstance(value, (int, float)):
        return fallback
    if value > 1e14:      # microseconds (ai_sidecar documents ts in microseconds)
        return value / 1e6
    if value > 1e11:      # milliseconds
        return value / 1e3
    return float(value)


def call_id_of(body) -> str:
    if not isinstance(body, dict):
        return "unparsed"
    info = body.get("call_info") if isinstance(body.get("call_info"), dict) else {}
    return str(info.get("call_id") or body.get("call_id") or "unparsed")


def parse_event(body: dict, received_at: float) -> list[Segment]:
    """Turn one webhook body into zero or more Segments. Never raises on odd input."""
    if not isinstance(body, dict):
        return []
    call_id = call_id_of(body)
    event = next((body[k] for k in EVENT_KEYS if isinstance(body.get(k), dict)), body)
    items = event.get("segments") or event.get("results") or [event]
    out = []
    for item in items if isinstance(items, list) else [items]:
        if not isinstance(item, dict):
            continue
        text = _first(item, TEXT_KEYS)
        alts = item.get("alternatives")
        if text is None and isinstance(alts, list) and alts and isinstance(alts[0], dict):
            text = alts[0].get("transcript")
        if not text or not str(text).strip():
            continue
        kind = str(item.get("type") or item.get("status") or "").lower()
        is_final = bool(item.get("is_final") or item.get("final") or item.get("speech_final")
                        or kind in ("final", "complete", "completed"))
        out.append(Segment(
            call_id=str(item.get("call_id") or call_id),
            speaker=str(_first(item, SPEAKER_KEYS) or "unknown"),
            text=str(text).strip(),
            is_final=is_final,
            ts=_epoch_seconds(_first(item, TS_KEYS), received_at),
            received_at=received_at,
            segment_id=str(item.get("segment_id") or item.get("utterance_id") or ""),
        ))
    return out
