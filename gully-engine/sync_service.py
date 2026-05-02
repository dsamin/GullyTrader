"""Background reconciliation loop.

Pulls positions / orders / fills / settlements from Kalshi every
SYNC_INTERVAL_SECONDS and upserts into the local DB. Survives transient SQLite
open failures, Kalshi rate limits, and per-endpoint errors — the loop must
never die from a single error.

Inherited from KalshiTrader PR #54: when SQLite open fails (e.g. file moved
or temp lock), log + sleep + retry rather than letting the thread crash.
A single endpoint blowing up (one Kalshi 503) must not skip the others.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import time

import database
from kalshi_client import (
    KalshiClient,
    KalshiFill,
    KalshiOrder,
    KalshiPosition,
    KalshiSettlement,
)
from pnl import normalize_position_side
from settings import settings


log = logging.getLogger(__name__)

_stop_flag = threading.Event()


def stop() -> None:
    _stop_flag.set()


def _iso_to_epoch(ts: str) -> int | None:
    """Convert ISO-8601 / Z-suffixed timestamps to unix epoch seconds."""
    if not ts:
        return None
    try:
        from datetime import datetime
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        return int(datetime.fromisoformat(ts).timestamp())
    except Exception:
        return None


# ── Upsert helpers ────────────────────────────────────────────────────


def _upsert_position(conn: sqlite3.Connection, p: KalshiPosition) -> None:
    side = normalize_position_side(p.yes_count, p.no_count)
    conn.execute(
        """
        INSERT INTO positions (ticker, side, yes_count, no_count,
                               avg_cost_cents, market_exposure_cents,
                               opened_at, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'open')
        ON CONFLICT(ticker) DO UPDATE SET
            side=excluded.side,
            yes_count=excluded.yes_count,
            no_count=excluded.no_count,
            avg_cost_cents=excluded.avg_cost_cents,
            market_exposure_cents=excluded.market_exposure_cents
        """,
        (
            p.ticker, side if side != "flat" else "yes",
            p.yes_count, p.no_count,
            p.avg_cost_cents, p.market_exposure_cents,
            int(time.time()),
        ),
    )


def _upsert_order(conn: sqlite3.Connection, o: KalshiOrder) -> None:
    conn.execute(
        """
        INSERT INTO orders (kalshi_order_id, ticker, side, action, count,
                            limit_price_cents, status, placed_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(kalshi_order_id) DO UPDATE SET
            status=excluded.status,
            count=excluded.count,
            limit_price_cents=excluded.limit_price_cents
        """,
        (
            o.order_id, o.ticker, o.side, o.action, o.count,
            o.limit_price_cents, o.status,
            _iso_to_epoch(o.created_time),
        ),
    )


def _insert_fill(conn: sqlite3.Connection, f: KalshiFill) -> None:
    """Insert a fill, skipping duplicates by kalshi_trade_id."""
    conn.execute(
        """
        INSERT OR IGNORE INTO fills
            (kalshi_trade_id, kalshi_order_id, ticker, side, action,
             count, price_cents, is_taker, filled_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            f.trade_id, f.order_id, f.ticker, f.side, f.action,
            f.count, f.price_cents, 1 if f.is_taker else 0,
            _iso_to_epoch(f.created_time) or int(time.time()),
        ),
    )


def _upsert_settlement(conn: sqlite3.Connection, s: KalshiSettlement) -> None:
    settled_at = _iso_to_epoch(s.settled_time) or int(time.time())
    conn.execute(
        """
        INSERT INTO settlements (ticker, market_result, revenue_cents,
                                 cost_cents, net_pnl_cents, settled_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(ticker) DO UPDATE SET
            market_result=excluded.market_result,
            revenue_cents=excluded.revenue_cents,
            cost_cents=excluded.cost_cents,
            net_pnl_cents=excluded.net_pnl_cents,
            settled_at=excluded.settled_at
        """,
        (s.ticker, s.market_result, s.revenue_cents, s.cost_cents,
         s.net_pnl_cents, settled_at),
    )

    # Mark any matching position 'closed' and copy realized P&L over.
    conn.execute(
        """
        UPDATE positions
           SET status='closed',
               realized_pnl_cents=?,
               closed_at=?
         WHERE ticker=?
        """,
        (s.net_pnl_cents, settled_at, s.ticker),
    )


# ── Main reconciliation pass ──────────────────────────────────────────


def _reconcile_once() -> None:
    """One pass: pull positions, orders, fills, settlements; upsert into DB.

    Each section is independently guarded — a Kalshi 503 on /portfolio/orders
    must not stop us from pulling /portfolio/fills.
    """
    client = KalshiClient()

    positions: list[KalshiPosition] = []
    orders: list[KalshiOrder] = []
    fills: list[KalshiFill] = []
    settlements: list[KalshiSettlement] = []

    try:
        positions = client.list_positions()
    except Exception:
        log.exception("sync_service: list_positions failed")

    try:
        orders = client.list_orders()
    except Exception:
        log.exception("sync_service: list_orders failed")

    try:
        fills = client.list_fills()
    except Exception:
        log.exception("sync_service: list_fills failed")

    try:
        settlements = client.list_settlements()
    except Exception:
        log.exception("sync_service: list_settlements failed")

    if not (positions or orders or fills or settlements):
        log.debug("sync_service: nothing to reconcile this pass")
        return

    with database.write_conn() as conn:
        for p in positions:
            try:
                _upsert_position(conn, p)
            except Exception:
                log.exception("sync_service: upsert_position failed for %s", p.ticker)
        for o in orders:
            try:
                _upsert_order(conn, o)
            except Exception:
                log.exception("sync_service: upsert_order failed for %s", o.order_id)
        for f in fills:
            try:
                _insert_fill(conn, f)
            except Exception:
                log.exception("sync_service: insert_fill failed for %s", f.trade_id)
        for s in settlements:
            try:
                _upsert_settlement(conn, s)
            except Exception:
                log.exception("sync_service: upsert_settlement failed for %s", s.ticker)

    log.info(
        "sync_service: reconciled %d positions, %d orders, %d fills, %d settlements",
        len(positions), len(orders), len(fills), len(settlements),
    )


def run() -> None:
    """Run the loop until stop() is called.

    Caller is responsible for spinning this in a daemon thread.
    """
    backoff = 1.0
    while not _stop_flag.is_set():
        try:
            _reconcile_once()
            backoff = 1.0
        except sqlite3.OperationalError as exc:
            # PR #54: keep loop alive when SQLite open fails
            log.warning("sync_service: SQLite error, retrying after backoff: %s", exc)
            time.sleep(min(30.0, backoff))
            backoff = min(30.0, backoff * 2)
            continue
        except Exception:  # noqa: BLE001 — top-level loop must not die
            log.exception("sync_service: unexpected error, sleeping before retry")
            time.sleep(min(30.0, backoff))
            backoff = min(30.0, backoff * 2)
            continue

        if _stop_flag.wait(timeout=settings.sync_interval_seconds):
            break


def start_in_thread() -> threading.Thread:
    t = threading.Thread(target=run, daemon=True, name="sync_service")
    t.start()
    log.info("sync_service: started thread")
    return t
