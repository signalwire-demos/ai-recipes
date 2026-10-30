"""Rule engine against fixture transcripts: on time passes, late or missing fires exactly one alert."""
from adapter import parse_event
from rules import ComplianceMonitor, normalize

import config

T0 = 1793000000.0   # the fixtures' call start (microsecond ts 1793000000000000)


def run(load_fixture, name, rules=config.RULES, grace=0.0):
    mon = ComplianceMonitor(rules, grace=grace)
    events = load_fixture(name)
    call_id = events[0]["call_info"]["call_id"]
    mon.start_call(call_id, T0)                    # as if the SWML fetch happened at T0
    alerts = []
    for body in events:
        for seg in parse_event(body, received_at=T0 + 60):
            mon.observe(seg)
        alerts += mon.check_deadlines(T0 + 5)      # mid-call ticks: nothing due yet
    alerts += mon.check_deadlines(T0 + 120)        # well past every deadline
    alerts += mon.check_deadlines(T0 + 240)        # ticking again never re-alerts
    return mon, call_id, alerts


def test_on_time_disclosure_passes(load_fixture):
    mon, call_id, alerts = run(load_fixture, "compliance-on-time")
    assert alerts == []
    assert mon.status(call_id) == {"recording-disclosure": "passed", "agent-identification": "passed"}


def test_late_disclosure_fires_exactly_one_alert(load_fixture):
    mon, call_id, alerts = run(load_fixture, "compliance-late")
    assert [(a.call_id, a.rule_id) for a in alerts] == [(call_id, "recording-disclosure")]
    assert alerts[0].deadline == T0 + 30
    assert mon.status(call_id) == {"recording-disclosure": "late", "agent-identification": "passed"}


def test_missing_disclosure_fires_exactly_one_alert(load_fixture):
    mon, call_id, alerts = run(load_fixture, "compliance-missing")
    assert [a.rule_id for a in alerts] == ["recording-disclosure"]
    assert mon.status(call_id)["recording-disclosure"] == "missed"
    assert call_id in alerts[0].message() and "UTC" in alerts[0].message()


def test_partials_never_satisfy_a_rule():
    mon = ComplianceMonitor(config.RULES)
    mon.start_call("p", T0)
    mon.observe(parse_event({"call_id": "p", "text": "this call is recorded", "ts": T0 + 1}, T0 + 1)[0])
    assert [a.rule_id for a in mon.check_deadlines(T0 + 100)] == ["recording-disclosure", "agent-identification"]


def test_speaker_restriction():
    rules = [{"id": "r", "within_seconds": 30, "speaker": "local-caller", "phrases": ["this call is recorded"]}]
    mon = ComplianceMonitor(rules)
    mon.start_call("s", T0)
    said = {"call_id": "s", "text": "This call is recorded.", "is_final": True, "ts": T0 + 2}
    mon.observe(parse_event({**said, "direction": "remote-caller"}, T0 + 2)[0])   # wrong leg
    assert mon.status("s") == {"r": "pending"}
    mon.observe(parse_event({**said, "direction": "local-caller"}, T0 + 2)[0])
    assert mon.status("s") == {"r": "passed"}


def test_grace_waits_for_in_flight_results():
    rules = [{"id": "r", "within_seconds": 30, "phrases": ["recorded"]}]
    mon = ComplianceMonitor(rules, grace=3)
    mon.start_call("g", T0)
    assert mon.check_deadlines(T0 + 32) == []          # past the deadline, inside the grace
    mon.observe(parse_event({"call_id": "g", "text": "recorded", "is_final": True, "ts": T0 + 29.5}, T0 + 32.5)[0])
    assert mon.check_deadlines(T0 + 40) == [] and mon.status("g") == {"r": "passed"}


def test_clock_falls_back_to_first_segment():
    mon = ComplianceMonitor([{"id": "r", "within_seconds": 10, "phrases": ["recorded"]}])
    mon.observe(parse_event({"call_id": "f", "text": "hello", "is_final": True, "ts": T0}, T0)[0])
    assert [a.deadline for a in mon.check_deadlines(T0 + 11)] == [T0 + 10]


def test_normalize_ignores_case_and_punctuation():
    assert normalize("This call -- is RECORDED!") == "this call is recorded"
