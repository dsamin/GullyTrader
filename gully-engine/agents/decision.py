"""Decision agent — sized order from a researcher note.

Pure math: takes a `ResearchNote` (LLM-derived probability + confidence),
the current market price, and the bankroll, and returns a `TradeDecision`
with action ∈ {pass, buy_yes, buy_no}, sized via Quarter-Kelly clamped at
MAX_POSITION_PCT.

No LLM call here — the LLM signal lives in `ResearchNote`. The decision
agent's job is mechanical sizing on that signal.

TODO(follow-up): KalshiMarket only exposes `yes_price`/`no_price` (the bid
side). Limit price is currently `bid + 1¢` which posts at top of queue but
won't fill unless someone crosses. For marketable orders we'd need
`yes_ask`/`no_ask` exposed on the market dataclass.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from agents.researcher import ResearchNote
from kalshi_client import KalshiMarket


log = logging.getLogger(__name__)


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


def _pass(ticker: str, why: str, fallback_price: int) -> TradeDecision:
    return TradeDecision(
        ticker=ticker, action="pass", contracts=0,
        limit_price_cents=fallback_price, reasoning=why,
    )


def decide(note: ResearchNote, *, bankroll_cents: int, market: KalshiMarket) -> TradeDecision:
    """Sized order recommendation from a researched market."""
    if note.confidence == 0.0:
        return _pass(note.ticker, "researcher fell back, no signal", market.yes_price)

    implied = market.yes_price / 100.0
    edge = note.estimated_yes_probability - implied

    if abs(edge) < MIN_EDGE:
        return _pass(note.ticker, f"edge {edge*100:+.1f}¢ below MIN_EDGE", market.yes_price)

    side = "buy_yes" if edge > 0 else "buy_no"
    if side == "buy_yes":
        kelly = edge / max(1e-6, 1.0 - implied)
    else:
        kelly = -edge / max(1e-6, implied)

    fraction = min(kelly * KELLY_FRACTION, MAX_POSITION_PCT)
    if fraction <= 0:
        return _pass(note.ticker, f"non-positive sizing fraction {fraction:.4f}", market.yes_price)

    dollars_to_risk_cents = int(bankroll_cents * fraction)
    price_to_buy = market.yes_price if side == "buy_yes" else market.no_price
    limit_price_cents = max(1, min(99, price_to_buy + 1))
    # Size against the limit price (what we'll actually pay) so the 5% cap holds.
    contracts = dollars_to_risk_cents // limit_price_cents

    if contracts < 1:
        return _pass(
            note.ticker,
            f"size too small: {dollars_to_risk_cents}¢ / {limit_price_cents}¢ < 1 contract",
            market.yes_price,
        )
    return TradeDecision(
        ticker=note.ticker, action=side, contracts=contracts,
        limit_price_cents=limit_price_cents,
        reasoning=(
            f"edge={edge*100:+.1f}¢ kelly={kelly:.3f} fraction={fraction:.4f} "
            f"bankroll=${bankroll_cents/100:.2f} → {contracts} contracts @ {limit_price_cents}¢"
        ),
    )
