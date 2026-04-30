"""Scanner agent: filter Kalshi markets to a candidate shortlist.

Inherited rules (already in `kalshi_client.is_parlay_spam`):
- Drop `KXMVECROSSCATEGORY*` and `KXMVESPORTSMULTIGAME*` parlay markets
- Filter to IPL events only (KXIPL prefix)

Beyond that, the scanner ranks markets by:
- Liquidity (book depth)
- Edge proxy (distance from implied probability based on H2H/form)
- Match proximity (live > tonight > tomorrow > later)

Stub implementation — wire up an LLM call once Kalshi is authenticated.
"""

from __future__ import annotations

from kalshi_client import KalshiMarket


def shortlist(markets: list[KalshiMarket], *, max_results: int = 10) -> list[KalshiMarket]:
    """Return up to max_results markets worth researching."""
    # TODO: rank by edge / liquidity / proximity
    return markets[:max_results]
