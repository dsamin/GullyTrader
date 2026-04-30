"""Tests for pnl.py — paired-position correction is the load-bearing case.

Carries forward the regression that bit KalshiTrader on 2026-03-02:
    A trade that bought YES @ 42¢ for 100 contracts, then exited via NO @ 60¢
    for 100 contracts, settled with a phantom -$34.74 loss because the auto-close
    payout (`min(yes,no) * 100¢`) was missing from revenue.
"""

from __future__ import annotations

from pnl import (
    CONTRACT_VALUE_CENTS,
    PositionPnl,
    normalize_contract_value,
    normalize_position_side,
    position_contract_count,
    realized_pnl,
)


def test_contract_value_defaults_to_100_when_api_returns_zero():
    assert normalize_contract_value(0) == 100
    assert normalize_contract_value(None) == 100
    assert normalize_contract_value(100) == 100
    # A non-default API value should still pass through (forward-compat).
    assert normalize_contract_value(50) == 50


def test_position_side_paired_when_both_counts_positive():
    assert normalize_position_side(yes_count=100, no_count=100) == "paired"
    assert normalize_position_side(yes_count=10, no_count=0) == "yes"
    assert normalize_position_side(yes_count=0, no_count=20) == "no"
    assert normalize_position_side(yes_count=0, no_count=0) == "flat"


def test_contract_count_uses_max_for_paired_positions():
    # Inherited helper: prevents 465K errors/week (KalshiTrader issue #49).
    assert position_contract_count(120, 0) == 120
    assert position_contract_count(0, 60) == 60
    assert position_contract_count(80, 80) == 80
    assert position_contract_count(80, 50) == 80


def test_paired_position_correction_recovers_phantom_loss():
    """The canonical scenario from KalshiTrader, 2026-03-02.

    Bought YES 100 @ 42¢ (cost = 4200¢)
    Then exited via buying NO 100 @ 60¢  (cost += 6000¢; total cost = 10_200¢)
    Auto-close pays min(yes, no) * 100¢ = 100 * 100 = 10_000¢

    Without the correction, settlement_revenue=0 → net = -10_200¢ (phantom loss).
    With the correction, revenue = 0 + 10_000 = 10_000¢ → net = -200¢ (real cost = spread).
    """
    pnl: PositionPnl = realized_pnl(
        yes_count=100,
        no_count=100,
        cost_cents=10_200,
        settlement_revenue_cents=0,
    )
    assert pnl.revenue_cents == 100 * CONTRACT_VALUE_CENTS == 10_000
    assert pnl.cost_cents == 10_200
    assert pnl.net_cents == -200
    # Sanity: this is the -$2.00 cost-of-spread, not the phantom -$102.00 figure.
    assert pnl.net_dollars == -2.00


def test_paired_position_correction_handles_partial_pairing():
    # Bought YES 120 @ 42¢, then NO 80 @ 60¢. Paired = 80; YES side keeps 40 @ settlement.
    # Cost: 120*42 + 80*60 = 5040 + 4800 = 9840¢
    # If YES wins: settlement_revenue = 40 * 100 = 4000¢
    # Paired correction:                +80 * 100 = 8000¢
    # Total revenue = 12_000¢ → net = +2160¢ = +$21.60
    pnl = realized_pnl(
        yes_count=120,
        no_count=80,
        cost_cents=9_840,
        settlement_revenue_cents=4_000,
    )
    assert pnl.revenue_cents == 12_000
    assert pnl.net_cents == 2_160


def test_unpaired_position_settles_normally():
    # Plain YES win: 100 @ 42¢, settles YES → 100 * 100¢
    pnl = realized_pnl(
        yes_count=100,
        no_count=0,
        cost_cents=4_200,
        settlement_revenue_cents=10_000,
    )
    assert pnl.revenue_cents == 10_000
    assert pnl.net_cents == 5_800


def test_unpaired_loss_settles_with_zero_revenue():
    pnl = realized_pnl(
        yes_count=100,
        no_count=0,
        cost_cents=4_200,
        settlement_revenue_cents=0,
    )
    assert pnl.revenue_cents == 0
    assert pnl.net_cents == -4_200
