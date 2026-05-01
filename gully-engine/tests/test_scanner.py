"""Scanner agent tests — mock the LLM client, exercise happy paths and shape resilience."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from agents.scanner import ScanCandidate, shortlist
from kalshi_client import KalshiMarket
from llm import LlmResponse


def _market(ticker: str, yes: int = 50, title: str = "test") -> KalshiMarket:
    return KalshiMarket(
        ticker=ticker, event_ticker=ticker.rsplit("-", 1)[0],
        title=title, yes_price=yes, no_price=100 - yes,
        status="open",
    )


@pytest.fixture
def stub_feed():
    """Pin cricket_data.get_feed to a tiny mock so the scanner doesn't try to hit CricAPI."""
    with patch("agents.scanner.get_feed") as gf:
        gf.return_value.live_match.return_value = None
        yield gf


def _llm_resp(parsed):
    return LlmResponse(
        content="(stub)", parsed_json=parsed,
        model="test-model", latency_ms=10, raw={},
    )


def test_returns_empty_for_empty_market_list(stub_feed):
    assert shortlist([]) == []


def test_happy_path_returns_ranked_candidates(stub_feed):
    markets = [
        _market("KXIPLGAME-26MAY07RCBLSG-LSG"),
        _market("KXIPLGAME-26MAY07RCBLSG-RCB"),
        _market("KXIPLGAME-26MAY06PBKSSRH-PBKS"),
    ]
    parsed = {
        "candidates": [
            {"ticker": "KXIPLGAME-26MAY07RCBLSG-LSG", "score": 78, "reason": "underpriced underdog"},
            {"ticker": "KXIPLGAME-26MAY07RCBLSG-RCB", "score": 65, "reason": "overhyped favorite"},
            {"ticker": "KXIPLGAME-26MAY06PBKSSRH-PBKS", "score": 42, "reason": "form mismatch"},
        ]
    }
    with patch("agents.scanner.chat_json", return_value=_llm_resp(parsed)):
        result = shortlist(markets, max_results=5)

    assert len(result) == 3
    assert result[0].ticker == "KXIPLGAME-26MAY07RCBLSG-LSG"
    assert result[0].score == 78
    assert "underpriced" in result[0].reason
    assert all(isinstance(c, ScanCandidate) for c in result)


def test_drops_low_scoring_candidates_below_30(stub_feed):
    markets = [_market("a"), _market("b")]
    parsed = {
        "candidates": [
            {"ticker": "a", "score": 75, "reason": "good"},
            {"ticker": "b", "score": 18, "reason": "skip"},   # below threshold
        ]
    }
    with patch("agents.scanner.chat_json", return_value=_llm_resp(parsed)):
        result = shortlist(markets)
    assert [c.ticker for c in result] == ["a"]


def test_drops_unknown_tickers_returned_by_llm(stub_feed):
    """LLM hallucinated a ticker not in our market list — must be filtered out."""
    markets = [_market("real-ticker")]
    parsed = {
        "candidates": [
            {"ticker": "hallucinated-ticker", "score": 99, "reason": "ghost"},
            {"ticker": "real-ticker", "score": 60, "reason": "ok"},
        ]
    }
    with patch("agents.scanner.chat_json", return_value=_llm_resp(parsed)):
        result = shortlist(markets)
    assert len(result) == 1
    assert result[0].ticker == "real-ticker"


def test_caps_at_max_results(stub_feed):
    markets = [_market(f"t{i}") for i in range(10)]
    parsed = {
        "candidates": [{"ticker": f"t{i}", "score": 50 + i, "reason": ""} for i in range(10)]
    }
    with patch("agents.scanner.chat_json", return_value=_llm_resp(parsed)):
        result = shortlist(markets, max_results=3)
    assert len(result) == 3


def test_clamps_score_to_0_100(stub_feed):
    markets = [_market("a"), _market("b")]
    parsed = {
        "candidates": [
            {"ticker": "a", "score": 250, "reason": "over"},
            {"ticker": "b", "score": -5, "reason": "under"},   # < 30 threshold drops it anyway
        ]
    }
    with patch("agents.scanner.chat_json", return_value=_llm_resp(parsed)):
        result = shortlist(markets)
    assert result[0].score == 100
    assert len(result) == 1   # b dropped by < 30 threshold


def test_falls_back_when_llm_returns_none(stub_feed):
    """LLM unreachable → return first N markets with score 0 so pipeline keeps moving."""
    markets = [_market(f"t{i}") for i in range(5)]
    with patch("agents.scanner.chat_json", return_value=None):
        result = shortlist(markets, max_results=3)
    assert len(result) == 3
    assert all(c.score == 0 for c in result)
    assert all("fallback" in c.reason.lower() for c in result)


def test_falls_back_on_malformed_candidates_field(stub_feed):
    markets = [_market("a"), _market("b")]
    parsed = {"candidates": "not a list"}
    with patch("agents.scanner.chat_json", return_value=_llm_resp(parsed)):
        result = shortlist(markets, max_results=3)
    assert len(result) == 2
    assert all("fallback" in c.reason.lower() for c in result)


def test_skips_non_dict_candidate_entries(stub_feed):
    markets = [_market("a"), _market("b")]
    parsed = {
        "candidates": [
            "not a dict",
            None,
            {"ticker": "a", "score": 60, "reason": "ok"},
        ]
    }
    with patch("agents.scanner.chat_json", return_value=_llm_resp(parsed)):
        result = shortlist(markets)
    assert len(result) == 1
    assert result[0].ticker == "a"
