"""PortfolioExit agent tests — mock chat_json, exercise hold/sell + safety fallback."""

from __future__ import annotations

from unittest.mock import patch

from agents.portfolio_exit import decide
from cricket_data import LiveScore
from exit_monitor import PositionSnapshot
from llm import LlmResponse


def _snap(side: str = "yes", entry: int = 50, mark: int = 60) -> PositionSnapshot:
    return PositionSnapshot(
        ticker="KXIPLGAME-T",
        entry_price_cents=entry, mark_price_cents=mark,
        yes_count=100 if side == "yes" else 0,
        no_count=0 if side == "yes" else 100,
        side=side, opened_at=0, peak_pnl_cents=0,
    )


def _live() -> LiveScore:
    return LiveScore(
        match_id="m1", team_a="A", team_b="B",
        runs_a=180, wickets_a=5, overs_a="20.0",
        runs_b=120, wickets_b=4, overs_b="15.0",
        batting="team_b", target=181, required_run_rate=12.0,
        on_strike_batter=None, non_strike_batter=None, bowler=None, last_balls=[],
    )


def _llm_resp(parsed):
    return LlmResponse(content="(stub)", parsed_json=parsed,
                       model="test-model", latency_ms=10, raw={})


def test_happy_path_hold():
    parsed = {"action": "hold", "confidence": 0.7, "reasoning": "still on track"}
    with patch("agents.portfolio_exit.chat_json", return_value=_llm_resp(parsed)):
        ex = decide(_snap(), _live())
    assert ex.action == "hold"
    assert ex.trigger == "llm"


def test_happy_path_sell():
    parsed = {"action": "sell", "confidence": 0.8, "reasoning": "momentum reversal"}
    with patch("agents.portfolio_exit.chat_json", return_value=_llm_resp(parsed)):
        ex = decide(_snap(), _live())
    assert ex.action == "sell"
    assert ex.trigger == "llm"
    assert ex.note != ""


def test_fallback_when_llm_returns_none_holds():
    with patch("agents.portfolio_exit.chat_json", return_value=None):
        ex = decide(_snap(), _live())
    assert ex.action == "hold"
    assert "fallback" in ex.note.lower()


def test_fallback_on_malformed_json_holds():
    parsed = {"verdict": "exit"}   # wrong field
    with patch("agents.portfolio_exit.chat_json", return_value=_llm_resp(parsed)):
        ex = decide(_snap(), _live())
    assert ex.action == "hold"
    assert "fallback" in ex.note.lower()


def test_invalid_action_coerces_to_hold():
    parsed = {"action": "liquidate", "confidence": 0.9, "reasoning": "panic"}
    with patch("agents.portfolio_exit.chat_json", return_value=_llm_resp(parsed)):
        ex = decide(_snap(), _live())
    assert ex.action == "hold"
    assert "fallback" in ex.note.lower() or "invalid" in ex.note.lower()


def test_no_live_match_still_calls_llm():
    parsed = {"action": "hold", "confidence": 0.4, "reasoning": "no live ctx"}
    with patch("agents.portfolio_exit.chat_json", return_value=_llm_resp(parsed)) as cj:
        ex = decide(_snap(), live=None)
    assert ex.action == "hold"
    user_prompt = cj.call_args.kwargs["user"]
    assert "no live match" in user_prompt.lower()
