"""crm.py: dispute references stay unique when calls file disputes at the same time."""
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

RECIPE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RECIPE))

import config  # noqa: E402
import crm  # noqa: E402


def test_concurrent_disputes_get_unique_refs(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DISPUTES_FILE", tmp_path / "disputes.jsonl")
    with ThreadPoolExecutor(8) as pool:
        refs = list(pool.map(lambda i: crm.open_dispute("ACC-0101", f"T-{i}", "x"), range(32)))
    assert sorted(refs) == [f"D-{n:04d}" for n in range(1, 33)]
    lines = [json.loads(line) for line in config.DISPUTES_FILE.read_text().splitlines()]
    assert sorted(r["ref"] for r in lines) == sorted(refs)
