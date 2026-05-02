"""Researcher agent — deep-dive on a single market.

Takes a Kalshi market plus the live match snapshot and asks the LLM for an
estimated probability that YES resolves. Output (`ResearchNote`) is consumed
by the decision agent.

Inherits the scanner-style fallback discipline:
- If `chat_json` returns None or malformed JSON, return a fallback note with
  `confidence=0.0` (the load-bearing signal that makes the decision agent skip).
- Probability is clamped to [0, 1] regardless of what the LLM returns.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from cricket_data import LiveScore
from kalshi_client import KalshiMarket
from llm import chat_json
from settings import settings


log = logging.getLogger(__name__)


SYSTEM_PROMPT = """You are a quantitative cricket prediction-market analyst.

Given live IPL match state and a YES/NO market, estimate the true probability
that YES resolves. Markets pay $1 (100¢) on the winning side, so the current
price (in cents) is the market's implied probability in percent.

Consider (in order of importance):
1. Live state — runs/wickets/overs vs target, required run rate, who's batting,
   in-form batters at the crease, bowler economy, recent ball-by-ball trend.
2. Pre-game context — H2H, recent form, venue, conditions.
3. Public-bias systematics — favorites tend to be overpriced; underdogs in
   close-to-the-coin markets are often slightly underpriced.

Return ONLY this JSON shape (no prose around it):
{
  "estimated_probability": <0.0-1.0 float>,
  "confidence": <0.0-1.0 float — your confidence in the estimate>,
  "reasoning": "<one paragraph explaining the estimate>"
}
"""


@dataclass
class ResearchNote:
    ticker: str
    estimated_yes_probability: float   # 0.0 - 1.0
    confidence: float                  # 0.0 - 1.0
    reasoning: str


def _fallback(market: KalshiMarket, why: str) -> ResearchNote:
    return ResearchNote(
        ticker=market.ticker,
        estimated_yes_probability=market.yes_price / 100,
        confidence=0.0,
        reasoning=f"fallback: {why}",
    )


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
        f"On-strike: {on_strike.get('name', '?')} {on_strike.get('runs', '?')}({on_strike.get('balls', '?')}) "
        f"sr={on_strike.get('sr', '?')}. "
        f"Non-strike: {non_strike.get('name', '?')} {non_strike.get('runs', '?')}({non_strike.get('balls', '?')}). "
        f"Bowler: {bowler.get('name', '?')} {bowler.get('overs', '?')}-{bowler.get('runs', '?')}-{bowler.get('wickets', '?')} "
        f"econ={bowler.get('economy', '?')}. "
        f"Last balls: {' '.join(live.last_balls or [])}."
    )


def research(market: KalshiMarket, live: LiveScore | None) -> ResearchNote:
    """Estimate true YES probability for a single market via LLM."""
    user_prompt = (
        f"Market: {market.ticker}\n"
        f"Title: {market.title}\n"
        f"Current YES: {market.yes_price}¢ | NO: {market.no_price}¢ "
        f"(implied YES = {market.yes_price}%)\n\n"
        f"{_live_block(live)}\n\n"
        f"Estimate true probability that YES resolves."
    )

    resp = chat_json(
        agent="researcher",
        model=settings.research_model,
        system=SYSTEM_PROMPT,
        user=user_prompt,
        temperature=0.2,
        max_tokens=900,
        log_ticker=market.ticker,
    )
    if resp is None or not isinstance(resp.parsed_json, dict):
        log.warning("researcher[%s]: LLM unavailable or wrong shape, falling back", market.ticker)
        return _fallback(market, "LLM unavailable")

    parsed = resp.parsed_json
    raw_prob = parsed.get("estimated_probability")
    if not isinstance(raw_prob, (int, float)):
        log.warning("researcher[%s]: missing/invalid estimated_probability, falling back", market.ticker)
        return _fallback(market, "missing estimated_probability")
    raw_conf = parsed.get("confidence", 0.5)
    if not isinstance(raw_conf, (int, float)):
        raw_conf = 0.5

    return ResearchNote(
        ticker=market.ticker,
        estimated_yes_probability=max(0.0, min(1.0, float(raw_prob))),
        confidence=max(0.0, min(1.0, float(raw_conf))),
        reasoning=str(parsed.get("reasoning", ""))[:1000],
    )
