import json
import sys
from pathlib import Path

import pytest

RECIPE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RECIPE))
FIXTURES = RECIPE / "data" / "fixtures"


@pytest.fixture
def meeting_events():
    return [json.loads(line) for line in (FIXTURES / "meeting-call.jsonl").read_text().splitlines()]


@pytest.fixture
def other_shapes():
    return json.loads((FIXTURES / "other-shapes.json").read_text())


@pytest.fixture(autouse=True)
def no_real_alerts(monkeypatch, tmp_path):
    """Tests never alert a real supervisor, whatever ALERT_TARGET says in .env."""
    import config
    monkeypatch.setattr(config, "ALERT_TARGET", "")
    monkeypatch.setattr(config, "ALERT_LOG", tmp_path / "alerts.jsonl")


@pytest.fixture
def load_fixture():
    def load(name):
        return [json.loads(line) for line in (FIXTURES / f"{name}.jsonl").read_text().splitlines()]
    return load
