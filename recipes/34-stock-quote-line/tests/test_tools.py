"""Tests: the stock_quote skill's schema, formatting, providers (with HTTP mocked),
error handling, and the two agents that load it with different params.
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import requests

os.environ.pop("MARKET_DATA_PROVIDER", None)   # tests run on the mock unless they say otherwise
os.environ.pop("MARKET_DATA_API_KEY", None)

RECIPE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RECIPE))

from app import QuoteLineAgent, StockPlanAgent  # noqa: E402
from signalwire import AgentBase  # noqa: E402
from skills.stock_quote import skill as sq  # noqa: E402

FAKE_KEY = "test-key-not-real"


def tool(agent, name):
    return agent._tool_registry._swaig_functions[name]


def run(agent, name, ticker):
    return tool(agent, name).handler({"ticker": ticker}, {}).to_dict()["response"]


def bare_agent(params):
    a = AgentBase(name="t", route="/t")
    a.add_skill("stock_quote", params)
    return a


class FakeResponse:
    def __init__(self, body, status=200):
        self.body, self.status_code = body, status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}")

    def json(self):
        return self.body


@pytest.fixture
def http(monkeypatch):
    """Replace requests.get; record what was asked for."""
    calls = []

    def install(body=None, exc=None):
        def fake_get(url, params=None, timeout=None):
            calls.append({"url": url, "params": params})
            if exc:
                raise exc
            return FakeResponse(body)
        monkeypatch.setattr(sq.requests, "get", fake_get)
        return calls
    return install


# --- schema and registration ---------------------------------------------------

def test_parameter_schema():
    schema = sq.StockQuoteSkill.get_parameter_schema()
    assert schema["provider"]["enum"] == ["mock", "alphavantage", "finnhub"]
    assert schema["api_key"]["hidden"] is True
    assert schema["tool_name"]["default"] == "get_stock_quote"


def test_skill_registers_its_tool_with_the_right_schema():
    fn = tool(QuoteLineAgent(), "get_stock_quote")
    assert fn.parameters == {"ticker": {"type": "string", "description": "Ticker symbol, e.g. ACME"}}
    assert fn.required == ["ticker"]


def test_paid_provider_without_key_fails_loudly():
    with pytest.raises(ValueError, match="stock_quote"):
        bare_agent({"provider": "finnhub"})
    with pytest.raises(ValueError):
        bare_agent({"provider": "bloomberg-terminal"})


# --- mock provider and speech -------------------------------------------------

def test_mock_quote_formats_to_speech():
    assert run(QuoteLineAgent(), "get_stock_quote", "acme") == \
        "Acme Corporation, ticker A C M E, is at 101.25 dollars, up 1.19, or 1.19 percent, today."


def test_spelled_out_ticker_and_down_and_flat_days():
    agent = QuoteLineAgent()
    assert "down 0.74, or 1.50 percent" in run(agent, "get_stock_quote", "g l b x")
    assert "unchanged today" in run(agent, "get_stock_quote", "INIT")


@pytest.mark.parametrize("ticker, expect", [
    ("", "doesn't look like a ticker"),
    ("12345", "doesn't look like a ticker"),
    ("what about apple shares", "doesn't look like a ticker"),
    ("ZZZZ", "couldn't find a quote for Z Z Z Z"),
])
def test_bad_ticker_is_handled_gracefully(ticker, expect):
    assert expect in run(QuoteLineAgent(), "get_stock_quote", ticker)


# --- real providers, HTTP mocked -------------------------------------------------

def test_alphavantage_adapter(http):
    calls = http({"Global Quote": {"01. symbol": "IBM", "05. price": "182.5000",
                                   "09. change": "-1.2500", "10. change percent": "-0.6803%"}})
    agent = bare_agent({"provider": "alphavantage", "api_key": FAKE_KEY})
    assert run(agent, "get_stock_quote", "ibm") == "I B M is at 182.50 dollars, down 1.25, or 0.68 percent, today."
    assert calls[0]["params"] == {"function": "GLOBAL_QUOTE", "symbol": "IBM", "apikey": FAKE_KEY}


def test_alphavantage_rate_limit_and_unknown(http):
    http({"Note": "Thank you for using Alpha Vantage! ... 5 calls per minute"})
    agent = bare_agent({"provider": "alphavantage", "api_key": FAKE_KEY})
    assert "isn't answering" in run(agent, "get_stock_quote", "IBM")
    http({"Global Quote": {}})
    assert "couldn't find" in run(agent, "get_stock_quote", "QQQQQ")


def test_finnhub_adapter(http):
    calls = http({"c": 211.3, "d": 2.1, "dp": 1.0037, "h": 212, "l": 209, "o": 209.5, "pc": 209.2})
    agent = bare_agent({"provider": "finnhub", "api_key": FAKE_KEY})
    assert run(agent, "get_stock_quote", "AAPL") == "A A P L is at 211.30 dollars, up 2.10, or 1.00 percent, today."
    assert calls[0]["url"] == "https://finnhub.io/api/v1/quote"
    http({"c": 0, "d": None, "dp": None, "h": 0, "l": 0, "o": 0, "pc": 0})
    assert "couldn't find" in run(agent, "get_stock_quote", "NOPE")


def test_network_failure_is_spoken_not_raised(http):
    http(exc=requests.ConnectionError("down"))
    agent = bare_agent({"provider": "finnhub", "api_key": FAKE_KEY})
    assert "isn't answering" in run(agent, "get_stock_quote", "AAPL")


# --- two agents, one skill ---------------------------------------------------------

def test_both_agents_run_the_same_skill_class():
    a, b = QuoteLineAgent(), StockPlanAgent()
    skill_a = tool(a, "get_stock_quote").handler.__self__
    skill_b = tool(b, "get_company_share_price").handler.__self__
    assert type(skill_a) is type(skill_b)          # one class, loaded once from skills/
    assert skill_a is not skill_b                   # two instances, two param sets
    assert Path(sys.modules[type(skill_a).__module__].__file__).resolve() == Path(sq.__file__).resolve()
    assert (skill_a.watchlist, skill_b.watchlist) == ([], ["ACME"])


def test_governance_stock_plan_line_only_quotes_its_watchlist():
    agent = StockPlanAgent()
    assert "A C M E" in run(agent, "get_company_share_price", "ACME")
    refused = run(agent, "get_company_share_price", "WAYN")
    assert "only quotes A C M E" in refused and "dollars" not in refused


def swaig_test_bin() -> str:
    local = Path(sys.executable).with_name("swaig-test")
    return str(local) if local.exists() else (shutil.which("swaig-test") or "swaig-test")


def dump(*extra, env=None):
    out = subprocess.run(
        [swaig_test_bin(), str(RECIPE / "app.py"), *extra, "--dump-swml", "--raw"],
        capture_output=True, text=True, check=True, cwd=RECIPE, env={**os.environ, **(env or {})},
    ).stdout
    return json.loads(out)


def functions(swml_doc):
    ai = next(v["ai"] for v in swml_doc["sections"]["main"] if "ai" in v)
    return [f["function"] for f in ai["SWAIG"]["functions"]]


def test_governance_each_agent_gets_only_its_own_tool():
    assert functions(dump()) == ["get_stock_quote"]
    assert functions(dump("--agent-class", "StockPlanAgent")) == ["get_company_share_price"]


def test_governance_api_key_never_reaches_the_swml():
    env = {"MARKET_DATA_PROVIDER": "finnhub", "MARKET_DATA_API_KEY": "sk-should-stay-server-side"}
    for extra in ((), ("--agent-class", "StockPlanAgent")):
        assert "sk-should-stay-server-side" not in json.dumps(dump(*extra, env=env))
