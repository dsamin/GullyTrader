"""Researcher agent: deep-dive on each shortlisted market.

Pulls live ball-by-ball state from the cricket feed plus historical context
(H2H, form, venue stats) and asks the LLM for an estimated probability.

Output is consumed by the decision agent. Stub: returns the implied YES price
unchanged, so it acts as a no-op pass-through until wired.
"""

from __future__ import annotations

from dataclasses import dataclass

from kalshi_client import KalshiMarket
from cricket_data import get_feed


@dataclass
class ResearchNote:
    ticker: str
    estimated_yes_probability: float   # 0.0 - 1.0
    confidence: float                  # 0.0 - 1.0
    reasoning: str


def research(market: KalshiMarket) -> ResearchNote:
    """Research a market. Stub: echoes the market's implied probability."""
    feed = get_feed()
    live = feed.live_match()
    implied = market.yes_price / 100.0
    return ResearchNote(
        ticker=market.ticker,
        estimated_yes_probability=implied,
        confidence=0.5,
        reasoning=f"stub: live={'yes' if live else 'no'}, implied={implied:.2f}",
    )
