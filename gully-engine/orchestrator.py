"""Two-thread orchestrator: entry pipeline + exit monitor.

- Entry pipeline runs only during active match windows (gated by
  cricket_data.live_match()). Calls Scanner → Researcher → Decision.
- Exit monitor runs always-on; checks each open position against hard stops,
  then defers to the LLM exit agent for nuanced calls.

Inherited from KalshiTrader: manual triggers acquire a *non-blocking* lock so
they can't pile on top of an already-running pass (was a deadlock source).
"""

from __future__ import annotations

import logging
import threading
import time

from agents.scanner import shortlist as scanner_shortlist
from cricket_data import get_feed
from exit_monitor import PositionSnapshot, evaluate
from kalshi_client import KalshiClient
from settings import settings


log = logging.getLogger(__name__)

_stop_flag = threading.Event()
_entry_lock = threading.Lock()
_exit_lock = threading.Lock()


def stop() -> None:
    _stop_flag.set()


# ── Entry pipeline ────────────────────────────────────────────────────


def run_entry_pipeline_once(*, force: bool = False) -> dict:
    """Single pass through Scanner → Researcher → Decision.

    Uses a non-blocking lock — manual triggers fast-fail rather than queue.
    """
    if not _entry_lock.acquire(blocking=False):
        return {"status": "skipped", "reason": "already_running"}
    try:
        feed = get_feed()
        live = feed.live_match()
        if not live and not force:
            return {"status": "skipped", "reason": "no_live_match"}

        client = KalshiClient()
        markets = client.list_ipl_markets()

        candidates = scanner_shortlist(markets, max_results=5)
        log.info(
            "orchestrator.entry: %d markets → %d scanner candidates%s",
            len(markets), len(candidates),
            (" [" + ", ".join(f"{c.ticker} ({c.score})" for c in candidates) + "]") if candidates else "",
        )
        # TODO: researcher / decision agents (next phase)
        return {
            "status": "ok",
            "markets_scanned": len(markets),
            "candidates": [
                {"ticker": c.ticker, "score": c.score, "reason": c.reason}
                for c in candidates
            ],
            "live": bool(live),
        }
    finally:
        _entry_lock.release()


def _entry_loop() -> None:
    while not _stop_flag.is_set():
        try:
            run_entry_pipeline_once()
        except Exception:  # noqa: BLE001
            log.exception("orchestrator.entry: error during pass")
        if _stop_flag.wait(timeout=settings.live_poll_interval_seconds):
            return


# ── Exit monitor ──────────────────────────────────────────────────────


def run_exit_monitor_once(*, force: bool = False) -> dict:
    """Evaluate every open position once."""
    if not _exit_lock.acquire(blocking=False):
        return {"status": "skipped", "reason": "already_running"}
    try:
        client = KalshiClient()
        positions = client.list_positions()
        decisions = []
        now = int(time.time())
        for p in positions:
            side = "yes" if p.yes_count >= p.no_count else "no"
            mark = p.avg_cost_cents  # TODO: use latest market price
            snap = PositionSnapshot(
                ticker=p.ticker,
                entry_price_cents=p.avg_cost_cents,
                mark_price_cents=mark,
                yes_count=p.yes_count,
                no_count=p.no_count,
                side=side,
                opened_at=now - 600,   # placeholder; replace with real timestamp
                peak_pnl_cents=0,
            )
            decisions.append(evaluate(snap, now=now))
        return {"status": "ok", "evaluated": len(decisions),
                "actions": [{"ticker": d.ticker, "action": d.action, "trigger": d.trigger} for d in decisions]}
    finally:
        _exit_lock.release()


def _exit_loop() -> None:
    while not _stop_flag.is_set():
        try:
            run_exit_monitor_once()
        except Exception:  # noqa: BLE001
            log.exception("orchestrator.exit: error during pass")
        if _stop_flag.wait(timeout=settings.live_poll_interval_seconds):
            return


# ── Lifecycle ─────────────────────────────────────────────────────────


def start_threads() -> tuple[threading.Thread, threading.Thread]:
    entry_t = threading.Thread(target=_entry_loop, daemon=True, name="orch.entry")
    exit_t = threading.Thread(target=_exit_loop, daemon=True, name="orch.exit")
    entry_t.start()
    exit_t.start()
    log.info("orchestrator: entry + exit threads started (exit_mode=%s)", settings.exit_mode)
    return entry_t, exit_t
