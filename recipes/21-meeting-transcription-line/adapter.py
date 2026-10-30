"""The ONE place that knows the shape of a live_transcribe webhook body.

The SWML docs don't publish this payload. The shape below was captured from a live call on
2026-10-30 (smoke call 30f79d23-dfb5-466c-84cc-e31255f778e1, inbound leg 646b6018-...,
`live_events: true`, deepgram):

  {"call_info": {"call_id": ..., "project_id": ..., "space_id": ...},
   "channel_data": {"content_disposition": "transcribe.utterance", "call_answer_date": <us>, ...},
   "confidence": 0.99,
   "utterance": {"role": "remote-caller" | "local-caller", "content": "text", "lang": "en-US",
                 "timestamp": <microseconds>, "utterance_id": "<uuid>", "confidence": 0.99, ...}}

At hangup, one more body arrives with content_disposition "transcribe.conversation_log" and
a full `conversation_log` list instead of `utterance`. This consumer ignores it, because
every line in it already arrived live (the raw body is still stored).

Every utterance in the capture was a FINAL result. TODO(blocked: partial events not
observed). No partial result arrived, so the partial path (an utterance with
`"is_final": false`, merged by utterance_id) is untested against the platform.
"""
from dataclasses import asdict, dataclass


@dataclass
class Segment:
    call_id: str
    speaker: str
    text: str
    is_final: bool
    ts: float            # when the utterance happened (epoch seconds), per the platform
    received_at: float   # when this consumer received it (epoch seconds)
    segment_id: str = ""
    answered_at: float = 0.0  # when the platform answered the call (epoch seconds), 0 if unknown

    @property
    def delay_ms(self) -> int:
        return max(0, round((self.received_at - self.ts) * 1000))

    def to_dict(self) -> dict:
        return {**asdict(self), "delay_ms": self.delay_ms}


def call_id_of(body) -> str:
    if not isinstance(body, dict):
        return "unparsed"
    for envelope in ("call_info", "channel_data"):
        if isinstance(body.get(envelope), dict) and body[envelope].get("call_id"):
            return str(body[envelope]["call_id"])
    return "unparsed"


def parse_event(body, received_at: float) -> list[Segment]:
    """Turn one webhook body into zero or one Segment. Never raises on odd input."""
    utt = body.get("utterance") if isinstance(body, dict) else None
    if not isinstance(utt, dict):
        return []        # conversation_log at hangup, or something new: raw body is kept
    text = str(utt.get("content") or "").strip()
    if not text:
        return []
    stamp = utt.get("timestamp")
    ts = stamp / 1e6 if isinstance(stamp, (int, float)) and stamp > 0 else received_at
    channel = body.get("channel_data") if isinstance(body.get("channel_data"), dict) else {}
    answered = channel.get("call_answer_date")
    answered_at = answered / 1e6 if isinstance(answered, (int, float)) and answered > 0 else 0.0
    return [Segment(
        call_id=call_id_of(body),
        speaker=str(utt.get("role") or "unknown"),
        text=text,
        is_final=utt.get("is_final") is not False,   # every captured utterance was final
        ts=ts,
        received_at=received_at,
        segment_id=str(utt.get("utterance_id") or ""),
        answered_at=answered_at,
    )]
