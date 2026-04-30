"""P&L calculation utilities.

Carries forward the *paired-position correction* from KalshiTrader (fix
landed 2026-03-02 in the Kalshi engine). The bug it solves:

  Kalshi binary contracts pay $1 (100¢) on the winning side. When you exit a
  YES position early by buying the matching NO, you end up with non-zero
  counts on both sides — a paired position. Both auto-close at settlement
  and the position pays you `min(yes_count, no_count) * 100¢`. If you only
  count revenue from the side that "won," profitable trades silently report
  as losses.

The Kalshi API also sometimes returns `value=0` for binary contracts. Always
default contract value to 100¢.
"""

from __future__ import annotations

from dataclasses import dataclass


CONTRACT_VALUE_CENTS = 100  # Kalshi binary contracts pay $1 — never trust value=0 from API


@dataclass(frozen=True)
class PositionPnl:
    revenue_cents: int
    cost_cents: int
    net_cents: int

    @property
    def revenue_dollars(self) -> float:
        return self.revenue_cents / 100.0

    @property
    def cost_dollars(self) -> float:
        return self.cost_cents / 100.0

    @property
    def net_dollars(self) -> float:
        return self.net_cents / 100.0


def normalize_contract_value(api_value: int | None) -> int:
    """API sometimes returns 0; default to 100 cents.

    Inherited from KalshiTrader (issue #49 → PR #50).
    """
    if not api_value:
        return CONTRACT_VALUE_CENTS
    return api_value


def realized_pnl(
    *,
    yes_count: int,
    no_count: int,
    cost_cents: int,
    settlement_revenue_cents: int = 0,
    contract_value_cents: int = CONTRACT_VALUE_CENTS,
) -> PositionPnl:
    """Compute realized P&L for a settled position with paired-position correction.

    Args:
        yes_count: contracts held on the YES side at close.
        no_count: contracts held on the NO side at close.
        cost_cents: total cost basis in cents (entry premium for both sides).
        settlement_revenue_cents: revenue already booked from the winning side
            via Kalshi settlement (i.e. winning_side_count * 100¢).
        contract_value_cents: defaults to 100. Pass through `normalize_contract_value`
            if you read it from the API.

    Returns:
        PositionPnl with corrected revenue/cost/net.

    The paired-position correction adds `min(yes,no) * value` to revenue.
    Without it, profitable early-exit trades show as losses.
    """
    paired = min(yes_count, no_count)
    paired_revenue = paired * contract_value_cents
    revenue = settlement_revenue_cents + paired_revenue
    return PositionPnl(
        revenue_cents=revenue,
        cost_cents=cost_cents,
        net_cents=revenue - cost_cents,
    )


def position_contract_count(yes_count: int, no_count: int) -> int:
    """Total contract count for a (possibly paired) position.

    Inherited helper from KalshiTrader — used by exit-monitor metrics.
    Without it the engine generated 465K errors/week (issue #49).
    """
    return max(yes_count, no_count)


def normalize_position_side(yes_count: int, no_count: int) -> str:
    """Infer effective side ('yes' | 'no' | 'flat' | 'paired')."""
    if yes_count > 0 and no_count > 0:
        return "paired"
    if yes_count > 0:
        return "yes"
    if no_count > 0:
        return "no"
    return "flat"
