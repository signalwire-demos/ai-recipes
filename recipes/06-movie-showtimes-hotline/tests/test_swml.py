"""Tests for the showtimes hotline. There is no app: the recipe is showtimes.swml.yaml.

1. The file passes the SWML JSON Schema that ships in signalwire-sdk (scripts/validate_swml.py,
   the same check CI's swml-schema job runs).
2. get_showtimes' data_map runs through the SDK's DataMap simulator (the engine behind
   `swaig-test --exec`) against a local server that serves data/showtimes.json and the
   fixtures in tests/fixtures/, so each feed maps to the expected sentence with no network.
3. Governance: one tool, and nothing in the file points at a server you run.
"""
import copy
import json
import sys
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import yaml

RECIPE = Path(__file__).resolve().parents[1]
REPO = RECIPE.parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from signalwire.cli.execution.datamap_exec import execute_datamap_function  # noqa: E402
from validate_swml import VALIDATOR  # noqa: E402

SWML_FILE = RECIPE / "showtimes.swml.yaml"
FEED = RECIPE / "data" / "showtimes.json"
RAW_URL = ("https://raw.githubusercontent.com/signalwire-demos/ai-recipes/main/"
           "recipes/06-movie-showtimes-hotline/data/showtimes.json")
UNAVAILABLE = "The showtimes aren't available right now. Ask the caller to try again in a few minutes."


@pytest.fixture(scope="module")
def doc():
    return yaml.safe_load(SWML_FILE.read_text())


@pytest.fixture(scope="module")
def ai(doc):
    return next(v["ai"] for v in doc["sections"]["main"] if "ai" in v)


@pytest.fixture(scope="module")
def get_showtimes(ai):
    (fn,) = ai["SWAIG"]["functions"]
    return fn


# --- schema -----------------------------------------------------------------

def test_swml_passes_the_sdk_schema(doc):
    errors = [f"{'/'.join(map(str, e.path))}: {e.message[:200]}" for e in VALIDATOR.iter_errors(doc)]
    assert errors == []


def test_schema_check_is_not_a_rubber_stamp(doc):
    broken = copy.deepcopy(doc)
    broken["sections"]["main"][1]["ai"]["SWAIG"]["functions"][0]["data_map"]["webhooks"][0]["method"] = "FETCH"
    assert list(VALIDATOR.iter_errors(broken))


# --- the data_map against feed fixtures ---------------------------------------

class Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def local_base():
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(Quiet, directory=str(RECIPE)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


@pytest.fixture
def run(monkeypatch, get_showtimes, local_base):
    monkeypatch.setenv("SWML_ALLOW_PRIVATE_URLS", "true")  # the simulator blocks localhost otherwise

    def _run(feed_path: str) -> str:
        fn = copy.deepcopy(get_showtimes)
        fn["data_map"]["webhooks"][0]["url"] = f"{local_base}/{feed_path}"
        return execute_datamap_function(fn, {})["response"]
    return _run


def test_feed_renders_one_sentence_per_film(run):
    assert run("data/showtimes.json") == (
        "Today's showtimes: "
        "The Lighthouse at Gull Point, rated PG, 104 minutes, at 1:00 PM, 4:15 PM and 7:30 PM. "
        "Orbit of Nine, rated PG-13, 128 minutes, at 2:30 PM, 6:00 PM and 9:20 PM. "
        "Paper Kites, rated G, 88 minutes, at 11:00 AM, 1:30 PM and 3:45 PM. "
    )


def test_every_film_has_the_fields_the_template_reads(get_showtimes):
    append = get_showtimes["data_map"]["webhooks"][0]["foreach"]["append"]
    films = json.loads(FEED.read_text())["films"]
    assert len(films) == 3
    for film in films:
        for field in ("title", "rating", "runtime", "times"):
            assert f"${{this.{field}}}" in append
            assert film.get(field), f"{film.get('title')} has no {field}"


def test_empty_feed_says_no_showtimes(run):
    assert run("tests/fixtures/no-films.json").startswith("There are no showtimes listed for today.")


def test_error_key_uses_fallback(run):
    assert run("tests/fixtures/error.json") == UNAVAILABLE


def test_missing_feed_uses_fallback(run):
    assert run("tests/fixtures/does-not-exist.json") == UNAVAILABLE


def test_templates_read_the_response_from_the_root(get_showtimes):
    # ${response.x} renders empty on the platform; webhook output reads fields from the root.
    assert "${response." not in json.dumps(get_showtimes)


# --- governance: no server, one tool, the feed on main ------------------------

def test_governance_get_showtimes_is_the_only_tool(ai, get_showtimes):
    assert [f["function"] for f in ai["SWAIG"]["functions"]] == ["get_showtimes"]
    assert "data_map" in get_showtimes
    assert set(ai["SWAIG"]) == {"functions"}       # no includes, no defaults.web_hook_url


def test_governance_nothing_points_at_your_server(doc):
    text = SWML_FILE.read_text()
    for marker in ("web_hook_url", "post_prompt_url", "localhost", "ngrok", "execute:", "transfer:"):
        assert marker not in text
    urls = [w["url"] for f in doc["sections"]["main"][1]["ai"]["SWAIG"]["functions"]
            for w in f["data_map"]["webhooks"]]
    assert urls == [RAW_URL]


def test_raw_url_points_at_the_committed_feed():
    assert RAW_URL.endswith("/" + FEED.relative_to(REPO).as_posix())


def test_prompt_forbids_guessing(ai):
    assert "Never guess" in ai["prompt"]["text"]
    assert "Starlight Cinema" in ai["prompt"]["text"]
