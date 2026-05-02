"""Tests for portfolio.py — DB-derived metrics that replace the hardcoded
day P&L / ROI / win-rate / sparkline blob in /api/portfolio.

The tests pre-seed the settlements + positions tables with hand-crafted rows
and assert the aggregations come out correct. We use a sentinel `now`
timestamp so day-boundary math is deterministic regardless of when the
suite runs.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import database
import portfolio


@pytest.fixture
def tmp_db(tmp_path: Path):
    from settings import settings as _settings
    db_path = tmp_path / "test.db"
    original = _settings.db_path
    object.__setattr__(_settings, "db_path", db_path)
    try:
        database.initialize(db_path)
        yield db_path
    finally:
        object.__setattr__(_settings, "db_path", original)


# Fixed reference: 2026-05-01 12:00:00 UTC
NOW = 1_777_852_800
SECS_PER_DAY = 86_400


def _seed_settlement(conn, ticker: str, net_pnl: int, cost: int = 1_000,
                     settled_at: int = NOW, market_result: str = "yes"):
    revenue = cost + net_pnl
    conn.execute(
        """INSERT INTO settlements
           (ticker, market_result, revenue_cents, cost_cents, net_pnl_cents, settled_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (ticker, market_result, revenue, cost, net_pnl, settled_at),
    )


def _seed_position(conn, ticker: str, exposure_cents: int = 5_000,
                   status: str = "open", yes_count: int = 100, avg_cost: int = 50):
    conn.execute(
        """INSERT INTO positions
           (ticker, side, yes_count, no_count, avg_cost_cents,
            market_exposure_cents, status)
           VALUES (?, 'yes', ?, 0, ?, ?, ?)""",
        (ticker, yes_count, avg_cost, exposure_cents, status),
    )


# ── Empty DB sanity ────────────────────────────────────────────────────


def test_metrics_with_empty_db_are_all_zero(tmp_db):
    m = portfolio.compute_metrics(now=NOW)
    assert m["day_pnl_abs_cents"] == 0
    assert m["day_pnl_pct"] == 0.0
    assert m["roi_pct"] == 0.0
    assert m["win_rate_pct"] == 0
    assert m["wagered_cents"] == 0
    assert m["open_positions"] == 0
    assert m["exposure_cents"] == 0
    assert m["streak_last_10"] == []
    assert len(m["spark_20d"]) == 20    # always 20 buckets, even if all zero
    assert all(v == 0 for v in m["spark_20d"])


# ── Day P&L ────────────────────────────────────────────────────────────


def test_day_pnl_only_includes_today(tmp_db):
    """Settlements from yesterday must NOT count toward today's P&L."""
    with database.write_conn() as conn:
        _seed_settlement(conn, "today-win",  net_pnl=500,  settled_at=NOW)
        _seed_settlement(conn, "today-loss", net_pnl=-200, settled_at=NOW - 60)
        _seed_settlement(conn, "yesterday",  net_pnl=9_999, settled_at=NOW - SECS_PER_DAY - 1)

    m = portfolio.compute_metrics(now=NOW)
    assert m["day_pnl_abs_cents"] == 300    # 500 - 200


# ── ROI ───────────────────────────────────────────────────────────────


def test_roi_pct_is_realized_pnl_over_total_cost(tmp_db):
    with database.write_conn() as conn:
        _seed_settlement(conn, "a", net_pnl=2_000, cost=10_000)   # +20%
        _seed_settlement(conn, "b", net_pnl=-500,  cost=5_000)   # -10%
    # total: net = 1500, cost = 15_000 → ROI 10%
    m = portfolio.compute_metrics(now=NOW)
    assert m["roi_pct"] == pytest.approx(10.0, abs=0.01)
    assert m["wagered_cents"] == 15_000


def test_roi_handles_zero_cost(tmp_db):
    """No settled trades → ROI must be 0, not raise ZeroDivisionError."""
    m = portfolio.compute_metrics(now=NOW)
    assert m["roi_pct"] == 0.0


# ── Win rate ──────────────────────────────────────────────────────────


def test_win_rate_pct(tmp_db):
    with database.write_conn() as conn:
        for i in range(7):
            _seed_settlement(conn, f"w{i}", net_pnl=100)
        for i in range(3):
            _seed_settlement(conn, f"l{i}", net_pnl=-50)
    m = portfolio.compute_metrics(now=NOW)
    assert m["win_rate_pct"] == 70   # 7/10


# ── Streak (W/L of last 10) ───────────────────────────────────────────


def test_streak_last_10_is_oldest_first(tmp_db):
    """The dashboard renders the dot strip left-to-right oldest → newest."""
    with database.write_conn() as conn:
        # 12 settlements over 12 days, alternating W/L. Only last 10 matter.
        for i in range(12):
            _seed_settlement(conn, f"t{i}",
                             net_pnl=100 if i % 2 == 0 else -50,
                             settled_at=NOW - (12 - i) * SECS_PER_DAY)

    m = portfolio.compute_metrics(now=NOW)
    assert len(m["streak_last_10"]) == 10
    # First settlement we saw (t2) was a win (i=2, even). Last (t11) was a loss.
    assert m["streak_last_10"][0] == "W"
    assert m["streak_last_10"][-1] == "L"


# ── Sparkline ─────────────────────────────────────────────────────────


def test_spark_20d_is_cumulative_pnl_per_day(tmp_db):
    """spark_20d returns 20 daily values: each = cumulative P&L (cents)
    through end of that day. Bucket 19 = today, bucket 0 = 19 days ago.
    Frontend just needs a monotonic-ish series."""
    with database.write_conn() as conn:
        # Bucket 0 (19 days ago): +1000. Bucket 9 (10 days ago): +2000. Bucket 19 (today): -500.
        _seed_settlement(conn, "old",  net_pnl=1_000, settled_at=NOW - 19 * SECS_PER_DAY)
        _seed_settlement(conn, "mid",  net_pnl=2_000, settled_at=NOW - 10 * SECS_PER_DAY)
        _seed_settlement(conn, "new",  net_pnl=-500,  settled_at=NOW)

    m = portfolio.compute_metrics(now=NOW)
    spark = m["spark_20d"]
    assert len(spark) == 20
    assert spark[0]  == 1_000    # +1000 lands at bucket 0
    assert spark[8]  == 1_000    # nothing between
    assert spark[9]  == 3_000    # +2000 lands at bucket 9
    assert spark[18] == 3_000    # nothing between
    assert spark[19] == 2_500    # -500 lands at bucket 19 (today)


# ── Open positions ────────────────────────────────────────────────────


def test_open_positions_and_exposure(tmp_db):
    with database.write_conn() as conn:
        _seed_position(conn, "a", exposure_cents=4_000, status="open")
        _seed_position(conn, "b", exposure_cents=1_500, status="open")
        _seed_position(conn, "c", exposure_cents=8_000, status="closed")  # excluded

    m = portfolio.compute_metrics(now=NOW)
    assert m["open_positions"] == 2
    assert m["exposure_cents"] == 5_500
