"""Tests for the package tracking line.

track_package is a DataMap: there is no Python handler to call. So the tests
1. compare the DataMap JSON with a golden file (URL, headers, output mapping),
2. run it through the SDK's DataMap simulator (the same one `swaig-test --exec`
   uses) against a local HTTP server that serves the mock feed in data/mock-api/,
   so every recorded response maps to the expected sentence with no network,
3. prove nothing runs on this server: no handler, no per-function webhook URL.
"""
import json
import re
import shutil
import subprocess
import sys
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

RECIPE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RECIPE))

import config  # noqa: E402
from app import TrackingAgent, build_track_package  # noqa: E402
from signalwire.cli.execution.datamap_exec import execute_datamap_function  # noqa: E402

MOCK_DIR = RECIPE / "data" / "mock-api"
GOLDEN = RECIPE / "tests" / "golden" / "track_package.json"

EXPECTED = {
    "40010001": "Package 40010001 is in transit. It is on schedule to arrive Tuesday, "
                "November 3, by 8 PM. The last scan was in Tulsa, Oklahoma on Friday at 6:40 AM.",
    "40010002": "Package 40010002 is delivered. It was left at the front door and signed for "
                "by D. Example. The last scan was in Springfield, Missouri on Thursday at 2:15 PM.",
    "40010003": "Package 40010003 is delayed with a delivery exception. The address label was "
                "damaged. The carrier will contact the sender, and a new delivery date is not "
                "set yet. The last scan was in Wichita, Kansas on Wednesday at 11:05 AM.",
}


@pytest.fixture(autouse=True)
def default_config(monkeypatch):
    """Every test starts from the shipped defaults, whatever is in .env."""
    monkeypatch.setattr(config, "TRACKING_URL", config.MOCK_TRACKING_URL)
    monkeypatch.setattr(config, "TRACKING_API_KEY", "")


class FeedHandler(SimpleHTTPRequestHandler):
    """Serves data/mock-api/ like GitHub raw, plus one carrier-style error reply."""

    def do_GET(self):
        if self.path.startswith("/ERR"):
            body = b'{"error": "carrier unavailable"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()

    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def feed_url():
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(FeedHandler, directory=str(MOCK_DIR)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}/" + "${enc:args.tracking_number}.json"
    server.shutdown()


def run_datamap(monkeypatch, feed_url, number):
    monkeypatch.setenv("SWML_ALLOW_PRIVATE_URLS", "true")   # the simulator blocks localhost otherwise
    monkeypatch.setattr(config, "TRACKING_URL", feed_url)
    return execute_datamap_function(build_track_package().to_swaig_function(),
                                    {"tracking_number": number})["response"]


# --- the DataMap definition ---------------------------------------------------

def test_datamap_matches_golden_file():
    assert build_track_package().to_swaig_function() == json.loads(GOLDEN.read_text())


def test_default_url_is_the_public_mock_feed():
    (hook,) = build_track_package().to_swaig_function()["data_map"]["webhooks"]
    assert hook["method"] == "GET"
    assert hook["url"].startswith(
        "https://raw.githubusercontent.com/signalwire-demos/ai-recipes/main/"
        "recipes/05-package-tracking-line/data/mock-api/")
    assert "Authorization" not in hook["headers"]


def test_every_mock_has_the_fields_the_template_reads():
    fields = set(re.findall(r"\$\{(\w+)\}", config.OUTPUT_TEMPLATE))
    assert fields == {"status", "detail", "last_location", "last_scan"}
    mocks = sorted(MOCK_DIR.glob("*.json"))
    assert [m.stem for m in mocks] == sorted(EXPECTED)
    for mock in mocks:
        assert fields <= set(json.loads(mock.read_text())), mock.name


# --- recorded responses map to the expected sentence ---------------------------

@pytest.mark.parametrize("number", sorted(EXPECTED))
def test_mock_response_maps_to_sentence(monkeypatch, feed_url, number):
    assert run_datamap(monkeypatch, feed_url, number) == EXPECTED[number]


def test_unknown_number_uses_fallback(monkeypatch, feed_url):
    assert run_datamap(monkeypatch, feed_url, "99999999") == (
        "I couldn't find tracking number 99999999. "
        "Ask the caller to read it again, one digit at a time.")


def test_error_key_in_response_uses_fallback(monkeypatch, feed_url):
    assert run_datamap(monkeypatch, feed_url, "ERR1").startswith("I couldn't find")


# --- nothing runs on this server ------------------------------------------------

def swaig_test_bin() -> str:
    local = Path(sys.executable).with_name("swaig-test")
    return str(local) if local.exists() else (shutil.which("swaig-test") or "swaig-test")


@pytest.fixture(scope="module")
def swml():
    out = subprocess.run(
        [swaig_test_bin(), str(RECIPE / "app.py"), "--dump-swml", "--raw"],
        capture_output=True, text=True, check=True, cwd=RECIPE,
    ).stdout
    return json.loads(out)


def ai_of(swml_doc):
    return next(v["ai"] for v in swml_doc["sections"]["main"] if "ai" in v)


def test_governance_track_package_ships_as_data_map_with_no_webhook(swml):
    (fn,) = ai_of(swml)["SWAIG"]["functions"]
    assert fn["function"] == "track_package"
    assert "data_map" in fn
    assert "web_hook_url" not in fn       # the platform calls the carrier, not this app


def test_governance_no_python_handler_exists():
    agent = TrackingAgent()
    registered = agent._tool_registry._swaig_functions
    assert list(registered) == ["track_package"]
    # a plain dict definition, not a SWAIGFunction with a handler behind it
    assert isinstance(registered["track_package"], dict)
    # and if a request for it ever reached this server, the SDK would refuse to run it
    reply = agent._execute_swaig_function("track_package", {"tracking_number": "40010001"})
    assert "should be executed by SignalWire server" in reply["response"]


def test_api_key_goes_in_the_header_not_where_the_model_reads(monkeypatch):
    monkeypatch.setattr(config, "TRACKING_API_KEY", "test-key-0000")
    fn = build_track_package().to_swaig_function()
    assert fn["data_map"]["webhooks"][0]["headers"]["Authorization"] == "Bearer test-key-0000"
    assert "test-key-0000" not in json.dumps(fn["parameters"]) + fn["description"]


def test_readme_raw_swml_is_the_shipped_datamap():
    yaml = pytest.importorskip("yaml")
    block = re.search(r"```yaml\n(.*?)```", (RECIPE / "README.md").read_text(), re.S)[1]
    assert yaml.safe_load(block)["SWAIG"]["functions"] == [json.loads(GOLDEN.read_text())]
