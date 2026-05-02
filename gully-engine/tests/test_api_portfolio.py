"""Integration tests for /api/portfolio, /api/positions, /api/trades.

Mounts the FastAPI app via TestClient, mocks KalshiClient (so we don't talk
to Kalshi or hit the file system for keys), and pre-seeds the DB so the
real DB-derived metrics are exercised end-to-end.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

import database
from kalshi_client import KalshiMarket, KalshiPosition


@pytest.fixture
def app_client(tmp_path: Path):
    """Build a FastAPI TestClient with an isolated tmp DB."""
    from settings import settings as _settings
    db_path = tmp_path / "test.db"
    original = _settings.db_path
    object.__setattr__(_settings, "db_path", db_path)
    try:
        database.initialize(db_path)
        # Import here so the app picks up the patched settings
        import importlib

        import main
        importlib.reload(main)
        with TestClient(main.app) as client:
            yield client, db_path
    finally:
        object.__setattr__(_settings, "db_path", original)


def _seed_settlement(conn, ticker, net_pnl, cost=1_000, settled_at=1_777_852_800,
                     market_result="yes"):
    revenue = cost + net_pnl
    conn.execute(
        """INSERT INTO settlements
           (ticker, market_result, revenue_cents, cost_cents, net_pnl_cents, settled_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (ticker, market_result, revenue, cost, net_pnl, settled_at),
    )


def _seed_fill(conn, trade_id, ticker, count=10, price=50, side="yes",
               action="buy", filled_at=1_777_852_800):
    conn.execute(
        """INSERT INTO fills
           (kalshi_trade_id, kalshi_order_id, ticker, side, action,
            count, price_cents, is_taker, filled_at)
           VALUES (?, 'ord-x', ?, ?, ?, ?, ?, 1, ?)""",
        (trade_id, ticker, side, action, count, price, filled_at),
    )


# ── /api/portfolio ─────────────────────────────────────────────────────


def test_api_portfolio_uses_db_derived_metrics_not_hardcoded(app_client):
    client, db_path = app_client
    with database.write_conn() as conn:
        _seed_settlement(conn, "a", net_pnl=2_000, cost=10_000)   # ROI +20%, win
        _seed_settlement(conn, "b", net_pnl=-500,  cost=5_000)    # ROI -10%, loss

    fake_kalshi = MagicMock()
    fake_kalshi.get_balance.return_value = {"balance": 500_00, "portfolio_value": 600_00}

    with patch("main.KalshiClient", return_value=fake_kalshi):
        resp = client.get("/api/portfolio")
    assert resp.status_code == 200
    data = resp.json()

    assert data["balance_cents"] == 500_00
    assert data["portfolio_value_cents"] == 600_00
    # Real metrics — NOT the old hardcoded 8.42, 32.4, 68
    assert data["wagered_cents"] == 15_000
    assert data["win_rate_pct"] == 50         # 1 win out of 2
    assert data["roi_pct"] == pytest.approx(10.0, abs=0.01)
    # Streak ordered oldest → newest. Both seeds have same settled_at → SQLite
    # returns them in insertion-id order; just assert membership.
    assert sorted(data["streak_last_10"]) == ["L", "W"]
    assert isinstance(data["spark_20d"], list) and len(data["spark_20d"]) == 20


# ── /api/trades ────────────────────────────────────────────────────────


def test_api_trades_returns_recent_fills(app_client):
    client, db_path = app_client
    with database.write_conn() as conn:
        _seed_fill(conn, "t1", "T-A", count=10, price=42, filled_at=1_000)
        _seed_fill(conn, "t2", "T-B", count=20, price=55, filled_at=2_000)
        _seed_fill(conn, "t3", "T-A", count= 5, price=43, filled_at=3_000)

    resp = client.get("/api/trades")
    assert resp.status_code == 200
    data = resp.json()

    # Newest first
    assert [f["trade_id"] for f in data["trades"]] == ["t3", "t2", "t1"]
    assert data["trades"][0]["ticker"] == "T-A"
    assert data["trades"][0]["price_cents"] == 43
    assert data["trades"][0]["count"] == 5


def test_api_trades_returns_empty_when_no_fills(app_client):
    client, _ = app_client
    resp = client.get("/api/trades")
    assert resp.status_code == 200
    assert resp.json() == {"trades": []}


# ── /api/positions ─────────────────────────────────────────────────────


def test_api_positions_uses_real_market_prices_for_mark(app_client):
    """The synthetic 'avg_cost +/- 8 if MUM in ticker' fudge is gone — the
    mark must come from KalshiClient.get_market(ticker)."""
    client, _ = app_client

    fake_kalshi = MagicMock()
    fake_kalshi.list_positions.return_value = [
        KalshiPosition("KXIPLGAME-26-LSG", yes_count=100, no_count=0,
                       avg_cost_cents=42, market_exposure_cents=4_200),
    ]
    fake_kalshi.get_market.return_value = KalshiMarket(
        ticker="KXIPLGAME-26-LSG", event_ticker="KXIPLGAME-26",
        title="LSG win", yes_price=58, no_price=42, status="open",
    )

    with patch("main.KalshiClient", return_value=fake_kalshi):
        resp = client.get("/api/positions")
    assert resp.status_code == 200

    data = resp.json()
    assert len(data["open"]) == 1
    pos = data["open"][0]
    assert pos["entry_cents"] == 42
    assert pos["mark_cents"] == 58            # came from get_market.yes_price
    assert pos["pnl_cents"] == (58 - 42) * 100   # 1600c = $16


def test_api_positions_uses_no_price_for_no_side(app_client):
    """A NO position should be marked at the no_price, not yes_price."""
    client, _ = app_client

    fake_kalshi = MagicMock()
    fake_kalshi.list_positions.return_value = [
        KalshiPosition("T", yes_count=0, no_count=50, avg_cost_cents=30,
                       market_exposure_cents=1_500),
    ]
    fake_kalshi.get_market.return_value = KalshiMarket(
        ticker="T", event_ticker="T", title="x",
        yes_price=80, no_price=20, status="open",
    )

    with patch("main.KalshiClient", return_value=fake_kalshi):
        resp = client.get("/api/positions")
    pos = resp.json()["open"][0]
    assert pos["side"] == "no"
    assert pos["mark_cents"] == 20            # uses no_price
    assert pos["pnl_cents"] == (20 - 30) * 50   # -500c


def test_api_positions_settled_comes_from_db_not_mock(app_client):
    """The hardcoded _mock_settled() blob is gone — settled positions must
    come from the settlements table."""
    client, _ = app_client
    with database.write_conn() as conn:
        _seed_settlement(conn, "X", net_pnl=4_900, cost=5_100, settled_at=1_777_852_800)

    fake_kalshi = MagicMock()
    fake_kalshi.list_positions.return_value = []

    with patch("main.KalshiClient", return_value=fake_kalshi):
        resp = client.get("/api/positions")
    data = resp.json()
    assert len(data["settled"]) == 1
    assert data["settled"][0]["pnl_cents"] == 4_900
    assert data["settled"][0]["win"] is True
    assert data["settled"][0]["ticker"] == "X"


def test_api_positions_falls_back_when_get_market_returns_none(app_client):
    """If Kalshi returns no market for a ticker (e.g. just delisted), the
    mark must default to entry price so PnL is 0 — not crash, not fake data."""
    client, _ = app_client

    fake_kalshi = MagicMock()
    fake_kalshi.list_positions.return_value = [
        KalshiPosition("T", yes_count=10, no_count=0, avg_cost_cents=42,
                       market_exposure_cents=420),
    ]
    fake_kalshi.get_market.return_value = None

    with patch("main.KalshiClient", return_value=fake_kalshi):
        resp = client.get("/api/positions")
    pos = resp.json()["open"][0]
    assert pos["mark_cents"] == 42
    assert pos["pnl_cents"] == 0
