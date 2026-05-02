"""Orchestrator wiring tests — mock all external services and agents.

Verifies the shadow/live gate around place_limit_order in both pipelines
and that the exit pipeline fetches real mark prices via get_market.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import orchestrator
from agents.decision import TradeDecision
from agents.researcher import ResearchNote
from exit_monitor import ExitDecision
from kalshi_client import KalshiMarket, KalshiPosition


def _set_settings(**overrides):
    """Override frozen Settings dataclass for the duration of a test."""
    from settings import settings as _settings
    originals = {k: getattr(_settings, k) for k in overrides}
    for k, v in overrides.items():
        object.__setattr__(_settings, k, v)
    def restore():
        for k, v in originals.items():
            object.__setattr__(_settings, k, v)
    return restore


def _market(ticker: str = "KXIPLGAME-T", yes: int = 50) -> KalshiMarket:
    return KalshiMarket(
        ticker=ticker, event_ticker=ticker, title="t",
        yes_price=yes, no_price=100 - yes, status="open",
    )


def _position(ticker: str = "KXIPLGAME-T", side: str = "yes") -> KalshiPosition:
    return KalshiPosition(
        ticker=ticker,
        yes_count=100 if side == "yes" else 0,
        no_count=0 if side == "yes" else 100,
        avg_cost_cents=50,
        market_exposure_cents=5000,
    )


# ── Entry pipeline ─────────────────────────────────────────────────────


def test_entry_shadow_mode_does_not_place_order():
    restore = _set_settings(decision_mode="shadow")
    try:
        client = MagicMock()
        client.list_ipl_markets.return_value = [_market(yes=40)]
        client.get_balance.return_value = {"balance": 100_000}
        client.place_limit_order = MagicMock()

        with patch("orchestrator.KalshiClient", return_value=client), \
             patch("orchestrator.get_feed") as gf, \
             patch("orchestrator.scanner_shortlist") as sc, \
             patch("orchestrator.research") as rs, \
             patch("orchestrator.decide") as dc:
            gf.return_value.live_match.return_value = None
            sc.return_value = [MagicMock(ticker="KXIPLGAME-T", score=80, reason="ok")]
            rs.return_value = ResearchNote("KXIPLGAME-T", 0.7, 0.6, "yes")
            dc.return_value = TradeDecision("KXIPLGAME-T", "buy_yes", 5, 41, "edge")
            result = orchestrator.run_entry_pipeline_once(force=True)

        assert result["status"] == "ok"
        assert result["decision_mode"] == "shadow"
        client.place_limit_order.assert_not_called()
        assert result["candidates"][0]["decision"]["action"] == "buy_yes"
        assert result["candidates"][0]["order"] is None
    finally:
        restore()


def test_entry_live_mode_places_order_on_buy():
    restore = _set_settings(decision_mode="live")
    try:
        client = MagicMock()
        client.list_ipl_markets.return_value = [_market(yes=40)]
        client.get_balance.return_value = {"balance": 100_000}
        client.place_limit_order.return_value = {"order_id": "o-1", "status": "queued"}

        with patch("orchestrator.KalshiClient", return_value=client), \
             patch("orchestrator.get_feed") as gf, \
             patch("orchestrator.scanner_shortlist") as sc, \
             patch("orchestrator.research") as rs, \
             patch("orchestrator.decide") as dc:
            gf.return_value.live_match.return_value = None
            sc.return_value = [MagicMock(ticker="KXIPLGAME-T", score=80, reason="ok")]
            rs.return_value = ResearchNote("KXIPLGAME-T", 0.7, 0.6, "yes")
            dc.return_value = TradeDecision("KXIPLGAME-T", "buy_yes", 5, 41, "edge")
            result = orchestrator.run_entry_pipeline_once(force=True)

        client.place_limit_order.assert_called_once_with(
            ticker="KXIPLGAME-T", side="yes", action="buy",
            count=5, limit_price_cents=41,
        )
        assert result["candidates"][0]["order"] == {"order_id": "o-1", "status": "queued"}
    finally:
        restore()


def test_entry_live_mode_does_not_place_order_on_pass():
    restore = _set_settings(decision_mode="live")
    try:
        client = MagicMock()
        client.list_ipl_markets.return_value = [_market(yes=50)]
        client.get_balance.return_value = {"balance": 100_000}
        client.place_limit_order = MagicMock()

        with patch("orchestrator.KalshiClient", return_value=client), \
             patch("orchestrator.get_feed") as gf, \
             patch("orchestrator.scanner_shortlist") as sc, \
             patch("orchestrator.research") as rs, \
             patch("orchestrator.decide") as dc:
            gf.return_value.live_match.return_value = None
            sc.return_value = [MagicMock(ticker="KXIPLGAME-T", score=80, reason="ok")]
            rs.return_value = ResearchNote("KXIPLGAME-T", 0.51, 0.6, "low edge")
            dc.return_value = TradeDecision("KXIPLGAME-T", "pass", 0, 50, "edge too low")
            result = orchestrator.run_entry_pipeline_once(force=True)

        client.place_limit_order.assert_not_called()
        assert result["candidates"][0]["decision"]["action"] == "pass"
    finally:
        restore()
