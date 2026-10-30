"""Rule engine against fixture transcripts: on time passes, late or missing fires exactly one alert."""
from adapter import parse_event
from rules import ComplianceMonitor, normalize

import config

T0 = 1793000000.0   # the fixtures' call_answer_date (microseconds 1793000000000000)


def utt(call_id, text, ts, role="local-caller", final=True, answered=None):
    """One body in the captured live_transcribe shape (see adapter.py)."""
    body = {"call_info": {"call_id": call_id},
            "utterance": {"role": role, "content": text, "timestamp": int(ts * 1e6)}}
    if answered:
        body["channel_data"] = {"call_answer_date": int(answered * 1e6)}
    if not final:
        body["utterance"]["is_final"] = False
    return parse_event(body, received_at=ts + 0.2)[0]


def run(load_fixture, name, rules=config.RULES, grace=0.0):
    mon = ComplianceMonitor(rules, grace=grace)
    events = load_fixture(name)
    call_id = events[0]["call_info"]["call_id"]
    alerts = []                                    # clock: call_answer_date in each event
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
    mon.observe(utt("p", "this call is recorded", T0 + 1, final=False))
    assert [a.rule_id for a in mon.check_deadlines(T0 + 100)] == ["recording-disclosure", "agent-identification"]


def test_speaker_restriction():
    rules = [{"id": "r", "within_seconds": 30, "speaker": "local-caller", "phrases": ["this call is recorded"]}]
    mon = ComplianceMonitor(rules)
    mon.start_call("s", T0)
    mon.observe(utt("s", "This call is recorded.", T0 + 2, role="remote-caller"))   # wrong leg
    assert mon.status("s") == {"r": "pending"}
    mon.observe(utt("s", "This call is recorded.", T0 + 2, role="local-caller"))
    assert mon.status("s") == {"r": "passed"}


def test_grace_waits_for_in_flight_results():
    rules = [{"id": "r", "within_seconds": 30, "phrases": ["recorded"]}]
    mon = ComplianceMonitor(rules, grace=3)
    mon.start_call("g", T0)
    assert mon.check_deadlines(T0 + 32) == []          # past the deadline, inside the grace
    mon.observe(utt("g", "recorded", T0 + 29.5))
    assert mon.check_deadlines(T0 + 40) == [] and mon.status("g") == {"r": "passed"}


def test_clock_starts_at_platform_answer_time():
    mon = ComplianceMonitor([{"id": "r", "within_seconds": 10, "phrases": ["recorded"]}])
    mon.observe(utt("a", "hello", T0 + 6, answered=T0))           # first words 6 s in
    assert [a.deadline for a in mon.check_deadlines(T0 + 11)] == [T0 + 10]


def test_clock_falls_back_to_first_segment():
    mon = ComplianceMonitor([{"id": "r", "within_seconds": 10, "phrases": ["recorded"]}])
    mon.observe(utt("f", "hello", T0))                            # no call_answer_date
    assert [a.deadline for a in mon.check_deadlines(T0 + 11)] == [T0 + 10]


def test_normalize_ignores_case_and_punctuation():
    assert normalize("This call -- is RECORDED!") == "this call is recorded"
