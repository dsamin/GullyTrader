"""Decision agent tests — pure math, no LLM mocks needed."""

from __future__ import annotations

from agents.decision import MAX_POSITION_PCT, MIN_EDGE, TradeDecision, decide
from agents.researcher import ResearchNote
from kalshi_client import KalshiMarket


def _note(ticker: str = "KXIPLGAME-T", prob: float = 0.7, confidence: float = 0.6) -> ResearchNote:
    return ResearchNote(ticker=ticker, estimated_yes_probability=prob,
                        confidence=confidence, reasoning="t")


def _market(ticker: str = "KXIPLGAME-T", yes: int = 50) -> KalshiMarket:
    return KalshiMarket(
        ticker=ticker, event_ticker=ticker, title="t",
        yes_price=yes, no_price=100 - yes, status="open",
    )


def test_passes_when_researcher_confidence_zero():
    """Confidence=0 means the researcher fell back. Don't trade on no signal."""
    note = _note(prob=0.9, confidence=0.0)
    dec = decide(note, bankroll_cents=100_000, market=_market(yes=50))
    assert dec.action == "pass"
    assert dec.contracts == 0
    assert "no signal" in dec.reasoning.lower() or "fell back" in dec.reasoning.lower()


def test_passes_when_edge_below_threshold():
    """Edge of 3¢ is under MIN_EDGE (5¢). Skip."""
    note = _note(prob=0.53)
    dec = decide(note, bankroll_cents=100_000, market=_market(yes=50))
    assert dec.action == "pass"
    assert "edge" in dec.reasoning.lower()


def test_buys_yes_on_positive_edge():
    """Researcher says 70%, market priced at 50% → buy YES."""
    note = _note(prob=0.70)
    dec = decide(note, bankroll_cents=100_000, market=_market(yes=50))
    assert dec.action == "buy_yes"
    assert dec.contracts > 0
    assert dec.limit_price_cents == 51   # bid + 1


def test_buys_no_on_negative_edge():
    """Researcher says 30%, market priced at 60% YES (so NO is 40¢) → buy NO."""
    note = _note(prob=0.30)
    dec = decide(note, bankroll_cents=100_000, market=_market(yes=60))
    assert dec.action == "buy_no"
    assert dec.contracts > 0
    assert dec.limit_price_cents == 41   # no_price + 1 = 40 + 1


def test_max_position_clamp_caps_size():
    """Massive edge — Kelly would size enormous, clamp to 5% of bankroll."""
    bankroll = 1_000_000   # $10,000
    note = _note(prob=0.99)
    dec = decide(note, bankroll_cents=bankroll, market=_market(yes=10))
    assert dec.action == "buy_yes"
    max_dollars_cents = int(bankroll * MAX_POSITION_PCT)
    assert dec.contracts * dec.limit_price_cents <= max_dollars_cents + dec.limit_price_cents


def test_zero_bankroll_passes():
    note = _note(prob=0.70)
    dec = decide(note, bankroll_cents=0, market=_market(yes=50))
    assert dec.action == "pass"
    assert dec.contracts == 0


def test_tiny_bankroll_below_one_contract_passes():
    """Bankroll so small that quarter-Kelly sizing produces <1 contract."""
    note = _note(prob=0.60)
    dec = decide(note, bankroll_cents=20, market=_market(yes=50))
    assert dec.action == "pass"
    assert "size" in dec.reasoning.lower() or "small" in dec.reasoning.lower()


def test_limit_price_is_bid_plus_one_and_clamped_at_99():
    """Limit price = price_to_buy + 1, clamped to <= 99.

    The upper-clamp is defensive — at yes_price=99 we'd need >5¢ edge to not
    pass, which requires probability >1.04 (impossible after researcher's clamp).
    So the clamp covers a defensive code path, not a reachable input.
    """
    note = _note(prob=0.60, confidence=0.6)
    dec = decide(note, bankroll_cents=100_000, market=_market(yes=50))
    assert dec.action == "buy_yes"
    assert dec.limit_price_cents == 51
    assert 1 <= dec.limit_price_cents <= 99
