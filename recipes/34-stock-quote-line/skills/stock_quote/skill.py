"""stock_quote: a reusable SignalWire skill that speaks stock quotes.

Load it from any agent:

    signalwire.add_skill_directory("skills")          # or pip-install it (see README)
    agent.add_skill("stock_quote", {"provider": "mock"})

Params: provider (mock | alphavantage | finnhub), api_key, tool_name, watchlist,
mock_file, timeout. The skill owns the provider call, the API key and the
watchlist rule, so no agent that loads it can leak the key or quote outside
its list, whatever the prompt says.
"""
import json
import re
from pathlib import Path

import requests
from signalwire import FunctionResult
from signalwire.core.skill_base import SkillBase

BUNDLED_MOCK = Path(__file__).with_name("mock_quotes.json")
TICKER = re.compile(r"^[A-Z][A-Z.]{0,5}$")


class QuoteUnavailable(Exception):
    """The provider didn't answer, or answered with an error."""


def mock_quote(symbol, params):
    feed = json.loads(Path(params.get("mock_file") or BUNDLED_MOCK).read_text())
    q = feed.get(symbol)
    return q and {"symbol": symbol, "name": q.get("name"), "price": q["price"],
                  "change": q["change"], "change_pct": q["change_pct"]}


def alphavantage_quote(symbol, params):
    body = _get("https://www.alphavantage.co/query", params,
                {"function": "GLOBAL_QUOTE", "symbol": symbol, "apikey": params["api_key"]})
    if "Note" in body or "Information" in body or "Error Message" in body:
        raise QuoteUnavailable("alphavantage refused the request")
    q = body.get("Global Quote") or {}
    if not q.get("05. price"):
        return None
    return {"symbol": symbol, "name": None, "price": float(q["05. price"]),
            "change": float(q["09. change"]), "change_pct": float(q["10. change percent"].rstrip("%"))}


def finnhub_quote(symbol, params):
    q = _get("https://finnhub.io/api/v1/quote", params, {"symbol": symbol, "token": params["api_key"]})
    if not q.get("c"):            # Finnhub answers unknown symbols with all zeros
        return None
    return {"symbol": symbol, "name": None, "price": float(q["c"]),
            "change": float(q.get("d") or 0), "change_pct": float(q.get("dp") or 0)}


def _get(url, params, query):
    try:
        resp = requests.get(url, params=query, timeout=params.get("timeout", 5))
        resp.raise_for_status()
        return resp.json()
    except (requests.RequestException, ValueError) as exc:
        raise QuoteUnavailable(str(exc)) from None


PROVIDERS = {"mock": mock_quote, "alphavantage": alphavantage_quote, "finnhub": finnhub_quote}


def normalize_ticker(raw) -> str | None:
    symbol = re.sub(r"[\s\-]", "", str(raw or "")).upper()
    return symbol if TICKER.match(symbol) else None


def speak(q: dict) -> str:
    """Turn a quote into one sentence that reads well aloud."""
    letters = " ".join(q["symbol"])
    who = f"{q['name']}, ticker {letters}," if q.get("name") else letters
    if q["change"] == 0:
        move = "unchanged today"
    else:
        move = f"{'up' if q['change'] > 0 else 'down'} {abs(q['change']):.2f}, or {abs(q['change_pct']):.2f} percent, today"
    return f"{who} is at {q['price']:.2f} dollars, {move}."


class StockQuoteSkill(SkillBase):
    SKILL_NAME = "stock_quote"
    SKILL_DESCRIPTION = "Spoken stock quotes from a mock feed, Alpha Vantage or Finnhub"
    SKILL_VERSION = "1.0.0"
    REQUIRED_PACKAGES = ["requests"]
    REQUIRED_ENV_VARS: list = []
    SUPPORTS_MULTIPLE_INSTANCES = True

    @classmethod
    def get_parameter_schema(cls):
        schema = super().get_parameter_schema()
        schema["tool_name"]["default"] = "get_stock_quote"
        schema.update({
            "provider": {"type": "string", "description": "Where quotes come from", "default": "mock",
                         "enum": list(PROVIDERS), "required": False, "env_var": "MARKET_DATA_PROVIDER"},
            "api_key": {"type": "string", "description": "Market data API key (not needed for mock)",
                        "required": False, "hidden": True, "env_var": "MARKET_DATA_API_KEY"},
            "watchlist": {"type": "array", "description": "If set, only these tickers can be quoted",
                          "default": [], "required": False},
            "mock_file": {"type": "string", "description": "JSON quote feed for the mock provider",
                          "required": False},
            "timeout": {"type": "number", "description": "Provider timeout in seconds", "default": 5,
                        "required": False},
        })
        return schema

    def setup(self) -> bool:
        self.provider = str(self.params.get("provider") or "mock").lower()
        if self.provider not in PROVIDERS:
            self.logger.error("unknown provider %r; use one of %s", self.provider, list(PROVIDERS))
            return False
        if self.provider != "mock" and not self.params.get("api_key"):
            self.logger.error("provider %r needs an api_key", self.provider)
            return False
        self.tool_name = self.params.get("tool_name") or "get_stock_quote"
        self.watchlist = [s.upper() for s in self.params.get("watchlist") or []]
        return True

    def get_instance_key(self) -> str:
        return f"{self.SKILL_NAME}_{self.params.get('tool_name') or 'get_stock_quote'}"

    def register_tools(self) -> None:
        self.define_tool(
            name=self.tool_name,
            description="Get the latest price and today's change for one stock ticker symbol.",
            parameters={"ticker": {"type": "string", "description": "Ticker symbol, e.g. ACME"}},
            required=["ticker"],
            handler=self.quote,
            fillers={"en-US": ["Let me check that price.", "One moment while I pull that up."]},
        )

    def quote(self, args, raw_data):
        symbol = normalize_ticker(args.get("ticker"))
        if not symbol:
            return FunctionResult("That doesn't look like a ticker symbol. Ask the caller to spell it.")
        if self.watchlist and symbol not in self.watchlist:
            listed = ", ".join(" ".join(s) for s in self.watchlist)
            return FunctionResult(f"This line only quotes {listed}. Say so, and offer one of those.")
        try:
            q = PROVIDERS[self.provider](symbol, self.params)
        except QuoteUnavailable as exc:
            self.logger.warning("quote failed for %s: %s", symbol, exc)
            return FunctionResult("The quote service isn't answering right now. Apologize and offer to try again.")
        if not q:
            return FunctionResult(f"I couldn't find a quote for {' '.join(symbol)}. Ask the caller to check the symbol.")
        return FunctionResult(speak(q))

    def get_hints(self):
        return ["ticker", "stock", "quote", *self.watchlist]

    def _get_prompt_sections(self):
        return [{"title": "Stock quotes",
                 "body": f"When the caller asks for a share price, call {self.tool_name} with the ticker symbol. "
                         "Read the result as given. Never guess a price."}]
