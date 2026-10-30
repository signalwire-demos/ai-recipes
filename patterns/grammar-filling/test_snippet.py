import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent)); sys.modules.pop("snippet", None)  # noqa: E702
from snippet import fill, record_slots  # noqa: E402


def acts(result, key):
    return [a[key] for a in result.to_dict().get("action", []) if key in a]


def test_out_of_order_fills_merge_across_turns():
    turn1, missing1, _ = fill({}, {"crust": "Deep  Dish"})
    turn2, missing2, _ = fill(turn1, {"fulfillment": "pickup"})
    turn3, missing3, _ = fill(turn2, {"size": "large"})
    assert missing1 == ["fulfillment", "size"] and missing2 == ["size"] and missing3 == []
    assert turn3 == {"crust": "deep dish", "fulfillment": "pickup", "size": "large"}


def test_unknown_slots_and_blanks_are_ignored():
    merged, missing, problems = fill({"size": "small"}, {"topping": "ham", "crust": "", "size": None})
    assert merged == {"size": "small"} and problems == {}


def test_invalid_value_is_reported_and_keeps_the_old_value():
    merged, missing, problems = fill({"size": "small"}, {"size": "huge"})
    assert merged == {"size": "small"}
    assert problems == {"size": "choose small or medium or large"}


def test_missing_slot_gate_blocks_step_change():
    r = record_slots({"size": "medium", "crust": "gluten free"}, {"global_data": {}})
    assert acts(r, "change_step") == []
    assert acts(r, "set_global_data") == [{"order": {"size": "medium"}}]
    assert "fulfillment, crust (choose thin or hand tossed or deep dish)" in r.to_dict()["response"]


def test_last_slot_opens_the_gate():
    raw = {"global_data": {"order": {"size": "medium", "crust": "thin"}}}
    r = record_slots({"fulfillment": "delivery"}, raw)
    assert acts(r, "change_step") == ["confirm"]
    assert acts(r, "set_global_data") == [{"order": {"size": "medium", "crust": "thin", "fulfillment": "delivery"}}]
