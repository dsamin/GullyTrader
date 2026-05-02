# Phase 3 Agents Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace three stub agents (researcher, decision, portfolio_exit) in [`gully-engine/agents/`](../../../gully-engine/agents/) with real implementations, wire them into the orchestrator's entry/exit pipelines, and gate live order placement behind `decision_mode`/`exit_mode` settings so the bot can run end-to-end in shadow mode for an IPL match.

**Architecture:** Researcher and PortfolioExit call OpenRouter via `llm.chat_json` (mirroring `agents/scanner.py`); both fall back deterministically when the LLM is unavailable. Decision is pure math (Quarter-Kelly sizing on the researcher's probability) — no LLM call. The orchestrator owns the only `KalshiClient.place_limit_order` calls and gates them on `settings.decision_mode == "live"` (entry) and `settings.exit_mode == "live"` (exit).

**Tech Stack:** Python 3.11+, dataclasses, pytest, `unittest.mock.patch`, `requests` (already wired through `llm.chat_json`). No new dependencies.

**Spec:** [`docs/superpowers/specs/2026-05-01-phase-3-agents-design.md`](../specs/2026-05-01-phase-3-agents-design.md).

---

## File Structure

| File | Change |
|---|---|
| `gully-engine/settings.py` | Add `decision_mode` field (env `GULLYTRADER_DECISION_MODE`, default `"shadow"`) |
| `gully-engine/agents/researcher.py` | Replace stub with LLM-driven probability estimator |
| `gully-engine/agents/decision.py` | Replace stub with pure-math Quarter-Kelly sizer |
| `gully-engine/agents/portfolio_exit.py` | Replace stub with LLM-driven hold/sell decision |
| `gully-engine/orchestrator.py` | Wire scanner→researcher→decision in entry pipeline, gate `place_limit_order`. Wire real mark prices + `place_limit_order` (sell) gate in exit pipeline. |
| `gully-engine/exit_monitor.py` | Replace placeholder LLM-path return with `agents.portfolio_exit.decide(...)` |
| `gully-engine/tests/test_researcher.py` | New file — 7 tests |
| `gully-engine/tests/test_decision.py` | New file — 8 tests |
| `gully-engine/tests/test_portfolio_exit.py` | New file — 6 tests |
| `gully-engine/tests/test_orchestrator.py` | New file — 6 tests |
| `README.md` | Status row updates; add `GULLYTRADER_DECISION_MODE` to env table; bump test count |
| `docs/HANDOFF.md` | Move Phase 3 from "Next-up" to "Current state"; note known limitations |
| `docs/ARCHITECTURE.md` | Update three agent rows + entry/exit data-flow blocks |

Each agent file owns one decision; the orchestrator owns I/O. Test files mirror module-under-test, matching existing convention ([`test_scanner.py`](../../../gully-engine/tests/test_scanner.py)).

---

## Task 1: Add `decision_mode` setting

**Files:**
- Modify: `gully-engine/settings.py` (add one line in the `Settings` dataclass)

- [ ] **Step 1: Add the field**

In [`gully-engine/settings.py`](../../../gully-engine/settings.py), in the `@dataclass(frozen=True) class Settings:` block, after the existing `exit_mode` line (currently around line 84), add:

```python
    decision_mode: str = os.getenv("GULLYTRADER_DECISION_MODE", "shadow")
```

So the area looks like:

```python
    enable_orchestrator: bool = _bool("GULLYTRADER_ENABLE_ORCHESTRATOR", False)
    exit_mode: str = os.getenv("GULLYTRADER_EXIT_MODE", "shadow")
    decision_mode: str = os.getenv("GULLYTRADER_DECISION_MODE", "shadow")
    sync_interval_seconds: int = _int("GULLYTRADER_SYNC_INTERVAL_SECONDS", 60)
```

- [ ] **Step 2: Run the existing test suite to confirm nothing broke**

Run: `cd gully-engine && python -m pytest -x`
Expected: all 102 existing tests still pass (the new field is unused so far; just verify no import or default-value error).

- [ ] **Step 3: Commit**

```bash
git add gully-engine/settings.py
git commit -m "Add GULLYTRADER_DECISION_MODE setting (default shadow)"
```

---

## Task 2: Researcher agent (TDD)

**Files:**
- Create: `gully-engine/tests/test_researcher.py`
- Modify (replace contents): `gully-engine/agents/researcher.py`

- [ ] **Step 1: Write the failing tests**

Create [`gully-engine/tests/test_researcher.py`](../../../gully-engine/tests/test_researcher.py) with the full content below:

```python
"""Researcher agent tests — mock chat_json, exercise prob extraction + fallbacks."""

from __future__ import annotations

from unittest.mock import patch

from agents.researcher import ResearchNote, research
from cricket_data import LiveScore
from kalshi_client import KalshiMarket
from llm import LlmResponse


def _market(ticker: str = "KXIPLGAME-26MAY07RCBLSG-LSG", yes: int = 50) -> KalshiMarket:
    return KalshiMarket(
        ticker=ticker, event_ticker=ticker.rsplit("-", 1)[0],
        title="LSG win", yes_price=yes, no_price=100 - yes, status="open",
    )


def _live() -> LiveScore:
    return LiveScore(
        match_id="m1", team_a="RCB", team_b="LSG",
        runs_a=160, wickets_a=4, overs_a="20.0",
        runs_b=82, wickets_b=3, overs_b="11.2",
        batting="team_b", target=161, required_run_rate=8.95,
        on_strike_batter={"name": "Pooran", "runs": 38, "balls": 22, "sr": 172.7},
        non_strike_batter={"name": "Stoinis", "runs": 12, "balls": 9, "sr": 133.3},
        bowler={"name": "Krunal", "overs": "2.2", "runs": 19, "wickets": 1, "economy": 8.14},
        last_balls=["1", "•", "4", "1", "W"],
    )


def _llm_resp(parsed):
    return LlmResponse(content="(stub)", parsed_json=parsed,
                       model="test-model", latency_ms=10, raw={})


def test_happy_path_extracts_probability_and_confidence():
    parsed = {"estimated_probability": 0.62, "confidence": 0.7,
              "reasoning": "LSG chasing well, RRR manageable, top 3 intact"}
    with patch("agents.researcher.chat_json", return_value=_llm_resp(parsed)):
        note = research(_market(yes=50), _live())
    assert isinstance(note, ResearchNote)
    assert note.estimated_yes_probability == 0.62
    assert note.confidence == 0.7
    assert "LSG" in note.reasoning


def test_fallback_when_llm_returns_none():
    with patch("agents.researcher.chat_json", return_value=None):
        note = research(_market(yes=55), _live())
    assert note.estimated_yes_probability == 0.55
    assert note.confidence == 0.0
    assert "fallback" in note.reasoning.lower()


def test_fallback_when_parsed_json_missing_estimated_probability():
    parsed = {"confidence": 0.4, "reasoning": "no probability field"}
    with patch("agents.researcher.chat_json", return_value=_llm_resp(parsed)):
        note = research(_market(yes=40), _live())
    assert note.estimated_yes_probability == 0.40
    assert note.confidence == 0.0
    assert "fallback" in note.reasoning.lower()


def test_fallback_when_parsed_json_is_not_a_dict():
    with patch("agents.researcher.chat_json", return_value=_llm_resp(["array", "instead"])):
        note = research(_market(yes=30), _live())
    assert note.estimated_yes_probability == 0.30
    assert note.confidence == 0.0


def test_probability_clamped_to_upper_bound():
    parsed = {"estimated_probability": 1.5, "confidence": 0.8, "reasoning": "over"}
    with patch("agents.researcher.chat_json", return_value=_llm_resp(parsed)):
        note = research(_market(yes=70), _live())
    assert note.estimated_yes_probability == 1.0
    assert note.confidence == 0.8


def test_probability_clamped_to_lower_bound():
    parsed = {"estimated_probability": -0.3, "confidence": 0.8, "reasoning": "under"}
    with patch("agents.researcher.chat_json", return_value=_llm_resp(parsed)):
        note = research(_market(yes=20), _live())
    assert note.estimated_yes_probability == 0.0
    assert note.confidence == 0.8


def test_works_with_no_live_match():
    parsed = {"estimated_probability": 0.45, "confidence": 0.5,
              "reasoning": "pre-game on form alone"}
    with patch("agents.researcher.chat_json", return_value=_llm_resp(parsed)) as cj:
        note = research(_market(yes=50), live=None)
    assert note.estimated_yes_probability == 0.45
    # Sanity: the chat_json call still happened with a non-empty user prompt.
    user_prompt = cj.call_args.kwargs["user"]
    assert "no live match" in user_prompt.lower()
```

- [ ] **Step 2: Run tests to confirm they fail**

Run: `cd gully-engine && python -m pytest tests/test_researcher.py -v`
Expected: 7 tests fail with `AttributeError: module 'agents.researcher' has no attribute 'research'` or shape errors against the stub. (The current stub only takes `(market)`, not `(market, live)`.)

- [ ] **Step 3: Replace `agents/researcher.py` with the real implementation**

Replace the entire contents of [`gully-engine/agents/researcher.py`](../../../gully-engine/agents/researcher.py) with:

```python
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
```

- [ ] **Step 4: Run tests to confirm they pass**

Run: `cd gully-engine && python -m pytest tests/test_researcher.py -v`
Expected: all 7 tests pass.

- [ ] **Step 5: Run full suite to confirm no regressions**

Run: `cd gully-engine && python -m pytest`
Expected: 102 + 7 = 109 tests pass.

- [ ] **Step 6: Commit**

```bash
git add gully-engine/agents/researcher.py gully-engine/tests/test_researcher.py
git commit -m "Researcher agent: real LLM probability estimator with fallback"
```

---

## Task 3: Decision agent (TDD)

**Files:**
- Create: `gully-engine/tests/test_decision.py`
- Modify (replace contents): `gully-engine/agents/decision.py`

- [ ] **Step 1: Write the failing tests**

Create [`gully-engine/tests/test_decision.py`](../../../gully-engine/tests/test_decision.py) with:

```python
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
    # 5% of $10,000 = $500 = 50,000¢; at 11¢/contract that's ~4545 contracts
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
    # 10¢ edge, implied 50% → kelly = 0.10/0.50 = 0.20, quarter = 0.05
    # min(0.05, MAX_POSITION_PCT=0.05) = 0.05 → at 1000¢ bankroll = 50¢ to risk
    # at 50¢/contract → 1 contract — borderline. Drop bankroll further:
    dec = decide(note, bankroll_cents=20, market=_market(yes=50))
    assert dec.action == "pass"
    assert "size" in dec.reasoning.lower() or "small" in dec.reasoning.lower()


def test_limit_price_is_bid_plus_one_and_clamped_at_99():
    """Limit price = price_to_buy + 1, clamped to <= 99.

    Note: the upper-clamp is defensive — at yes_price=99 we'd need >5¢ edge to
    not pass, which requires probability >1.04 (impossible after researcher's
    clamp). So the clamp covers a defensive code path, not a reachable input.
    """
    note = _note(prob=0.60, confidence=0.6)
    dec = decide(note, bankroll_cents=100_000, market=_market(yes=50))
    assert dec.action == "buy_yes"
    assert dec.limit_price_cents == 51
    assert 1 <= dec.limit_price_cents <= 99
```

- [ ] **Step 2: Run tests to confirm they fail**

Run: `cd gully-engine && python -m pytest tests/test_decision.py -v`
Expected: failures because the stub always returns `pass`.

- [ ] **Step 3: Replace `agents/decision.py` with the real implementation**

Replace the entire contents of [`gully-engine/agents/decision.py`](../../../gully-engine/agents/decision.py) with:

```python
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
    contracts = dollars_to_risk_cents // max(1, price_to_buy)

    if contracts < 1:
        return _pass(
            note.ticker,
            f"size too small: {dollars_to_risk_cents}¢ / {price_to_buy}¢ < 1 contract",
            market.yes_price,
        )

    limit_price_cents = max(1, min(99, price_to_buy + 1))
    return TradeDecision(
        ticker=note.ticker, action=side, contracts=contracts,
        limit_price_cents=limit_price_cents,
        reasoning=(
            f"edge={edge*100:+.1f}¢ kelly={kelly:.3f} fraction={fraction:.4f} "
            f"bankroll=${bankroll_cents/100:.2f} → {contracts} contracts @ {limit_price_cents}¢"
        ),
    )
```

- [ ] **Step 4: Run tests to confirm they pass**

Run: `cd gully-engine && python -m pytest tests/test_decision.py -v`
Expected: all 8 tests pass.

- [ ] **Step 5: Run full suite to confirm no regressions**

Run: `cd gully-engine && python -m pytest`
Expected: 109 + 8 = 117 tests pass.

- [ ] **Step 6: Commit**

```bash
git add gully-engine/agents/decision.py gully-engine/tests/test_decision.py
git commit -m "Decision agent: pure-math Quarter-Kelly sizer"
```

---

## Task 4: PortfolioExit agent (TDD)

**Files:**
- Create: `gully-engine/tests/test_portfolio_exit.py`
- Modify (replace contents): `gully-engine/agents/portfolio_exit.py`

- [ ] **Step 1: Write the failing tests**

Create [`gully-engine/tests/test_portfolio_exit.py`](../../../gully-engine/tests/test_portfolio_exit.py) with:

```python
"""PortfolioExit agent tests — mock chat_json, exercise hold/sell + safety fallback."""

from __future__ import annotations

from unittest.mock import patch

from agents.portfolio_exit import decide
from cricket_data import LiveScore
from exit_monitor import PositionSnapshot
from llm import LlmResponse


def _snap(side: str = "yes", entry: int = 50, mark: int = 60) -> PositionSnapshot:
    return PositionSnapshot(
        ticker="KXIPLGAME-T",
        entry_price_cents=entry, mark_price_cents=mark,
        yes_count=100 if side == "yes" else 0,
        no_count=0 if side == "yes" else 100,
        side=side, opened_at=0, peak_pnl_cents=0,
    )


def _live() -> LiveScore:
    return LiveScore(
        match_id="m1", team_a="A", team_b="B",
        runs_a=180, wickets_a=5, overs_a="20.0",
        runs_b=120, wickets_b=4, overs_b="15.0",
        batting="team_b", target=181, required_run_rate=12.0,
        on_strike_batter=None, non_strike_batter=None, bowler=None, last_balls=[],
    )


def _llm_resp(parsed):
    return LlmResponse(content="(stub)", parsed_json=parsed,
                       model="test-model", latency_ms=10, raw={})


def test_happy_path_hold():
    parsed = {"action": "hold", "confidence": 0.7, "reasoning": "still on track"}
    with patch("agents.portfolio_exit.chat_json", return_value=_llm_resp(parsed)):
        ex = decide(_snap(), _live())
    assert ex.action == "hold"
    assert ex.trigger == "llm"


def test_happy_path_sell():
    parsed = {"action": "sell", "confidence": 0.8, "reasoning": "momentum reversal"}
    with patch("agents.portfolio_exit.chat_json", return_value=_llm_resp(parsed)):
        ex = decide(_snap(), _live())
    assert ex.action == "sell"
    assert ex.trigger == "llm"
    assert "momentum" in ex.note.lower() or "reasoning" in ex.note.lower() or ex.note != ""


def test_fallback_when_llm_returns_none_holds():
    with patch("agents.portfolio_exit.chat_json", return_value=None):
        ex = decide(_snap(), _live())
    assert ex.action == "hold"
    assert "fallback" in ex.note.lower()


def test_fallback_on_malformed_json_holds():
    parsed = {"verdict": "exit"}   # wrong field
    with patch("agents.portfolio_exit.chat_json", return_value=_llm_resp(parsed)):
        ex = decide(_snap(), _live())
    assert ex.action == "hold"
    assert "fallback" in ex.note.lower()


def test_invalid_action_coerces_to_hold():
    parsed = {"action": "liquidate", "confidence": 0.9, "reasoning": "panic"}
    with patch("agents.portfolio_exit.chat_json", return_value=_llm_resp(parsed)):
        ex = decide(_snap(), _live())
    assert ex.action == "hold"
    assert "fallback" in ex.note.lower() or "invalid" in ex.note.lower()


def test_no_live_match_still_calls_llm():
    parsed = {"action": "hold", "confidence": 0.4, "reasoning": "no live ctx"}
    with patch("agents.portfolio_exit.chat_json", return_value=_llm_resp(parsed)) as cj:
        ex = decide(_snap(), live=None)
    assert ex.action == "hold"
    user_prompt = cj.call_args.kwargs["user"]
    assert "no live match" in user_prompt.lower()
```

- [ ] **Step 2: Run tests to confirm they fail**

Run: `cd gully-engine && python -m pytest tests/test_portfolio_exit.py -v`
Expected: failures (current stub returns `hold` for everything but doesn't call `chat_json`, so `cj.call_args` accessor fails; signature mismatch — current stub takes only `(snap)` not `(snap, live)`).

- [ ] **Step 3: Replace `agents/portfolio_exit.py` with the real implementation**

Replace the entire contents of [`gully-engine/agents/portfolio_exit.py`](../../../gully-engine/agents/portfolio_exit.py) with:

```python
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
```

- [ ] **Step 4: Run tests to confirm they pass**

Run: `cd gully-engine && python -m pytest tests/test_portfolio_exit.py -v`
Expected: all 6 tests pass.

- [ ] **Step 5: Run full suite to confirm no regressions**

Run: `cd gully-engine && python -m pytest`
Expected: 117 + 6 = 123 tests pass.

- [ ] **Step 6: Commit**

```bash
git add gully-engine/agents/portfolio_exit.py gully-engine/tests/test_portfolio_exit.py
git commit -m "PortfolioExit agent: LLM hold/sell with safety-default to hold"
```

---

## Task 5: Wire researcher + decision into orchestrator entry pipeline (TDD)

**Files:**
- Create: `gully-engine/tests/test_orchestrator.py`
- Modify: `gully-engine/orchestrator.py` (entry pipeline section)

- [ ] **Step 1: Write the failing entry-pipeline tests**

Create [`gully-engine/tests/test_orchestrator.py`](../../../gully-engine/tests/test_orchestrator.py) with:

```python
"""Orchestrator wiring tests — mock all external services and agents.

Verifies the shadow/live gate around place_limit_order in both pipelines
and that the exit pipeline fetches real mark prices via get_market.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import orchestrator
from agents.decision import TradeDecision
from agents.researcher import ResearchNote
from exit_monitor import ExitDecision
from kalshi_client import KalshiMarket, KalshiPosition


def _set_settings(**overrides):
    """Override frozen Settings dataclass for the duration of a test."""
    from settings import settings as _settings
    originals = {k: getattr(_settings, k) for k in overrides}
    for k, v in overrides.items():
        object.__setattr__(_settings, k, v)
    def restore():
        for k, v in originals.items():
            object.__setattr__(_settings, k, v)
    return restore


def _market(ticker: str = "KXIPLGAME-T", yes: int = 50) -> KalshiMarket:
    return KalshiMarket(
        ticker=ticker, event_ticker=ticker, title="t",
        yes_price=yes, no_price=100 - yes, status="open",
    )


def _position(ticker: str = "KXIPLGAME-T", side: str = "yes") -> KalshiPosition:
    return KalshiPosition(
        ticker=ticker,
        yes_count=100 if side == "yes" else 0,
        no_count=0 if side == "yes" else 100,
        avg_cost_cents=50,
        market_exposure_cents=5000,
    )


# ── Entry pipeline ─────────────────────────────────────────────────────


def test_entry_shadow_mode_does_not_place_order():
    restore = _set_settings(decision_mode="shadow")
    try:
        client = MagicMock()
        client.list_ipl_markets.return_value = [_market(yes=40)]
        client.get_balance.return_value = {"balance": 100_000}
        client.place_limit_order = MagicMock()

        with patch("orchestrator.KalshiClient", return_value=client), \
             patch("orchestrator.get_feed") as gf, \
             patch("orchestrator.scanner_shortlist") as sc, \
             patch("orchestrator.research") as rs, \
             patch("orchestrator.decide") as dc:
            gf.return_value.live_match.return_value = None
            sc.return_value = [MagicMock(ticker="KXIPLGAME-T", score=80, reason="ok")]
            rs.return_value = ResearchNote("KXIPLGAME-T", 0.7, 0.6, "yes")
            dc.return_value = TradeDecision("KXIPLGAME-T", "buy_yes", 5, 41, "edge")
            result = orchestrator.run_entry_pipeline_once(force=True)

        assert result["status"] == "ok"
        assert result["decision_mode"] == "shadow"
        client.place_limit_order.assert_not_called()
        assert result["candidates"][0]["decision"]["action"] == "buy_yes"
        assert result["candidates"][0]["order"] is None
    finally:
        restore()


def test_entry_live_mode_places_order_on_buy():
    restore = _set_settings(decision_mode="live")
    try:
        client = MagicMock()
        client.list_ipl_markets.return_value = [_market(yes=40)]
        client.get_balance.return_value = {"balance": 100_000}
        client.place_limit_order.return_value = {"order_id": "o-1", "status": "queued"}

        with patch("orchestrator.KalshiClient", return_value=client), \
             patch("orchestrator.get_feed") as gf, \
             patch("orchestrator.scanner_shortlist") as sc, \
             patch("orchestrator.research") as rs, \
             patch("orchestrator.decide") as dc:
            gf.return_value.live_match.return_value = None
            sc.return_value = [MagicMock(ticker="KXIPLGAME-T", score=80, reason="ok")]
            rs.return_value = ResearchNote("KXIPLGAME-T", 0.7, 0.6, "yes")
            dc.return_value = TradeDecision("KXIPLGAME-T", "buy_yes", 5, 41, "edge")
            result = orchestrator.run_entry_pipeline_once(force=True)

        client.place_limit_order.assert_called_once_with(
            ticker="KXIPLGAME-T", side="yes", action="buy",
            count=5, limit_price_cents=41,
        )
        assert result["candidates"][0]["order"] == {"order_id": "o-1", "status": "queued"}
    finally:
        restore()


def test_entry_live_mode_does_not_place_order_on_pass():
    restore = _set_settings(decision_mode="live")
    try:
        client = MagicMock()
        client.list_ipl_markets.return_value = [_market(yes=50)]
        client.get_balance.return_value = {"balance": 100_000}
        client.place_limit_order = MagicMock()

        with patch("orchestrator.KalshiClient", return_value=client), \
             patch("orchestrator.get_feed") as gf, \
             patch("orchestrator.scanner_shortlist") as sc, \
             patch("orchestrator.research") as rs, \
             patch("orchestrator.decide") as dc:
            gf.return_value.live_match.return_value = None
            sc.return_value = [MagicMock(ticker="KXIPLGAME-T", score=80, reason="ok")]
            rs.return_value = ResearchNote("KXIPLGAME-T", 0.51, 0.6, "low edge")
            dc.return_value = TradeDecision("KXIPLGAME-T", "pass", 0, 50, "edge too low")
            result = orchestrator.run_entry_pipeline_once(force=True)

        client.place_limit_order.assert_not_called()
        assert result["candidates"][0]["decision"]["action"] == "pass"
    finally:
        restore()
```

- [ ] **Step 2: Run tests to confirm they fail**

Run: `cd gully-engine && python -m pytest tests/test_orchestrator.py -v`
Expected: failures — module-level imports `research` and `decide` don't exist in `orchestrator` yet.

- [ ] **Step 3: Update orchestrator entry pipeline**

In [`gully-engine/orchestrator.py`](../../../gully-engine/orchestrator.py), at the top of the file, in the imports block, add after `from agents.scanner import shortlist as scanner_shortlist`:

```python
from agents.researcher import research
from agents.decision import decide
```

Then replace the body of `run_entry_pipeline_once` (the `try:` block) with:

```python
    try:
        feed = get_feed()
        live = feed.live_match()
        if not live and not force:
            return {"status": "skipped", "reason": "no_live_match"}

        client = KalshiClient()
        markets = client.list_ipl_markets()
        balance_resp = client.get_balance() or {}
        balance = int(balance_resp.get("balance", 0) or 0)
        market_by_ticker = {m.ticker: m for m in markets}

        candidates = scanner_shortlist(markets, max_results=5)
        log.info(
            "orchestrator.entry: %d markets → %d scanner candidates%s",
            len(markets), len(candidates),
            (" [" + ", ".join(f"{c.ticker} ({c.score})" for c in candidates) + "]") if candidates else "",
        )

        results = []
        for c in candidates:
            market = market_by_ticker.get(c.ticker)
            if market is None:
                continue
            note = research(market, live)
            dec = decide(note, bankroll_cents=balance, market=market)
            order_resp = None
            if dec.action != "pass" and settings.decision_mode == "live":
                side = "yes" if dec.action == "buy_yes" else "no"
                try:
                    order_resp = client.place_limit_order(
                        ticker=dec.ticker, side=side, action="buy",
                        count=dec.contracts, limit_price_cents=dec.limit_price_cents,
                    )
                except Exception as e:  # noqa: BLE001 — keep loop alive on order errors
                    log.exception("orchestrator.entry: place_limit_order failed for %s", dec.ticker)
                    order_resp = {"error": str(e)}
            results.append({
                "ticker": c.ticker, "score": c.score, "scan_reason": c.reason,
                "research": {
                    "estimated_yes_probability": note.estimated_yes_probability,
                    "confidence": note.confidence, "reasoning": note.reasoning,
                },
                "decision": {
                    "action": dec.action, "contracts": dec.contracts,
                    "limit_price_cents": dec.limit_price_cents, "reasoning": dec.reasoning,
                },
                "order": order_resp,
            })

        return {
            "status": "ok",
            "markets_scanned": len(markets),
            "decision_mode": settings.decision_mode,
            "live": bool(live),
            "candidates": results,
        }
    finally:
        _entry_lock.release()
```

- [ ] **Step 4: Run tests to confirm they pass**

Run: `cd gully-engine && python -m pytest tests/test_orchestrator.py -v`
Expected: 3 entry-pipeline tests pass.

- [ ] **Step 5: Run full suite to confirm no regressions**

Run: `cd gully-engine && python -m pytest`
Expected: 123 + 3 = 126 tests pass.

- [ ] **Step 6: Commit**

```bash
git add gully-engine/orchestrator.py gully-engine/tests/test_orchestrator.py
git commit -m "Wire researcher + decision into orchestrator entry pipeline"
```

---

## Task 6: Wire portfolio_exit + real mark prices into exit pipeline (TDD)

**Files:**
- Modify: `gully-engine/exit_monitor.py:117-126` (LLM-path placeholder → call portfolio_exit)
- Modify: `gully-engine/orchestrator.py` (`run_exit_monitor_once` — fetch real mark, gate sell)
- Modify: `gully-engine/tests/test_orchestrator.py` (append 3 exit tests)

- [ ] **Step 1: Append the failing exit-pipeline tests**

Append to [`gully-engine/tests/test_orchestrator.py`](../../../gully-engine/tests/test_orchestrator.py):

```python
# ── Exit pipeline ──────────────────────────────────────────────────────


def _hold_decision(ticker: str, mark: int) -> ExitDecision:
    return ExitDecision(ticker=ticker, trigger="llm", action="hold",
                        mode="shadow", mark_price_cents=mark,
                        pnl_cents_at_decision=0, note="t")


def _sell_decision(ticker: str, mark: int, mode: str) -> ExitDecision:
    return ExitDecision(ticker=ticker, trigger="llm", action="sell",
                        mode=mode, mark_price_cents=mark,
                        pnl_cents_at_decision=100, note="t")


def test_exit_shadow_mode_does_not_place_sell_on_sell_decision():
    restore = _set_settings(exit_mode="shadow")
    try:
        client = MagicMock()
        client.list_positions.return_value = [_position(ticker="KXIPLGAME-T", side="yes")]
        client.get_market.return_value = _market(ticker="KXIPLGAME-T", yes=70)
        client.place_limit_order = MagicMock()

        with patch("orchestrator.KalshiClient", return_value=client), \
             patch("orchestrator.evaluate") as ev:
            ev.return_value = _sell_decision("KXIPLGAME-T", 70, "shadow")
            result = orchestrator.run_exit_monitor_once(force=True)

        client.place_limit_order.assert_not_called()
        assert result["actions"][0]["action"] == "sell"
        assert result["actions"][0]["order"] is None
        assert result["exit_mode"] == "shadow"
    finally:
        restore()


def test_exit_live_mode_places_sell_on_sell_decision():
    restore = _set_settings(exit_mode="live")
    try:
        client = MagicMock()
        client.list_positions.return_value = [_position(ticker="KXIPLGAME-T", side="yes")]
        client.get_market.return_value = _market(ticker="KXIPLGAME-T", yes=70)
        client.place_limit_order.return_value = {"order_id": "sell-1", "status": "queued"}

        with patch("orchestrator.KalshiClient", return_value=client), \
             patch("orchestrator.evaluate") as ev:
            ev.return_value = _sell_decision("KXIPLGAME-T", 70, "live")
            result = orchestrator.run_exit_monitor_once(force=True)

        client.place_limit_order.assert_called_once_with(
            ticker="KXIPLGAME-T", side="yes", action="sell",
            count=100, limit_price_cents=69,   # mark - 1
        )
        assert result["actions"][0]["order"] == {"order_id": "sell-1", "status": "queued"}
    finally:
        restore()


def test_exit_pipeline_fetches_real_mark_via_get_market():
    """The snapshot passed into evaluate() must use yes_price / no_price from get_market,
    not avg_cost_cents."""
    restore = _set_settings(exit_mode="shadow")
    try:
        client = MagicMock()
        client.list_positions.return_value = [_position(ticker="KXIPLGAME-T", side="yes")]
        client.get_market.return_value = _market(ticker="KXIPLGAME-T", yes=73)
        client.place_limit_order = MagicMock()

        captured = {}
        def _eval(snap, *, now=None):
            captured["mark"] = snap.mark_price_cents
            return _hold_decision(snap.ticker, snap.mark_price_cents)

        with patch("orchestrator.KalshiClient", return_value=client), \
             patch("orchestrator.evaluate", side_effect=_eval):
            orchestrator.run_exit_monitor_once(force=True)

        assert captured["mark"] == 73   # yes_price from get_market, not avg_cost_cents (50)
        client.get_market.assert_called_once_with("KXIPLGAME-T")
    finally:
        restore()
```

- [ ] **Step 2: Run the new tests to confirm they fail**

Run: `cd gully-engine && python -m pytest tests/test_orchestrator.py -v`
Expected: 3 entry tests pass; 3 exit tests fail (no `exit_mode` field in response, no `order` field, mark is `avg_cost_cents=50` not `73`).

- [ ] **Step 3: Update `exit_monitor.evaluate` to delegate to portfolio_exit**

In [`gully-engine/exit_monitor.py`](../../../gully-engine/exit_monitor.py), replace the LLM-path block (currently lines 117-126, the `return ExitDecision(...note="llm placeholder: hold")` block) with:

```python
    # LLM path — delegate to portfolio_exit agent.
    # Imports inside the function: agents.portfolio_exit imports ExitDecision and
    # PositionSnapshot from this module, so a top-level import would be circular.
    from agents.portfolio_exit import decide as llm_decide
    from cricket_data import get_feed
    return llm_decide(snap, live=get_feed().live_match())
```

- [ ] **Step 4: Update `orchestrator.run_exit_monitor_once`**

Replace the body of `run_exit_monitor_once` (the `try:` block) in [`gully-engine/orchestrator.py`](../../../gully-engine/orchestrator.py) with:

```python
    try:
        client = KalshiClient()
        positions = client.list_positions()
        decisions = []
        now = int(time.time())
        for p in positions:
            side = "yes" if p.yes_count >= p.no_count else "no"
            market = client.get_market(p.ticker)
            if market is not None:
                mark = market.yes_price if side == "yes" else market.no_price
            else:
                mark = p.avg_cost_cents   # fallback: stale mark; LLM will see zero P&L
            snap = PositionSnapshot(
                ticker=p.ticker,
                entry_price_cents=p.avg_cost_cents,
                mark_price_cents=mark,
                yes_count=p.yes_count, no_count=p.no_count,
                side=side,
                opened_at=now - 600,    # TODO(phase-4): track real open time per position
                peak_pnl_cents=0,       # TODO(phase-4): track peak P&L for trailing-stop
            )
            exit_dec = evaluate(snap, now=now)
            order_resp = None
            if exit_dec.action == "sell" and settings.exit_mode == "live":
                try:
                    order_resp = client.place_limit_order(
                        ticker=p.ticker, side=side, action="sell",
                        count=max(p.yes_count, p.no_count),
                        limit_price_cents=max(1, mark - 1),
                    )
                except Exception as e:  # noqa: BLE001 — keep loop alive on order errors
                    log.exception("orchestrator.exit: place_limit_order failed for %s", p.ticker)
                    order_resp = {"error": str(e)}
            decisions.append({
                "ticker": exit_dec.ticker, "action": exit_dec.action,
                "trigger": exit_dec.trigger, "mode": exit_dec.mode,
                "note": exit_dec.note, "order": order_resp,
            })
        return {
            "status": "ok",
            "evaluated": len(decisions),
            "exit_mode": settings.exit_mode,
            "actions": decisions,
        }
    finally:
        _exit_lock.release()
```

- [ ] **Step 5: Run tests to confirm they pass**

Run: `cd gully-engine && python -m pytest tests/test_orchestrator.py -v`
Expected: all 6 orchestrator tests pass.

- [ ] **Step 6: Run full suite to confirm no regressions**

Run: `cd gully-engine && python -m pytest`
Expected: 126 + 3 = 129 tests pass.

- [ ] **Step 7: Commit**

```bash
git add gully-engine/exit_monitor.py gully-engine/orchestrator.py gully-engine/tests/test_orchestrator.py
git commit -m "Wire portfolio_exit + real mark prices into exit pipeline"
```

---

## Task 7: Update README + HANDOFF + ARCHITECTURE

**Files:**
- Modify: `README.md`
- Modify: `docs/HANDOFF.md`
- Modify: `docs/ARCHITECTURE.md`

- [ ] **Step 1: Update README**

Find the status row in [`README.md`](../../../README.md) for the agents (look for "Researcher", "Decision", "Portfolio exit" or similar). Update them from "stub" / "not yet wired" to live status. Add a new env-var row for `GULLYTRADER_DECISION_MODE` (default `shadow`, values `shadow|live`) — same row format as `GULLYTRADER_EXIT_MODE`. Bump the test count reference (e.g. "102 tests passing" → "129 tests passing").

If a "What's wired" or "Status" section exists, add:

> **Phase 3 (2026-05-01):** Researcher + Decision + PortfolioExit agents wired end-to-end. Entry pipeline runs Scanner → Researcher (LLM) → Decision (pure-math Quarter-Kelly) → orchestrator places live order only when `GULLYTRADER_DECISION_MODE=live`. Exit pipeline fetches real mark prices via `get_market`, hard stops still bypass the LLM, LLM exits run via PortfolioExit agent and place live sells only when `GULLYTRADER_EXIT_MODE=live`.

- [ ] **Step 2: Update HANDOFF**

In [`docs/HANDOFF.md`](../../../docs/HANDOFF.md), under "Current state", add bullets for:

> - **Researcher agent:** wired. LLM (settings.research_model, default deepseek/deepseek-chat-v3-0324) returns ResearchNote{estimated_yes_probability, confidence, reasoning}. Falls back to confidence=0 (which makes Decision skip) when LLM unavailable.
> - **Decision agent:** wired. Pure-math Quarter-Kelly sizer; no LLM call. Skips on edge<5¢, confidence=0, contracts<1, or zero bankroll. Limit price = best-bid + 1¢ (TODO: expose yes_ask/no_ask for marketable orders).
> - **PortfolioExit agent:** wired. LLM (settings.exit_model, default qwen) returns hold/sell. Defaults to HOLD on any failure mode (LLM unavailable, malformed JSON, invalid action).
> - **Orchestrator entry pipeline:** end-to-end. Scanner → Researcher → Decision per candidate; `place_limit_order` only fires when `GULLYTRADER_DECISION_MODE=live`.
> - **Orchestrator exit pipeline:** real mark prices via `client.get_market(ticker)` per position; LLM path delegates to PortfolioExit; live sells only when `GULLYTRADER_EXIT_MODE=live`.
> - **Tests:** **129 passing** (Phase 3 added 27 across researcher / decision / portfolio_exit / orchestrator wiring).

Then in "Next-up", REMOVE sections 1, 2, 3 (Researcher / Decision / PortfolioExit). The remaining items renumber down. Add a new "Known limitations carried into Phase 4":

> - `peak_pnl_cents=0` placeholder in orchestrator exit pipeline → trailing stop never fires. Needs per-position peak-P&L tracking (likely a new in-memory dict keyed by ticker, or a dedicated DB column).
> - `opened_at=now-600` placeholder → time stop fires arbitrarily based on current wall clock. Needs real position-open timestamp tracked from fills.
> - `KalshiMarket` exposes only `yes_price`/`no_price` (bid side). Decision's `limit = bid + 1¢` posts at top of queue but won't fill unless someone crosses. For marketable orders, expose `yes_ask`/`no_ask` from `_market_from_dict`.

- [ ] **Step 3: Update ARCHITECTURE**

In [`docs/ARCHITECTURE.md`](../../../docs/ARCHITECTURE.md), update the module-responsibilities table rows for `agents/researcher.py`, `agents/decision.py`, `agents/portfolio_exit.py` from "Stub. ..." to real descriptions:

> | [`agents/researcher.py`](../gully-engine/agents/researcher.py) | Implemented. Calls `settings.research_model` via OpenRouter to estimate true YES probability for one market. Returns `ResearchNote{estimated_yes_probability, confidence, reasoning}`. Probability clamped to [0,1]. Fallback on LLM failure → `confidence=0`. |
> | [`agents/decision.py`](../gully-engine/agents/decision.py) | Implemented. Pure-math Quarter-Kelly sizing on `ResearchNote`. No LLM call. `pass` if edge<5¢, confidence=0, or contracts<1. Limit price = best-bid + 1¢, clamped [1, 99]. |
> | [`agents/portfolio_exit.py`](../gully-engine/agents/portfolio_exit.py) | Implemented. LLM hold/sell on a single position. Defaults to HOLD on any failure (LLM unavailable, malformed JSON, invalid action). |

Update the "Manual entry-pipeline trigger" data flow block (around line 130) to show the new shape:

> ```
> POST /api/orchestrator/run-entry
>    └─ orchestrator.run_entry_pipeline_once(force=True)
>        ├─ feed.live_match()
>        ├─ KalshiClient.list_ipl_markets()
>        ├─ KalshiClient.get_balance()  → bankroll
>        ├─ scanner_shortlist(markets)  → [ScanCandidate]
>        └─ for each candidate:
>            ├─ researcher.research(market, live)  → ResearchNote (LLM)
>            ├─ decision.decide(note, bankroll, market)  → TradeDecision (pure math)
>            └─ if action != 'pass' and decision_mode == 'live':
>                  KalshiClient.place_limit_order(...)
>        return {markets_scanned, decision_mode, live, candidates: [...]}
> ```

Update the "Manual exit-monitor trigger" data flow block similarly:

> ```
> POST /api/orchestrator/run-exit
>    └─ orchestrator.run_exit_monitor_once(force=True)
>        ├─ KalshiClient.list_positions()
>        └─ for each position:
>            ├─ KalshiClient.get_market(ticker)  → real mark price
>            ├─ build PositionSnapshot
>            └─ exit_monitor.evaluate(snap)
>                ├─ check stop_loss / trailing_stop / time_stop  (deterministic)
>                └─ if no hard stop: agents.portfolio_exit.decide(snap, live)  (LLM)
>            └─ if action == 'sell' and exit_mode == 'live':
>                  KalshiClient.place_limit_order(action='sell', limit=mark-1)
>        return {evaluated, exit_mode, actions: [...]}
> ```

- [ ] **Step 4: Commit docs**

```bash
git add README.md docs/HANDOFF.md docs/ARCHITECTURE.md
git commit -m "Docs: Phase 3 agent wiring + decision_mode + known Phase 4 carry-overs"
```

---

## Task 8: Push branch and open PR

**Files:** none — git/gh operations.

- [ ] **Step 1: Push branch**

Run: `git push -u origin feat/phase-3-agents`
Expected: branch pushed; `origin/feat/phase-3-agents` tracking set.

- [ ] **Step 2: Open PR**

Run:

```bash
gh pr create --title "Phase 3: Researcher + Decision + PortfolioExit agents (shadow-mode end-to-end)" --body "$(cat <<'EOF'
## Summary

- **Researcher agent** (`agents/researcher.py`): real LLM probability estimator with `confidence=0` fallback.
- **Decision agent** (`agents/decision.py`): pure-math Quarter-Kelly sizer; no LLM call.
- **PortfolioExit agent** (`agents/portfolio_exit.py`): LLM hold/sell with safety-default to HOLD on any failure.
- **Orchestrator entry pipeline**: Scanner → Researcher → Decision wired end-to-end. `place_limit_order` gated on `GULLYTRADER_DECISION_MODE=live` (default `shadow`).
- **Orchestrator exit pipeline**: real mark prices via `KalshiClient.get_market`. Sells gated on `GULLYTRADER_EXIT_MODE=live`.
- **New setting**: `GULLYTRADER_DECISION_MODE` (`shadow|live`, default `shadow`).
- **Tests**: 102 → 129 (+27).

## Manual smoke (operator verification)

These are NOT automated — they require the operator to boot uvicorn against demo Kalshi creds + a real OpenRouter key:

- [ ] Boot uvicorn with `KALSHI_API_ENV=demo`, `GULLYTRADER_DECISION_MODE=shadow`. POST `/api/orchestrator/run-entry`. Verify response shape includes `research` and `decision` blocks per candidate; verify `agent_logs` has fresh `scanner` and `researcher` rows.
- [ ] POST `/api/orchestrator/run-exit` against the mock positions. Verify response shape; verify `agent_logs` has `portfolio_exit` rows where no hard stop fired.
- [ ] With strict mode + missing OpenRouter key — verify researcher and portfolio_exit gracefully fall back; orchestrator response still well-formed.
- [ ] DEFER until at least one full IPL match has been observed in shadow mode without errors: set `GULLYTRADER_DECISION_MODE=live`, `GULLYTRADER_EXIT_MODE=live`, watch first `place_limit_order` go out.

## Known limitations carried into Phase 4

- `peak_pnl_cents=0` placeholder in orchestrator exit pipeline → trailing stop never fires.
- `opened_at=now-600` placeholder → time stop fires based on wall clock, not real position-open time.
- `KalshiMarket` exposes only bid side (`yes_price`/`no_price`); decision posts at `bid+1¢` which won't fill unless someone crosses.

## Spec & plan

- Spec: [`docs/superpowers/specs/2026-05-01-phase-3-agents-design.md`](docs/superpowers/specs/2026-05-01-phase-3-agents-design.md)
- Plan: [`docs/superpowers/plans/2026-05-01-phase-3-agents.md`](docs/superpowers/plans/2026-05-01-phase-3-agents.md)

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

Expected: PR URL printed.

- [ ] **Step 3: Done**

Phase 3 ships as one PR. Operator runs the manual smoke tests above before flipping `decision_mode=live` / `exit_mode=live` in any deployed env.
