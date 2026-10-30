"""The adapter is the only code that knows the payload shape (captured from a live call)."""
import random

from adapter import call_id_of, parse_event
from consumer import merge

CALL = "c0ffee00-0000-4000-8000-000000000021"
T0 = 1793000000.0


def parse_all(bodies, received_at=T0 + 60):
    return [seg for b in bodies for seg in parse_event(b, received_at)]


def test_utterance_event(meeting_events):
    seg = parse_event(meeting_events[2], received_at=T0 + 9.584)[0]
    assert (seg.call_id, seg.speaker, seg.is_final) == (CALL, "remote-caller", True)
    assert seg.text == "Good morning, everyone. This is the weekly review."
    assert seg.ts == T0 + 9.5                  # utterance.timestamp is microseconds
    assert seg.delay_ms == 84                  # received_at - ts
    assert seg.answered_at == T0               # channel_data.call_answer_date
    assert seg.segment_id == meeting_events[2]["utterance"]["utterance_id"]


def test_conversation_log_at_hangup_yields_nothing(meeting_events):
    last = meeting_events[-1]
    assert last["channel_data"]["content_disposition"] == "transcribe.conversation_log"
    assert parse_event(last, T0) == [] and call_id_of(last) == CALL


def test_garbage_never_raises():
    for body in (None, [], "text", 42, {}, {"utterance": "x"}, {"utterance": {"content": "  "}}):
        assert parse_event(body, 1.0) == []
    assert call_id_of(None) == call_id_of({}) == "unparsed"


def test_missing_timestamp_falls_back_to_receive_time():
    seg = parse_event({"utterance": {"content": "hi"}}, received_at=123.0)[0]
    assert (seg.ts, seg.delay_ms, seg.speaker, seg.call_id) == (123.0, 0, "unknown", "unparsed")


def test_merge_orders_by_timestamp_not_arrival(meeting_events):
    shuffled = meeting_events[:]
    random.Random(21).shuffle(shuffled)
    merged = merge(parse_all(shuffled))
    assert merged == merge(parse_all(meeting_events))
    assert [s.text for s in merged][-1] == "First item is the launch date."
    assert all(s.is_final for s in merged) and len(merged) == 4


def test_partials_are_replaced_by_their_final(partial_events):
    merged = merge(parse_all(partial_events))
    assert [(s.speaker, s.is_final, s.text) for s in merged] == [
        ("remote-caller", True, "Good morning, everyone. Let's start."),
        ("local-caller", False, "Thanks"),  # still open: a partial with no final yet
    ]
