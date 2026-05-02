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

from agents.decision import decide
from agents.researcher import research
from agents.scanner import shortlist as scanner_shortlist
from cricket_data import get_feed
from exit_monitor import PositionSnapshot, evaluate
from kalshi_client import KalshiClient
from settings import settings


log = logging.getLogger(__name__)


def _log_decision(agent: str, ticker: str, decision: str, reasoning: str) -> None:
    """Write a single agent_logs row for a non-LLM orchestrator decision.

    The LLM-driven agents (scanner, researcher, exit) self-log via llm.chat_json.
    The pure-math Decision agent and the deterministic exit-monitor branches don't,
    so the orchestrator emits an explicit row so /api/bot/status can read them.
    """
    import database  # local import — keeps module load order stable in tests
    try:
        with database.write_conn() as conn:
            conn.execute(
                "INSERT INTO agent_logs (agent, ticker, decision, reasoning, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (agent, ticker, decision, reasoning, int(time.time())),
            )
    except Exception:  # noqa: BLE001 — DB write failure must not crash the loop
        log.exception("orchestrator: failed to write agent_log %s/%s", agent, ticker)


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
        balance_resp = client.get_balance() or {}
        balance = int(balance_resp.get("balance", 0) or 0)
        market_by_ticker = {m.ticker: m for m in markets}

        candidates = scanner_shortlist(markets, max_results=5)
        log.info(
            "orchestrator.entry: %d markets → %d scanner candidates%s",
            len(markets), len(candidates),
            (" [" + ", ".join(f"{c.ticker} ({c.score})" for c in candidates) + "]") if candidates else "",
        )

        results = []
        for c in candidates:
            market = market_by_ticker.get(c.ticker)
            if market is None:
                continue
            note = research(market, live)
            dec = decide(note, bankroll_cents=balance, market=market)
            _log_decision(
                agent="decision",
                ticker=dec.ticker,
                decision=dec.action,
                reasoning=dec.reasoning,
            )
            order_resp = None
            if dec.action != "pass" and settings.decision_mode == "live":
                side = "yes" if dec.action == "buy_yes" else "no"
                try:
                    order_resp = client.place_limit_order(
                        ticker=dec.ticker, side=side, action="buy",
                        count=dec.contracts, limit_price_cents=dec.limit_price_cents,
                    )
                except Exception as e:  # noqa: BLE001 — keep loop alive on order errors
                    log.exception("orchestrator.entry: place_limit_order failed for %s", dec.ticker)
                    order_resp = {"error": str(e)}
            results.append({
                "ticker": c.ticker, "score": c.score, "scan_reason": c.reason,
                "research": {
                    "estimated_yes_probability": note.estimated_yes_probability,
                    "confidence": note.confidence, "reasoning": note.reasoning,
                },
                "decision": {
                    "action": dec.action, "contracts": dec.contracts,
                    "limit_price_cents": dec.limit_price_cents, "reasoning": dec.reasoning,
                },
                "order": order_resp,
            })

        return {
            "status": "ok",
            "markets_scanned": len(markets),
            "decision_mode": settings.decision_mode,
            "live": bool(live),
            "candidates": results,
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
            market = client.get_market(p.ticker)
            if market is not None:
                mark = market.yes_price if side == "yes" else market.no_price
            else:
                mark = p.avg_cost_cents   # fallback: stale mark; LLM will see zero P&L
            snap = PositionSnapshot(
                ticker=p.ticker,
                entry_price_cents=p.avg_cost_cents,
                mark_price_cents=mark,
                yes_count=p.yes_count, no_count=p.no_count,
                side=side,
                opened_at=now - 600,    # TODO(phase-4): track real open time per position
                peak_pnl_cents=0,       # TODO(phase-4): track peak P&L for trailing-stop
            )
            exit_dec = evaluate(snap, now=now)
            order_resp = None
            if exit_dec.action == "sell" and settings.exit_mode == "live":
                try:
                    order_resp = client.place_limit_order(
                        ticker=p.ticker, side=side, action="sell",
                        count=max(p.yes_count, p.no_count),
                        limit_price_cents=max(1, mark - 1),
                    )
                except Exception as e:  # noqa: BLE001 — keep loop alive on order errors
                    log.exception("orchestrator.exit: place_limit_order failed for %s", p.ticker)
                    order_resp = {"error": str(e)}
            decisions.append({
                "ticker": exit_dec.ticker, "action": exit_dec.action,
                "trigger": exit_dec.trigger, "mode": exit_dec.mode,
                "note": exit_dec.note, "order": order_resp,
            })
        return {
            "status": "ok",
            "evaluated": len(decisions),
            "exit_mode": settings.exit_mode,
            "actions": decisions,
        }
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
