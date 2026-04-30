"""Exit agent: nuanced LLM-driven exit decisions.

Called only when no hard stop fires (see exit_monitor.py). Used to take
profit early on momentum reversals, ride a winning trade through a tightening
spread, etc.

Defaults to shadow mode — logs decisions without placing sells. Promote to
live by setting GULLYTRADER_EXIT_MODE=live in .env.
"""

from __future__ import annotations

from exit_monitor import ExitDecision, PositionSnapshot
from settings import settings


def decide(snap: PositionSnapshot) -> ExitDecision:
    """Stub LLM exit decision — always holds.

    Real implementation: prompt with current ball-by-ball, position context,
    win-prob trajectory; ask for hold | take_profit | exit_now with rationale.
    """
    return ExitDecision(
        ticker=snap.ticker,
        trigger="llm",
        action="hold",
        mode=settings.exit_mode,
        mark_price_cents=snap.mark_price_cents,
        pnl_cents_at_decision=0,
        note="llm exit agent stub",
    )
