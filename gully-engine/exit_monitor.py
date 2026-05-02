"""Exit monitor — when to close a position.

Carries forward two hard rules from KalshiTrader:

1. **Hard stops bypass the LLM.** Stop loss, trailing stop, and time-based
   exits fire deterministically and never call out to a model. The LLM is
   only consulted for nuanced "should I take profit early" calls.
2. **Shadow mode by default.** Any new exit logic must run in shadow for a
   full session before flipping to live. Shadow mode logs decisions to
   `exit_decisions` but never places sells.

Restart resilience is baked in: a startup grace window prevents the monitor
from re-logging stale decisions on every reboot, and the closed_market_cache
table stops it from rechecking already-settled markets after a restart.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from settings import settings


log = logging.getLogger(__name__)

STARTUP_GRACE_SECONDS = 60
STOP_LOSS_PCT = -0.30          # exit if mark drops 30% below entry
TRAILING_STOP_GIVEBACK = 0.20  # give back 20% of peak unrealized profit
TIME_STOP_MINUTES = 90         # close out positions older than this if no signal


@dataclass
class ExitDecision:
    ticker: str
    trigger: str           # 'stop_loss' | 'trailing_stop' | 'time' | 'llm' | 'manual'
    action: str            # 'hold' | 'sell'
    mode: str              # 'shadow' | 'live'
    mark_price_cents: int
    pnl_cents_at_decision: int
    note: str = ""


@dataclass
class PositionSnapshot:
    ticker: str
    entry_price_cents: int
    mark_price_cents: int
    yes_count: int
    no_count: int
    side: str              # 'yes' | 'no'
    opened_at: int
    peak_pnl_cents: int


def _hard_stop(snap: PositionSnapshot, now: int) -> ExitDecision | None:
    """Return a deterministic exit (or None to defer to LLM)."""
    if snap.entry_price_cents <= 0:
        return None

    direction = 1 if snap.side == "yes" else -1
    pnl_per_contract_cents = direction * (snap.mark_price_cents - snap.entry_price_cents)
    contracts = max(snap.yes_count, snap.no_count)
    pnl_cents = pnl_per_contract_cents * contracts

    pct = pnl_per_contract_cents / snap.entry_price_cents

    if pct <= STOP_LOSS_PCT:
        return ExitDecision(
            ticker=snap.ticker,
            trigger="stop_loss",
            action="sell",
            mode=settings.exit_mode,
            mark_price_cents=snap.mark_price_cents,
            pnl_cents_at_decision=pnl_cents,
            note=f"stop_loss: {pct:.1%} <= {STOP_LOSS_PCT:.0%}",
        )

    if snap.peak_pnl_cents > 0:
        giveback = (snap.peak_pnl_cents - pnl_cents) / max(1, snap.peak_pnl_cents)
        if giveback >= TRAILING_STOP_GIVEBACK:
            return ExitDecision(
                ticker=snap.ticker,
                trigger="trailing_stop",
                action="sell",
                mode=settings.exit_mode,
                mark_price_cents=snap.mark_price_cents,
                pnl_cents_at_decision=pnl_cents,
                note=f"trailing_stop: gave back {giveback:.0%} of peak ${snap.peak_pnl_cents/100:.2f}",
            )

    if (now - snap.opened_at) > TIME_STOP_MINUTES * 60:
        return ExitDecision(
            ticker=snap.ticker,
            trigger="time",
            action="sell",
            mode=settings.exit_mode,
            mark_price_cents=snap.mark_price_cents,
            pnl_cents_at_decision=pnl_cents,
            note=f"time_stop: open > {TIME_STOP_MINUTES}m",
        )

    return None


def evaluate(snap: PositionSnapshot, *, now: int | None = None) -> ExitDecision:
    """Evaluate a position and return an ExitDecision.

    Hard stops short-circuit. If none triggered, defer to the LLM (stub here).
    """
    now = now or int(time.time())
    deterministic = _hard_stop(snap, now)
    if deterministic:
        return deterministic

    # LLM path — delegate to portfolio_exit agent.
    # Imports inside the function: agents.portfolio_exit imports ExitDecision and
    # PositionSnapshot from this module, so a top-level import would be circular.
    from agents.portfolio_exit import decide as llm_decide
    from cricket_data import get_feed
    return llm_decide(snap, live=get_feed().live_match())
