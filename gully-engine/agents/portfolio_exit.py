"""PortfolioExit agent — LLM-driven hold/sell on an open position.

Called by `exit_monitor.evaluate()` only when no hard stop fires (stop loss /
trailing / time stop). Used for nuanced calls: take profit early on momentum
reversal, ride a winner through a tightening spread, etc.

Defaults to safe behavior on any failure mode:
- LLM unavailable / malformed JSON / invalid action → hold.

Shadow vs live is a runtime concern owned by the orchestrator — this agent
just returns an `ExitDecision` with `mode=settings.exit_mode` for traceability.
"""

from __future__ import annotations

import logging

from cricket_data import LiveScore
from exit_monitor import ExitDecision, PositionSnapshot
from llm import chat_json
from settings import settings


log = logging.getLogger(__name__)


SYSTEM_PROMPT = """You are a quantitative cricket trader managing an open IPL
prediction-market position. You will be given the current position state
(side, entry, mark, contracts, P&L) and the live match state.

Decide whether to HOLD or SELL. Bias toward HOLD unless:
- The thesis behind the entry is clearly broken (e.g. you bought YES on a
  team chasing, but they've collapsed below the run-rate),
- Or the position has a strong unrealized profit and the match state suggests
  reversion is likely (e.g. holding YES on a team batting last that's now
  needing 24 off the final over).

Return ONLY this JSON shape (no prose around it):
{
  "action": "hold" | "sell",
  "confidence": <0.0-1.0 float>,
  "reasoning": "<one paragraph>"
}
"""


VALID_ACTIONS = {"hold", "sell"}


def _live_block(live: LiveScore | None) -> str:
    if live is None:
        return "no live match — score on pre-game context only."
    on_strike = live.on_strike_batter or {}
    non_strike = live.non_strike_batter or {}
    bowler = live.bowler or {}
    return (
        f"LIVE: {live.team_a} {live.runs_a}/{live.wickets_a} ({live.overs_a}) vs "
        f"{live.team_b} {live.runs_b}/{live.wickets_b} ({live.overs_b}). "
        f"Batting: {live.batting}. Target: {live.target}. RRR: {live.required_run_rate}. "
        f"On-strike: {on_strike.get('name', '?')} {on_strike.get('runs', '?')}({on_strike.get('balls', '?')}). "
        f"Non-strike: {non_strike.get('name', '?')} {non_strike.get('runs', '?')}({non_strike.get('balls', '?')}). "
        f"Bowler: {bowler.get('name', '?')} {bowler.get('overs', '?')}-{bowler.get('runs', '?')}-{bowler.get('wickets', '?')}. "
        f"Last balls: {' '.join(live.last_balls or [])}."
    )


def _compute_pnl(snap: PositionSnapshot) -> int:
    direction = 1 if snap.side == "yes" else -1
    pnl_per_contract = direction * (snap.mark_price_cents - snap.entry_price_cents)
    contracts = max(snap.yes_count, snap.no_count)
    return pnl_per_contract * contracts


def _decision(snap: PositionSnapshot, action: str, note: str) -> ExitDecision:
    return ExitDecision(
        ticker=snap.ticker,
        trigger="llm",
        action=action,
        mode=settings.exit_mode,
        mark_price_cents=snap.mark_price_cents,
        pnl_cents_at_decision=_compute_pnl(snap),
        note=note,
    )


def decide(snap: PositionSnapshot, live: LiveScore | None) -> ExitDecision:
    """LLM-driven hold/sell. Defaults to hold on any failure mode."""
    pnl = _compute_pnl(snap)
    contracts = max(snap.yes_count, snap.no_count)
    user_prompt = (
        f"Position: {snap.ticker} side={snap.side} contracts={contracts}\n"
        f"Entry: {snap.entry_price_cents}¢  Mark: {snap.mark_price_cents}¢  "
        f"P&L: {pnl/100:+.2f}\n\n"
        f"{_live_block(live)}\n\n"
        f"Hold or sell?"
    )

    resp = chat_json(
        agent="portfolio_exit",
        model=settings.exit_model,
        system=SYSTEM_PROMPT,
        user=user_prompt,
        temperature=0.2,
        max_tokens=600,
        log_ticker=snap.ticker,
    )
    if resp is None or not isinstance(resp.parsed_json, dict):
        log.warning("portfolio_exit[%s]: LLM unavailable, defaulting to hold", snap.ticker)
        return _decision(snap, "hold", "fallback: LLM unavailable")

    parsed = resp.parsed_json
    action = str(parsed.get("action", "")).lower()
    if action not in VALID_ACTIONS:
        log.warning("portfolio_exit[%s]: invalid action %r, defaulting to hold", snap.ticker, action)
        return _decision(snap, "hold", f"fallback: invalid action {action!r}")

    reasoning = str(parsed.get("reasoning", ""))[:500]
    return _decision(snap, action, reasoning or f"llm decision={action}")
