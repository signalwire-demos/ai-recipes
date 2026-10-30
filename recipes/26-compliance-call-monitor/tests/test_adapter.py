"""The adapter is the only code that knows the (undocumented) payload shape."""
import random

from adapter import parse_event
from consumer import merge

CALL = "c0ffee00-0000-4000-8000-000000000021"


def parse_all(bodies, received_at=1793000005.0):
    return [seg for b in bodies for seg in parse_event(b, received_at)]


def test_sidecar_style_envelope(meeting_events):
    seg = parse_event(meeting_events[2], received_at=1793000001.4)[0]
    assert (seg.call_id, seg.speaker, seg.is_final) == (CALL, "remote-caller", True)
    assert seg.text == "Good morning everyone, let's start the weekly review."
    assert seg.ts == 1793000000.9          # microseconds -> epoch seconds
    assert seg.delay_ms == 500             # received_at - ts
    assert parse_event(meeting_events[0], 1793000000.1)[0].is_final is False


def test_other_candidate_shapes(other_shapes):
    partial, final = parse_all(other_shapes)  # the summary-only body yields no segment
    assert (partial.call_id, partial.speaker, partial.is_final) == ("flat-0001", "remote-caller", False)
    assert partial.ts == 1793000010.0     # milliseconds -> seconds
    assert final.text == "Hello there, team." and final.is_final
    assert final.ts > partial.ts           # ISO-8601 timestamp parsed


def test_garbage_never_raises():
    for body in (None, [], "text", 42, {}, {"transcribe_event": {"text": "   "}}, {"results": "x"}):
        assert parse_event(body, 1.0) == []


def test_missing_timestamp_falls_back_to_receive_time():
    seg = parse_event({"call_id": "x", "text": "hi"}, received_at=123.0)[0]
    assert seg.ts == 123.0 and seg.delay_ms == 0 and seg.speaker == "unknown"


def test_merge_partials_and_finals(meeting_events):
    merged = merge(parse_all(meeting_events))
    assert [(s.speaker, s.is_final, s.text) for s in merged] == [
        ("remote-caller", True, "Good morning everyone, let's start the weekly review."),
        ("local-caller", True, "Thanks, I have the numbers ready."),
        ("remote-caller", True, "First item is the launch date."),
        ("remote-caller", False, "Any objections"),  # still open: a partial with no final yet
    ]


def test_merge_orders_by_timestamp_not_arrival(meeting_events):
    shuffled = meeting_events[:]
    random.Random(21).shuffle(shuffled)
    assert merge(parse_all(shuffled)) == merge(parse_all(meeting_events))


def test_segment_id_keys_partials_when_present():
    bodies = [{"call_id": "x", "segment_id": "a", "text": "one", "ts": 1.0},
              {"call_id": "x", "segment_id": "b", "text": "two", "ts": 2.0},
              {"call_id": "x", "segment_id": "a", "text": "one done", "ts": 3.0, "is_final": True}]
    assert [s.text for s in merge(parse_all(bodies))] == ["one done", "two"]
