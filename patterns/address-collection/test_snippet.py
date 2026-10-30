import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent)); sys.modules.pop("snippet", None)  # noqa: E702
from snippet import check_address, record_address  # noqa: E402


def acts(result, key):
    return [a[key] for a in result.to_dict().get("action", []) if key in a]


def test_partial_address_gives_the_missing_list():
    assert check_address({"street": "123 Main St", "city": "Springfield"})[1] == ["region", "postal"]


def test_invalid_parts_count_as_missing():
    valid, missing = check_address({"street": "Main St", "city": "Austin", "region": "Texas", "postal": "7870"})
    assert valid == {"city": "Austin"}
    assert missing == ["street", "region", "postal"]


def test_partial_call_stores_parts_and_does_not_advance():
    r = record_address({"city": "Austin", "postal": "78701"}, {"global_data": {}})
    assert acts(r, "set_global_data") == [{"address": {"city": "Austin", "postal": "78701"}}]
    assert acts(r, "change_step") == []
    assert "street, region" in r.to_dict()["response"]


def test_later_call_merges_with_saved_parts_and_advances():
    saved = {"global_data": {"address": {"city": "Austin", "postal": "78701"}}}
    r = record_address({"street": "123  Main St", "region": "tx"}, saved)
    assert acts(r, "set_global_data") == [{"address": {
        "street": "123 Main St", "city": "Austin", "region": "TX", "postal": "78701"}}]
    assert acts(r, "change_step") == ["confirm"]
