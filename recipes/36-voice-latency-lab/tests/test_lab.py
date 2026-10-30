"""Timing parser and report generator, on fixture post-prompt payloads (no live calls)."""
import json
import random
import shutil
import sys
from pathlib import Path

RECIPE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RECIPE))

import config  # noqa: E402
from lab.report import load_runs, percentile, render, summarize  # noqa: E402
from lab.timings import entry_timing, parse_turns  # noqa: E402

FIXTURES = RECIPE / "tests" / "fixtures"
CALL_1 = FIXTURES / "runs" / "nano-rime" / "c0ffee00-0000-4000-8000-000000000001.json"


def payload():
    return json.loads(CALL_1.read_text())


def test_one_value_per_caller_turn_using_first_audio():
    turns, omitted = parse_turns(payload())
    assert [t["mouth_to_ear_ms"] for t in turns] == [950.0, 1120.0]  # the 2350 ms final reply is deduped
    assert omitted == 1                                               # the unstamped "Goodbye!"


def test_segments_are_differences_of_reported_fields():
    first = parse_turns(payload())[0][0]
    assert first["turn_detection_ms"] == 400 and first["model_ms"] == 300
    assert first["assembly_ms"] == 80.0 and first["tts_ms"] == 140.0
    assert first["tools_other_ms"] == 30.0


LIVE = sorted((FIXTURES / "live").glob("*.json"))  # sanitized post-prompt payloads from real lab calls


def test_live_payloads_mouth_to_ear_matches_platform_acoustic_latency():
    assert LIVE
    for path in LIVE:
        p = json.loads(path.read_text())
        reported = {e["stamps_us"]["last_word_end"]: e["acoustic_latency"] for e in p["raw_call_log"]
                    if e.get("role") == "assistant" and e.get("acoustic_latency")
                    and "last_word_end" in e.get("stamps_us", {})}
        turns, _ = parse_turns(p)
        assert len(turns) >= 2
        for t in turns:
            if t["anchor"] in reported:
                assert abs(t["mouth_to_ear_ms"] - reported[t["anchor"]]) <= 1.0


def test_live_payloads_segments_add_up_to_mouth_to_ear():
    for path in LIVE:
        for t in parse_turns(json.loads(path.read_text()))[0]:
            parts = sum(t[k] for k in ("turn_detection_ms", "tools_other_ms", "model_ms", "assembly_ms", "tts_ms"))
            assert abs(parts - t["mouth_to_ear_ms"]) <= 3.0


def test_prefers_raw_call_log_over_consolidated_call_log():
    p = payload()
    assert len(parse_turns(p)[0]) == 2
    del p["raw_call_log"]
    assert len(parse_turns(p)[0]) == 1  # call_log alone (consolidated) has lost the first turn


def test_missing_or_bad_stamps_are_omitted_not_estimated():
    assert entry_timing({"role": "assistant", "latency": 300}) is None
    assert entry_timing({"stamps_us": {"last_word_end": 10, "first_audio": 5}}) is None
    assert entry_timing({"stamps_us": {"last_word_end": True, "first_audio": 5}}) is None
    t = entry_timing({"stamps_us": {"last_word_end": 1_000_000, "first_audio": 1_900_000}})
    assert t["mouth_to_ear_ms"] == 900.0 and t["model_ms"] is None and t["tts_ms"] is None


def test_non_assistant_and_junk_entries_ignored():
    assert parse_turns({"raw_call_log": ["junk", {"role": "tool", "stamps_us": {}}, {"role": "user"}]}) == ([], 0)
    assert parse_turns({}) == ([], 0)


def test_percentile_nearest_rank():
    assert percentile([], 50) is None
    assert percentile([5], 95) == 5
    assert percentile([880, 950, 1010, 1120], 50) == 950
    assert percentile([880, 950, 1010, 1120], 95) == 1120
    assert percentile(list(range(1, 101)), 95) == 95


def test_report_matches_golden_file():
    table = render(summarize(load_runs(FIXTURES / "runs"), list(config.CONFIGS)), config.CONFIGS)
    assert table == (FIXTURES / "expected_report.md").read_text()


def test_report_is_stable_regardless_of_input_order(tmp_path):
    runs = load_runs(FIXTURES / "runs")
    shuffled = {k: random.Random(7).sample(v, len(v)) for k, v in reversed(list(runs.items()))}
    a = render(summarize(runs, list(config.CONFIGS)), config.CONFIGS)
    b = render(summarize(shuffled, list(config.CONFIGS)), config.CONFIGS)
    assert a == b == render(summarize(runs, list(config.CONFIGS)), config.CONFIGS)


def test_report_follows_config_order_and_skips_configs_without_runs():
    rows = summarize(load_runs(FIXTURES / "runs"), list(config.CONFIGS))
    assert [r["config"] for r in rows] == ["nano-rime", "mini-rime"]


def test_config_comes_from_payload_global_data(tmp_path):
    shutil.copy(CALL_1, tmp_path / "x.json")
    (tmp_path / "misfiled").mkdir()
    shutil.move(tmp_path / "x.json", tmp_path / "misfiled" / "x.json")
    assert list(load_runs(tmp_path)) == ["nano-rime"]
