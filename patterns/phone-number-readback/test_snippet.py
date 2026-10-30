import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent)); sys.modules.pop("snippet", None)  # noqa: E702
from snippet import readback, record_phone, to_e164  # noqa: E402

SPOKEN = [
    "2125550142", "212-555-0142", "(212) 555-0142", "+1 212 555 0142", "1 212 555 0142",
    "two one two five five five oh one four two", "two one two, triple five, zero one four two",
    "my number is 212 555 oh one four two", "plus one two one two double five five 0142",
]


@pytest.mark.parametrize("spoken", SPOKEN)
def test_many_spoken_forms_normalize_to_one_e164(spoken):
    assert to_e164(spoken) == "+12125550142"


@pytest.mark.parametrize("spoken", ["555 0142", "212 555 01422", "012 555 0142", "", "call me later"])
def test_incomplete_or_invalid_numbers_are_rejected(spoken):
    assert to_e164(spoken) is None


def test_readback_is_in_digit_groups():
    assert readback("+12125550142") == "2 1 2, 5 5 5, 0 1 4 2"


def gd(result):
    return [a["set_global_data"] for a in result.to_dict().get("action", []) if "set_global_data" in a]


def test_first_call_reads_back_and_only_stores_pending():
    r = record_phone({"number": "two one two triple five oh one four two"}, {"global_data": {}})
    assert "2 1 2, 5 5 5, 0 1 4 2" in r.to_dict()["response"]
    assert gd(r) == [{"phone_pending": "+12125550142"}]


def test_confirmed_true_without_a_readback_does_not_store():
    r = record_phone({"number": "2125550142", "confirmed": True}, {"global_data": {}})
    assert gd(r) == [{"phone_pending": "+12125550142"}]   # reads back instead of saving


def test_confirmed_after_readback_stores_e164():
    raw = {"global_data": {"phone_pending": "+12125550142"}}
    r = record_phone({"number": "212 555 0142", "confirmed": True}, raw)
    assert gd(r) == [{"phone": "+12125550142", "phone_pending": None}]


def test_bad_number_stores_nothing():
    r = record_phone({"number": "555"}, {})
    assert gd(r) == [] and "10-digit" in r.to_dict()["response"]
