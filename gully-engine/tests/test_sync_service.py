"""Tests for sync_service — real reconciliation loop.

Exercises the full pull-then-upsert cycle against an in-memory SQLite DB and
a stubbed KalshiClient so we can verify rows actually land and that
re-running the loop is idempotent (the property we burned ourselves on in
KalshiTrader before — duplicate fills inflated win-rate numbers).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

import database
import sync_service
from kalshi_client import (
    KalshiFill,
    KalshiOrder,
    KalshiPosition,
    KalshiSettlement,
)


@pytest.fixture
def tmp_db(tmp_path: Path):
    """Point settings.db_path at a tmp file and run schema.

    Settings is a frozen dataclass; we use object.__setattr__ to override the
    db_path field for the duration of the test, then restore it.
    """
    from settings import settings as _settings
    db_path = tmp_path / "test.db"
    original = _settings.db_path
    object.__setattr__(_settings, "db_path", db_path)
    try:
        database.initialize(db_path)
        yield db_path
    finally:
        object.__setattr__(_settings, "db_path", original)


class _StubClient:
    def __init__(self, *, positions=None, orders=None, fills=None, settlements=None,
                 balance=None):
        self._positions = positions or []
        self._orders = orders or []
        self._fills = fills or []
        self._settlements = settlements or []
        self._balance = balance or {"balance": 1_000_00, "portfolio_value": 1_200_00}
        self.calls: list[str] = []

    def list_positions(self):
        self.calls.append("positions")
        return self._positions

    def list_orders(self, **_):
        self.calls.append("orders")
        return self._orders

    def list_fills(self, **_):
        self.calls.append("fills")
        return self._fills

    def list_settlements(self, **_):
        self.calls.append("settlements")
        return self._settlements

    def get_balance(self):
        self.calls.append("balance")
        return self._balance


# ── Reconciliation pull → upsert ───────────────────────────────────────


def test_reconcile_once_pulls_all_four_data_types(tmp_db):
    client = _StubClient()
    with patch("sync_service.KalshiClient", return_value=client):
        sync_service._reconcile_once()
    assert "positions" in client.calls
    assert "orders" in client.calls
    assert "fills" in client.calls
    assert "settlements" in client.calls


def test_reconcile_upserts_positions(tmp_db):
    client = _StubClient(positions=[
        KalshiPosition("KXIPLGAME-26MAY07-LSG", yes_count=100, no_count=0,
                       avg_cost_cents=42, market_exposure_cents=4_200),
    ])
    with patch("sync_service.KalshiClient", return_value=client):
        sync_service._reconcile_once()

    with database.connect(tmp_db) as conn:
        rows = conn.execute("SELECT ticker, yes_count, avg_cost_cents, side FROM positions").fetchall()
    assert len(rows) == 1
    assert rows[0]["ticker"] == "KXIPLGAME-26MAY07-LSG"
    assert rows[0]["yes_count"] == 100
    assert rows[0]["avg_cost_cents"] == 42
    assert rows[0]["side"] == "yes"


def test_reconcile_upserts_orders_idempotent(tmp_db):
    """Running reconciliation twice with the same orders must not duplicate rows."""
    client = _StubClient(orders=[
        KalshiOrder(order_id="ord-A", ticker="T", side="yes", action="buy",
                    status="resting", count=50, limit_price_cents=42,
                    created_time="2026-05-01T10:00:00Z"),
    ])
    with patch("sync_service.KalshiClient", return_value=client):
        sync_service._reconcile_once()
        sync_service._reconcile_once()

    with database.connect(tmp_db) as conn:
        rows = conn.execute("SELECT kalshi_order_id, status FROM orders").fetchall()
    assert len(rows) == 1
    assert rows[0]["kalshi_order_id"] == "ord-A"


def test_reconcile_updates_order_status_on_state_change(tmp_db):
    """Order goes from resting → executed; status must reflect the latest pull."""
    pass1 = _StubClient(orders=[
        KalshiOrder(order_id="ord-A", ticker="T", side="yes", action="buy",
                    status="resting", count=50, limit_price_cents=42),
    ])
    pass2 = _StubClient(orders=[
        KalshiOrder(order_id="ord-A", ticker="T", side="yes", action="buy",
                    status="executed", count=50, limit_price_cents=42),
    ])
    with patch("sync_service.KalshiClient", return_value=pass1):
        sync_service._reconcile_once()
    with patch("sync_service.KalshiClient", return_value=pass2):
        sync_service._reconcile_once()

    with database.connect(tmp_db) as conn:
        row = conn.execute("SELECT status FROM orders WHERE kalshi_order_id='ord-A'").fetchone()
    assert row["status"] == "executed"


def test_reconcile_upserts_fills_with_trade_id_dedup(tmp_db):
    """Fills must dedupe by kalshi_trade_id; running twice can't double-count."""
    client = _StubClient(fills=[
        KalshiFill(trade_id="trade-1", order_id="ord-A", ticker="T",
                   side="yes", action="buy", count=100, price_cents=42,
                   is_taker=True, created_time="2026-05-01T10:00:05Z"),
        KalshiFill(trade_id="trade-2", order_id="ord-A", ticker="T",
                   side="yes", action="buy", count=20, price_cents=43,
                   is_taker=False, created_time="2026-05-01T10:00:10Z"),
    ])
    with patch("sync_service.KalshiClient", return_value=client):
        sync_service._reconcile_once()
        sync_service._reconcile_once()    # second pass should not duplicate

    with database.connect(tmp_db) as conn:
        rows = conn.execute("SELECT count, price_cents FROM fills ORDER BY id").fetchall()
    assert len(rows) == 2
    assert rows[0]["count"] == 100 and rows[0]["price_cents"] == 42
    assert rows[1]["count"] == 20 and rows[1]["price_cents"] == 43


def test_reconcile_upserts_settlements_with_corrected_pnl(tmp_db):
    """Settlements written to DB carry the paired-correction net_pnl, not the
    raw API revenue. Wrong here = phantom losses on the dashboard."""
    client = _StubClient(settlements=[
        KalshiSettlement(
            ticker="KXIPLGAME-26APR29-MUM",
            market_result="no",
            revenue_cents=10_000,    # post-correction
            cost_cents=10_200,
            net_pnl_cents=-200,
            yes_count=100, no_count=100,
            settled_time="2026-04-29T18:00:00Z",
        ),
    ])
    with patch("sync_service.KalshiClient", return_value=client):
        sync_service._reconcile_once()

    with database.connect(tmp_db) as conn:
        row = conn.execute(
            "SELECT revenue_cents, cost_cents, net_pnl_cents FROM settlements"
        ).fetchone()
    assert row["revenue_cents"] == 10_000
    assert row["cost_cents"] == 10_200
    assert row["net_pnl_cents"] == -200


def test_reconcile_marks_settled_positions_closed(tmp_db):
    """When a position's ticker shows up in settlements, the position row
    should flip status='closed'."""
    client = _StubClient(
        positions=[],   # already cleared on Kalshi after settlement
        settlements=[
            KalshiSettlement(
                ticker="KXIPLGAME-26APR29-MUM",
                market_result="yes",
                revenue_cents=10_000, cost_cents=4_200, net_pnl_cents=5_800,
                yes_count=100, no_count=0,
                settled_time="2026-04-29T18:00:00Z",
            ),
        ],
    )
    # Pre-seed a position row to simulate a previously-open position
    with database.write_conn() as conn:
        conn.execute("""
            INSERT INTO positions (ticker, side, yes_count, no_count,
                                  avg_cost_cents, status)
            VALUES ('KXIPLGAME-26APR29-MUM', 'yes', 100, 0, 42, 'open')
        """)

    with patch("sync_service.KalshiClient", return_value=client):
        sync_service._reconcile_once()

    with database.connect(tmp_db) as conn:
        row = conn.execute(
            "SELECT status, realized_pnl_cents, closed_at FROM positions WHERE ticker=?",
            ("KXIPLGAME-26APR29-MUM",),
        ).fetchone()
    assert row["status"] == "closed"
    assert row["realized_pnl_cents"] == 5_800
    assert row["closed_at"] is not None


def test_reconcile_continues_when_one_call_errors(tmp_db):
    """If list_orders blows up, list_fills should still run. The loop must
    survive — KalshiTrader incident: one failing endpoint took down the daemon."""
    class ExplodingOrders(_StubClient):
        def list_orders(self, **_):
            self.calls.append("orders")
            raise RuntimeError("kalshi 503")

    client = ExplodingOrders(fills=[
        KalshiFill(trade_id="t1", order_id="x", ticker="T", side="yes",
                   action="buy", count=10, price_cents=50, is_taker=True),
    ])
    with patch("sync_service.KalshiClient", return_value=client):
        sync_service._reconcile_once()    # must not raise

    assert "orders" in client.calls
    assert "fills" in client.calls
    with database.connect(tmp_db) as conn:
        assert conn.execute("SELECT COUNT(*) c FROM fills").fetchone()["c"] == 1
