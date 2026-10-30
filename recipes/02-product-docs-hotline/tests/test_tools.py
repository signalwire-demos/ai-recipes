"""Tests for the docs hotline.

1. The search tool, called exactly as a live call would call it (agent.on_function_call),
   against the committed index: known questions return the right chunk, off-topic ones
   return the NOT_IN_DOCS marker.
2. grounded_only(), the threshold gate, on hand-made results.
3. Governance against the SWML that swaig-test dumps: search_docs is the only tool.
4. The committed index covers every file in docs/ (catches a forgotten `make index`).
"""
import json
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

RECIPE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RECIPE))

import config  # noqa: E402
from app import DocsHotline, grounded_only  # noqa: E402


@pytest.fixture(scope="module")
def agent():
    return DocsHotline()


# --- the search tool against the real index -------------------------------

@pytest.mark.parametrize("question, expected_file, expected_text", [
    ("How do I point a phone number at my agent?", "02-phone-numbers.md", "SWML webhook"),
    ("What is 10DLC registration?", "13-messaging-10dlc.md", "10-digit long code"),
    ("Can I run SWML without my own server?", "04-swml-scripts.md", "stored in your Space"),
    ("How do I test my agent without making a phone call?", "10-testing-with-swaig-test.md", "swaig-test"),
])
def test_known_question_returns_expected_chunk(agent, question, expected_file, expected_text):
    response = agent.search(question)
    assert response.startswith("Docs excerpts. Answer only from these:")
    first_excerpt = response.split(":\n\n", 1)[1]
    assert first_excerpt.startswith(f"[{expected_file}]")
    assert expected_text in response


@pytest.mark.parametrize("question", [
    "What is the capital of France?",
    "Give me a recipe for chocolate cake.",
    "What states do you serve?",          # keyword-only hit on "states": must still be refused
    "What's the weather tomorrow?",
])
def test_out_of_scope_question_returns_not_in_docs(agent, question):
    assert agent.search(question) == config.NOT_IN_DOCS


def test_empty_query_is_rejected(agent):
    assert "provide a search query" in agent.search("   ")


# --- the gate itself -------------------------------------------------------

def result(score, name="a.md", content="text", vector=True):
    r = {"content": content, "metadata": {"filename": name}, "final_score": score}
    if vector:
        r["vector_score"] = score
    return r


def test_gate_drops_weak_and_keyword_only_results():
    out = grounded_only("ignored", [result(0.7, "good.md", "keep me"),
                                    result(0.2, "weak.md"),
                                    result(0.9, "kw.md", vector=False)])
    assert "[good.md] keep me" in out
    assert "weak.md" not in out and "kw.md" not in out


def test_gate_returns_marker_when_nothing_passes():
    assert grounded_only("ignored", [result(0.1)]) == config.NOT_IN_DOCS
    assert grounded_only("ignored", []) == config.NOT_IN_DOCS


def test_gate_truncates_long_chunks():
    out = grounded_only("ignored", [result(0.8, content="z" * 5000)])
    assert out.count("z") == config.MAX_CHUNK_CHARS


# --- governance: the SWML exactly as swaig-test dumps it -------------------

def swaig_test_bin() -> str:
    local = Path(sys.executable).with_name("swaig-test")
    return str(local) if local.exists() else (shutil.which("swaig-test") or "swaig-test")


@pytest.fixture(scope="module")
def ai_verb():
    out = subprocess.run(
        [swaig_test_bin(), str(RECIPE / "app.py"), "--dump-swml", "--raw"],
        capture_output=True, text=True, check=True, cwd=RECIPE,
    ).stdout
    return next(v["ai"] for v in json.loads(out)["sections"]["main"] if "ai" in v)


def test_governance_search_is_the_only_tool(ai_verb):
    names = [f["function"] for f in ai_verb["SWAIG"]["functions"]]
    assert names == [config.SEARCH_TOOL]
    assert not ai_verb["SWAIG"].get("native_functions")
    assert not ai_verb["SWAIG"].get("includes")


def test_governance_prompt_forbids_model_knowledge(ai_verb):
    text = json.dumps(ai_verb["prompt"])
    assert "Never answer from your own knowledge" in text
    assert config.REFUSAL in text
    assert "another knowledge source" not in text  # the skill's default advice is replaced


# --- the committed index ---------------------------------------------------

def test_index_is_committed_small_and_covers_every_doc():
    assert config.INDEX_FILE.is_file(), "run `make index`"
    assert config.INDEX_FILE.stat().st_size < 5 * 1024 * 1024
    with sqlite3.connect(config.INDEX_FILE) as db:
        indexed = {row[0] for row in db.execute("SELECT DISTINCT filename FROM chunks")}
    on_disk = {p.name for p in config.DOCS_DIR.glob("*.md")}
    assert {Path(f).name for f in indexed} == on_disk, "docs/ changed: run `make index`"
