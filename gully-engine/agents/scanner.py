"""Scanner agent — first pass over open IPL markets.

Job: rank candidates by likely edge. Hands a short list to the Researcher.

Inherited from KalshiTrader:
- Filter parlay/multi-game spam at `kalshi_client.is_parlay_spam()` (already
  done by `KalshiClient.list_ipl_markets`).
- Filter to IPL events only (KXIPL prefix; auto-excludes Saudi Pro League).

Beyond that the LLM is asked to score on:
- Match proximity (live > today > tomorrow > later)
- Asymmetric pricing vs implied probability from H2H/form/conditions
- Public-bias props (e.g. "team X wins" markets get systematic inflation)
- Liquidity (skip if no recent volume — flagged in metadata when available)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from cricket_data import CricketFeed, get_feed
from kalshi_client import KalshiMarket
from llm import chat_json
from settings import settings


log = logging.getLogger(__name__)


SYSTEM_PROMPT = """You are a quantitative cricket prediction-market analyst.

You score open Kalshi YES/NO contracts on Indian Premier League (IPL) markets
by their likely *edge* — how mispriced they are vs the true probability.

Markets pay $1 (100¢) on the winning side. Prices are 1–99¢. A market priced
at 60¢ is the market saying YES = 60% probability. Edge exists when your
estimated probability differs meaningfully from the price.

Score each market on a 0–100 edge index:
- 0–20: efficient, skip
- 20–50: small edge, watch
- 50–80: meaningful edge, research
- 80–100: strong conviction, fast-track to decision

Base scoring on (in order of importance):
1. Match proximity. Live or in-progress > today > tomorrow > this week > later.
2. Pricing asymmetry vs base rates from H2H/form/conditions if known.
3. Liquidity. Skip illiquid markets even if mispriced — edge can't be captured.
4. Known systematic biases (favorites overpriced; super-overs underpriced;
   top-batter markets often have public bias toward star players).

Return ONLY this JSON shape (no prose around it):
{
  "candidates": [
    {"ticker": "<exact ticker>", "score": <0-100 int>, "reason": "<one line>"}
  ]
}

Sort `candidates` by score descending. Include at most 5 entries. Skip any
market with score < 30.
"""


@dataclass
class ScanCandidate:
    ticker: str
    score: int
    reason: str


def shortlist(markets: list[KalshiMarket], *, max_results: int = 5) -> list[ScanCandidate]:
    """Score and rank markets via the LLM. Falls back to ticker-order slice on failure."""
    if not markets:
        return []

    feed: CricketFeed = get_feed()
    live = feed.live_match()
    live_blurb = (
        f"\nLIVE NOW: {live.team_a} vs {live.team_b} — {live.status_text}"
        if live else "\nNo IPL match in progress right now."
    )

    market_lines = []
    for m in markets[:80]:   # cap to keep token usage sane
        market_lines.append(
            f"- {m.ticker} | {m.title or '(no title)'} | yes={m.yes_price}¢ no={m.no_price}¢"
        )
    user_prompt = (
        f"{live_blurb}\n\n"
        f"Open IPL markets ({len(market_lines)} of {len(markets)}):\n"
        + "\n".join(market_lines)
        + f"\n\nRank the top {max_results}."
    )

    resp = chat_json(
        agent="scanner",
        model=settings.scanner_model,
        system=SYSTEM_PROMPT,
        user=user_prompt,
        temperature=0.2,
        max_tokens=900,
    )
    if resp is None or not isinstance(resp.parsed_json, dict):
        log.warning("scanner: LLM unavailable, falling back to first %d markets", max_results)
        return [
            ScanCandidate(ticker=m.ticker, score=0, reason="fallback (no LLM)")
            for m in markets[:max_results]
        ]

    raw_candidates = resp.parsed_json.get("candidates", [])
    if not isinstance(raw_candidates, list):
        log.warning("scanner: malformed candidates field, falling back")
        return [
            ScanCandidate(ticker=m.ticker, score=0, reason="fallback (bad shape)")
            for m in markets[:max_results]
        ]

    valid_tickers = {m.ticker for m in markets}
    out: list[ScanCandidate] = []
    for c in raw_candidates:
        if not isinstance(c, dict):
            continue
        ticker = c.get("ticker")
        if ticker not in valid_tickers:
            log.debug("scanner: dropping unknown ticker %s", ticker)
            continue
        try:
            score = int(c.get("score", 0))
        except (TypeError, ValueError):
            continue
        if score < 30:
            continue
        out.append(ScanCandidate(
            ticker=ticker,
            score=max(0, min(100, score)),
            reason=str(c.get("reason", ""))[:200],
        ))
        if len(out) >= max_results:
            break

    return out
