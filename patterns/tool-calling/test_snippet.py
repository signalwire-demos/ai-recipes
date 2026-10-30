import json
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE)); sys.modules.pop("snippet", None)  # noqa: E702
from snippet import lookup_order  # noqa: E402


def test_known_order_speaks_and_sets_global_data():
    out = lookup_order({"order_id": "a 0101"}, {}).to_dict()
    assert out["response"] == "Order A-0101 is shipped."
    assert out["action"] == [{"set_global_data": {"order_id": "A-0101", "order_status": "shipped"}}]


def test_unknown_order_sets_nothing():
    out = lookup_order({"order_id": "Z-9999"}, {}).to_dict()
    assert "no order Z-9999" in out["response"]
    assert not out.get("action")


def test_tool_is_declared_with_typed_args_in_swml():
    exe = Path(sys.executable).with_name("swaig-test")
    exe = str(exe) if exe.exists() else shutil.which("swaig-test")
    swml = json.loads(subprocess.run([exe, str(HERE / "snippet.py"), "--dump-swml", "--raw"],
                                     capture_output=True, text=True, check=True, cwd=HERE).stdout)
    ai = next(v["ai"] for v in swml["sections"]["main"] if "ai" in v)
    fn = next(f for f in ai["SWAIG"]["functions"] if f["function"] == "lookup_order")
    assert fn["parameters"]["properties"]["order_id"]["type"] == "string"
    assert fn["parameters"]["required"] == ["order_id"]
