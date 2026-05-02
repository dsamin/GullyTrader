"""Researcher agent tests — mock chat_json, exercise prob extraction + fallbacks."""

from __future__ import annotations

from unittest.mock import patch

from agents.researcher import ResearchNote, research
from cricket_data import LiveScore
from kalshi_client import KalshiMarket
from llm import LlmResponse


def _market(ticker: str = "KXIPLGAME-26MAY07RCBLSG-LSG", yes: int = 50) -> KalshiMarket:
    return KalshiMarket(
        ticker=ticker, event_ticker=ticker.rsplit("-", 1)[0],
        title="LSG win", yes_price=yes, no_price=100 - yes, status="open",
    )


def _live() -> LiveScore:
    return LiveScore(
        match_id="m1", team_a="RCB", team_b="LSG",
        runs_a=160, wickets_a=4, overs_a="20.0",
        runs_b=82, wickets_b=3, overs_b="11.2",
        batting="team_b", target=161, required_run_rate=8.95,
        on_strike_batter={"name": "Pooran", "runs": 38, "balls": 22, "sr": 172.7},
        non_strike_batter={"name": "Stoinis", "runs": 12, "balls": 9, "sr": 133.3},
        bowler={"name": "Krunal", "overs": "2.2", "runs": 19, "wickets": 1, "economy": 8.14},
        last_balls=["1", "•", "4", "1", "W"],
    )


def _llm_resp(parsed):
    return LlmResponse(content="(stub)", parsed_json=parsed,
                       model="test-model", latency_ms=10, raw={})


def test_happy_path_extracts_probability_and_confidence():
    parsed = {"estimated_probability": 0.62, "confidence": 0.7,
              "reasoning": "LSG chasing well, RRR manageable, top 3 intact"}
    with patch("agents.researcher.chat_json", return_value=_llm_resp(parsed)):
        note = research(_market(yes=50), _live())
    assert isinstance(note, ResearchNote)
    assert note.estimated_yes_probability == 0.62
    assert note.confidence == 0.7
    assert "LSG" in note.reasoning


def test_fallback_when_llm_returns_none():
    with patch("agents.researcher.chat_json", return_value=None):
        note = research(_market(yes=55), _live())
    assert note.estimated_yes_probability == 0.55
    assert note.confidence == 0.0
    assert "fallback" in note.reasoning.lower()


def test_fallback_when_parsed_json_missing_estimated_probability():
    parsed = {"confidence": 0.4, "reasoning": "no probability field"}
    with patch("agents.researcher.chat_json", return_value=_llm_resp(parsed)):
        note = research(_market(yes=40), _live())
    assert note.estimated_yes_probability == 0.40
    assert note.confidence == 0.0
    assert "fallback" in note.reasoning.lower()


def test_fallback_when_parsed_json_is_not_a_dict():
    with patch("agents.researcher.chat_json", return_value=_llm_resp(["array", "instead"])):
        note = research(_market(yes=30), _live())
    assert note.estimated_yes_probability == 0.30
    assert note.confidence == 0.0


def test_probability_clamped_to_upper_bound():
    parsed = {"estimated_probability": 1.5, "confidence": 0.8, "reasoning": "over"}
    with patch("agents.researcher.chat_json", return_value=_llm_resp(parsed)):
        note = research(_market(yes=70), _live())
    assert note.estimated_yes_probability == 1.0
    assert note.confidence == 0.8


def test_probability_clamped_to_lower_bound():
    parsed = {"estimated_probability": -0.3, "confidence": 0.8, "reasoning": "under"}
    with patch("agents.researcher.chat_json", return_value=_llm_resp(parsed)):
        note = research(_market(yes=20), _live())
    assert note.estimated_yes_probability == 0.0
    assert note.confidence == 0.8


def test_works_with_no_live_match():
    parsed = {"estimated_probability": 0.45, "confidence": 0.5,
              "reasoning": "pre-game on form alone"}
    with patch("agents.researcher.chat_json", return_value=_llm_resp(parsed)) as cj:
        note = research(_market(yes=50), live=None)
    assert note.estimated_yes_probability == 0.45
    user_prompt = cj.call_args.kwargs["user"]
    assert "no live match" in user_prompt.lower()
