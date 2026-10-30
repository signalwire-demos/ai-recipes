"""Handler tests (direct calls, assertions on FunctionResult actions) plus governance
assertions on the SWML that swaig-test dumps. Wire names: swml_change_step() emits
{"change_step": ...}, update_global_data() emits {"set_global_data": ...}.
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

RECIPE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RECIPE))

import config  # noqa: E402
from app import DriveThruAgent  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_files(tmp_path, monkeypatch):
    stock = tmp_path / "stock.json"
    stock.write_text(json.dumps({
        "out_of_stock": ["onion_rings", "bacon", "milkshake"],
        "substitutes": {"onion_rings": ["fries"], "bacon": ["extra cheese"],
                        "milkshake": ["soda"], "chicken_sandwich": ["cheeseburger"]},
    }))
    monkeypatch.setattr(config, "STOCK_FILE", stock)
    monkeypatch.setattr(config, "ORDERS_FILE", tmp_path / "orders.jsonl")
    return tmp_path


@pytest.fixture(scope="module")
def agent():
    return DriveThruAgent()


def acts(result):
    return result.to_dict().get("action", [])


def find(actions, key):
    return [a[key] for a in actions if key in a]


def gd(order=None, **extra):
    return {"global_data": {"order": order or [], **extra}, "call_id": "test-call"}


def placed(agent, **args):
    """Add one line and return the resulting order."""
    return find(acts(agent.add_item(args, gd())), "set_global_data")[0]["order"]


# --- add_item / menu validation ----------------------------------------------------

def test_add_item_prices_line_in_code(agent):
    result = agent.add_item({"item": "cheeseburger", "size": "double", "quantity": 2,
                             "modifiers": ["extra cheese"]}, gd())
    order = find(acts(result), "set_global_data")[0]["order"]
    assert order == [{"item": "cheeseburger", "size": "double", "modifiers": ["extra cheese"], "quantity": 2}]
    assert "$13.98" in result.to_dict()["response"]   # (6.49 + 0.50) x 2
    assert find(acts(result), "change_step") == []      # stays in take_order


def test_single_size_item_defaults_size(agent):
    assert placed(agent, item="chicken_sandwich")[0]["size"] == "regular"


@pytest.mark.parametrize("args, says", [
    ({"item": "pizza"}, "isn't on the menu"),
    ({"item": "fries", "size": "jumbo"}, "comes in small, medium, large"),
    ({"item": "fries", "size": "large", "modifiers": ["extra cheese"]}, "isn't an option on Fries"),
    ({"item": "soda", "size": "large", "quantity": 50}, "Quantity must be"),
    ({"item": "burger_combo", "size": "large", "side": "salad", "drink": "soda"}, "combo side"),
])
def test_invalid_lines_are_rejected(agent, args, says):
    result = agent.add_item(args, gd())
    assert acts(result) == []
    assert says in result.to_dict()["response"]


# --- stock-outs ----------------------------------------------------------------------

def test_stock_out_jumps_to_substitute_offer(agent):
    result = agent.add_item({"item": "burger_combo", "size": "large", "side": "onion_rings",
                             "drink": "soda"}, gd())
    assert find(acts(result), "change_step") == ["substitute_offer"]
    pending = find(acts(result), "set_global_data")[0]["pending"]
    assert pending["token"] == "onion_rings" and pending["options"] == ["fries"]
    assert "order" not in find(acts(result), "set_global_data")[0]   # nothing added yet


def test_out_of_stock_substitute_is_never_offered(agent, isolated_files):
    (isolated_files / "stock.json").write_text(json.dumps(
        {"out_of_stock": ["milkshake", "soda"], "substitutes": {"milkshake": ["soda"]}}))
    result = agent.add_item({"item": "milkshake"}, gd())
    assert acts(result) == []                      # no jump, nothing added
    assert "no substitute" in result.to_dict()["response"]


def test_accept_substitute_adds_line_and_returns(agent):
    jump = agent.add_item({"item": "burger_combo", "size": "large", "side": "onion_rings",
                           "drink": "soda", "modifiers": ["bacon"]}, gd())
    pending = find(acts(jump), "set_global_data")[0]["pending"]
    result = agent.accept_substitute({"choice": "fries"}, gd(pending=pending))
    # bacon is out too, so the second stock-out jumps again with the fixed side kept
    again = find(acts(result), "set_global_data")[0]["pending"]
    assert again["token"] == "bacon" and again["line"]["side"] == "fries"
    final = agent.accept_substitute({"choice": "extra cheese"}, gd(pending=again))
    order = find(acts(final), "set_global_data")[0]["order"]
    assert order[0]["side"] == "fries" and order[0]["modifiers"] == ["extra cheese"]
    assert find(acts(final), "change_step") == ["take_order"]


def test_accept_substitute_rejects_unoffered_choice(agent):
    pending = {"line": {"item": "milkshake", "size": "regular", "modifiers": [], "quantity": 1},
               "token": "milkshake", "options": ["soda"], "replace": None}
    result = agent.accept_substitute({"choice": "cheeseburger"}, gd(pending=pending))
    assert acts(result) == []


def test_decline_substitute_clears_pending(agent):
    result = agent.decline_substitute({}, gd(pending={"token": "x"}))
    assert find(acts(result), "unset_global_data") == [["pending"]]
    assert find(acts(result), "change_step") == ["take_order"]


# --- modify / remove -----------------------------------------------------------------

def test_modify_item_revalidates(agent):
    order = placed(agent, item="fries", size="small")
    ok = agent.modify_item({"line": 1, "size": "large", "add_modifiers": ["no salt"]}, gd(order))
    assert find(acts(ok), "set_global_data")[0]["order"][0] == \
        {"item": "fries", "size": "large", "modifiers": ["no salt"], "quantity": 1}
    bad = agent.modify_item({"line": 1, "add_modifiers": ["whipped cream"]}, gd(order))
    assert acts(bad) == []
    assert acts(agent.modify_item({"line": 7}, gd(order))) == []


def test_modify_into_stock_out_jumps(agent):
    order = placed(agent, item="cheeseburger", size="single")
    result = agent.modify_item({"line": 1, "add_modifiers": ["bacon"]}, gd(order))
    assert find(acts(result), "change_step") == ["substitute_offer"]
    assert find(acts(result), "set_global_data")[0]["pending"]["replace"] == 0


def test_remove_item(agent):
    order = placed(agent, item="fries", size="small")
    result = agent.remove_item({"line": 1}, gd(order))
    assert find(acts(result), "set_global_data") == [{"order": []}]


# --- finish / confirm: the total is menu math ----------------------------------------

def test_total_matches_menu_math_including_tax(agent):
    order = [
        {"item": "burger_combo", "size": "large", "modifiers": ["extra cheese"], "quantity": 2,
         "side": "fries", "drink": "soda"},          # (9.49 + 0.50) x 2 = 19.98
        {"item": "soda", "size": "small", "modifiers": [], "quantity": 1},   # 1.49
    ]
    result = agent.finish_order({}, gd(order))
    data = find(acts(result), "set_global_data")[0]
    # subtotal 21.47; tax 21.47 x 0.0825 = 1.771275 -> 1.77; total 23.24
    assert (data["subtotal"], data["tax"], data["total"]) == ("$21.47", "$1.77", "$23.24")
    assert data["readback"].startswith("1. 2 large Cheeseburger Combo, Fries, Soda, extra cheese")
    assert find(acts(result), "change_step") == ["confirm"]


def test_finish_empty_order_stays(agent):
    assert acts(agent.finish_order({}, gd())) == []


def test_confirm_order_writes_record(agent, isolated_files):
    order = placed(agent, item="soda", size="large")
    result = agent.confirm_order({}, gd(order))
    assert find(acts(result), "change_step") == ["done"]
    record = json.loads((isolated_files / "orders.jsonl").read_text())
    assert record["total"] == "$2.26" and record["call_id"] == "test-call"   # 2.09 + 0.17 tax


def test_change_order_goes_back(agent):
    assert find(acts(agent.change_order({}, gd())), "change_step") == ["take_order"]


# --- governance: read the SWML exactly as swaig-test dumps it ----------------------

@pytest.fixture(scope="module")
def steps():
    local = Path(sys.executable).with_name("swaig-test")
    exe = str(local) if local.exists() else (shutil.which("swaig-test") or "swaig-test")
    out = subprocess.run([exe, str(RECIPE / "app.py"), "--dump-swml", "--raw"],
                         capture_output=True, text=True, check=True, cwd=RECIPE).stdout
    ai = next(v["ai"] for v in json.loads(out)["sections"]["main"] if "ai" in v)
    return {s["name"]: s for s in ai["prompt"]["contexts"]["default"]["steps"]}


def test_governance_substitute_offer_cannot_add_items(steps):
    assert steps["substitute_offer"]["functions"] == ["accept_substitute", "decline_substitute"]
    assert "add_item" not in steps["confirm"]["functions"]
    assert steps["done"]["functions"] == []


def test_governance_only_handlers_move_the_call(steps):
    for name in ("take_order", "substitute_offer", "confirm"):
        assert steps[name]["valid_steps"] == []


def test_governance_prices_are_not_in_the_prompt():
    agent = DriveThruAgent()
    prompt = json.dumps(agent.get_prompt())
    assert "449" not in prompt and "$" not in prompt
