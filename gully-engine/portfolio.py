"""Portfolio metrics derived from the local SQLite tables.

Replaces the hardcoded day_pnl / ROI / win_rate / sparkline blob that
`/api/portfolio` used to return. All metrics read from `settlements` (closed
trades) and `positions` (open exposure) — these tables are populated by
`sync_service._reconcile_once()` against Kalshi's portfolio endpoints.

When the DB is empty (e.g. fresh install, never reconciled, unauthed Kalshi
client) every aggregation returns 0 / [] — the dashboard renders a clean
zero state rather than throwing.
"""

from __future__ import annotations

import time

import database


def compute_metrics(*, now: int | None = None) -> dict:
    """Aggregate portfolio metrics from the DB.

    Args:
        now: unix epoch seconds reference for "today" / day buckets. Defaults
            to time.time(). Tests inject a sentinel for deterministic results.
    """
    now_ts = int(now if now is not None else time.time())
    # Rolling 24h window for "day" P&L — matches what trading dashboards show
    # ("last 24 hours" P&L), and avoids midnight-boundary edge cases.
    day_window_start = now_ts - 86_400
    spark_window_start = now_ts - 20 * 86_400

    with database.connect() as conn:
        totals = conn.execute(
            "SELECT COALESCE(SUM(net_pnl_cents), 0) AS net, "
            "       COALESCE(SUM(cost_cents),    0) AS cost, "
            "       COUNT(*)                       AS n "
            "  FROM settlements"
        ).fetchone()
        total_net = totals["net"]
        total_cost = totals["cost"]
        total_count = totals["n"] or 0

        wins = conn.execute(
            "SELECT COUNT(*) c FROM settlements WHERE net_pnl_cents > 0"
        ).fetchone()["c"]

        day_pnl = conn.execute(
            "SELECT COALESCE(SUM(net_pnl_cents), 0) AS net, "
            "       COALESCE(SUM(cost_cents),    0) AS cost  "
            "  FROM settlements WHERE settled_at > ?",
            (day_window_start,),
        ).fetchone()

        # Last 10 settlements ordered oldest → newest for the W/L dot strip
        recent = conn.execute(
            "SELECT net_pnl_cents FROM settlements "
            "ORDER BY settled_at DESC LIMIT 10"
        ).fetchall()
        streak = ["W" if r["net_pnl_cents"] > 0 else "L" for r in reversed(recent)]

        # 20-day cumulative-P&L sparkline. Each bucket = 1 day of width.
        # Bucket 19 covers (now-1d, now]; bucket 0 covers (now-20d, now-19d].
        # Cumulative running total at the end of each bucket.
        spark_rows = conn.execute(
            "SELECT settled_at, net_pnl_cents FROM settlements "
            "WHERE settled_at > ? ORDER BY settled_at ASC",
            (spark_window_start,),
        ).fetchall()
        bucket_sums = [0] * 20
        for r in spark_rows:
            offset = now_ts - r["settled_at"]
            day_idx = 19 - (offset // 86_400)
            if 0 <= day_idx < 20:
                bucket_sums[day_idx] += r["net_pnl_cents"]
        spark: list[int] = []
        running = 0
        for v in bucket_sums:
            running += v
            spark.append(running)

        # Open positions
        open_rows = conn.execute(
            "SELECT COUNT(*) AS n, COALESCE(SUM(market_exposure_cents), 0) AS exp "
            "  FROM positions WHERE status='open'"
        ).fetchone()

    roi_pct = (total_net / total_cost * 100.0) if total_cost else 0.0
    win_rate_pct = int(round(wins / total_count * 100)) if total_count else 0
    day_pnl_pct = (day_pnl["net"] / day_pnl["cost"] * 100.0) if day_pnl["cost"] else 0.0

    return {
        "day_pnl_abs_cents": int(day_pnl["net"]),
        "day_pnl_pct": round(day_pnl_pct, 2),
        "roi_pct": round(roi_pct, 2),
        "win_rate_pct": win_rate_pct,
        "wagered_cents": int(total_cost),
        "open_positions": int(open_rows["n"]),
        "exposure_cents": int(open_rows["exp"]),
        "streak_last_10": streak,
        "spark_20d": spark,
    }


def recent_fills(limit: int = 50) -> list[dict]:
    """Return the most recent fills as plain dicts for /api/trades."""
    with database.connect() as conn:
        rows = conn.execute(
            "SELECT kalshi_trade_id, kalshi_order_id, ticker, side, action, "
            "       count, price_cents, is_taker, filled_at "
            "  FROM fills ORDER BY filled_at DESC, id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [
        {
            "trade_id": r["kalshi_trade_id"],
            "order_id": r["kalshi_order_id"],
            "ticker": r["ticker"],
            "side": r["side"],
            "action": r["action"],
            "count": r["count"],
            "price_cents": r["price_cents"],
            "is_taker": bool(r["is_taker"]),
            "filled_at": r["filled_at"],
        }
        for r in rows
    ]


def recent_settled_positions(limit: int = 20) -> list[dict]:
    """Recent settlements as plain dicts for the Positions screen 'settled' tab."""
    with database.connect() as conn:
        rows = conn.execute(
            "SELECT ticker, market_result, revenue_cents, cost_cents, "
            "       net_pnl_cents, settled_at "
            "  FROM settlements ORDER BY settled_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [
        {
            "ticker": r["ticker"],
            "market_result": r["market_result"],
            "revenue_cents": r["revenue_cents"],
            "cost_cents": r["cost_cents"],
            "pnl_cents": r["net_pnl_cents"],
            "win": r["net_pnl_cents"] > 0,
            "settled_at": r["settled_at"],
        }
        for r in rows
    ]
