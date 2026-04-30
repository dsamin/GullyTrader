"""Decision agent: do we trade, and how big?

Takes a ResearchNote and decides:
- which side (YES / NO)
- position size (fractional Kelly or fixed % of bankroll)
- limit price

Stub: returns 'pass' for everything until wired up.
"""

from __future__ import annotations

from dataclasses import dataclass

from agents.researcher import ResearchNote


KELLY_FRACTION = 0.25       # quarter-Kelly — conservative
MIN_EDGE = 0.05             # require 5+¢ of edge to enter
MAX_POSITION_PCT = 0.05     # never more than 5% of bankroll on one bet


@dataclass
class TradeDecision:
    ticker: str
    action: str           # 'pass' | 'buy_yes' | 'buy_no'
    contracts: int
    limit_price_cents: int
    reasoning: str


def decide(note: ResearchNote, *, bankroll_cents: int, market_yes_cents: int) -> TradeDecision:
    """Decide whether/how to trade a researched market.

    Stub: always passes. Real implementation should compute edge against the
    book and size with fractional Kelly clamped by MAX_POSITION_PCT.
    """
    # TODO: real Kelly sizing & limit price calculation
    return TradeDecision(
        ticker=note.ticker,
        action="pass",
        contracts=0,
        limit_price_cents=market_yes_cents,
        reasoning="stub: decision agent not yet wired",
    )
