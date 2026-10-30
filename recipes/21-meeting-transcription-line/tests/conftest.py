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
