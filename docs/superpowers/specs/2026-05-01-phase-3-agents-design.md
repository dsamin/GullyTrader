# Phase 3 — Researcher / Decision / PortfolioExit agents

**Status:** approved 2026-05-01 (user delegated remaining decisions to Claude — see "Open questions resolved" section).
**Branch:** `feat/phase-3-agents`.
**One PR.** Matches established repo pattern (Phase 1 = PR #2, Phase 2 = PR #3).

## Goal

Replace three stub agents in the trading pipeline with real LLM-driven implementations:

- `agents/researcher.py` — pure pass-through stub (returns implied price unchanged) → real LLM probability estimator
- `agents/decision.py` — always returns `pass` → real Quarter-Kelly sizer
- `agents/portfolio_exit.py` — always returns `hold` → real LLM exit-decision agent

Wire them into the orchestrator so the entry pipeline runs end-to-end (Scanner → Researcher → Decision → optional `place_limit_order`) and the exit monitor delegates to the LLM exit agent when no hard stop fires.

## Non-goals

- Phase 4 work (bot/status realness, frontend cleanup, cricket_matches orphan).
- Fixing `peak_pnl_cents=0` and `opened_at=now-600` placeholders in [orchestrator.py:107-108](../../../gully-engine/orchestrator.py#L107-L108) — TODO comments only, real fix is its own PR.
- Adding `yes_ask`/`no_ask` to `KalshiMarket` — TODO in decision.py, follow-up phase.
- Implementing peak-P&L tracking or per-position open-time tracking.

## Architecture

```
Scanner (existing)              ─→ list[ScanCandidate]
  └─ Researcher (3a, new)       ─→ list[ResearchNote]      (one per candidate)
      └─ Decision (3b, new)     ─→ list[TradeDecision]     (one per candidate)
          └─ orchestrator       ─→ KalshiClient.place_limit_order  (live mode only)

ExitMonitor.evaluate (existing) ─→ ExitDecision (hard stop)
  └─ PortfolioExit (3c, new)    ─→ ExitDecision (LLM)      (when no hard stop)
      └─ orchestrator           ─→ KalshiClient.place_limit_order  (live mode only)
```

**Key invariant: pure agents, side-effecting orchestrator.** None of the agent modules call `place_limit_order`. They return dataclasses. The orchestrator is the only place that touches real money — and the only place where the shadow/live gate lives.

## Settings change

One new field added to [settings.py](../../../gully-engine/settings.py):

```python
decision_mode: str = os.getenv("GULLYTRADER_DECISION_MODE", "shadow")
```

Mirrors the existing `exit_mode` field. Strings: `"shadow"` (default) or `"live"`. `exit_mode` field already exists, no change.

`.env.example` (if it exists, otherwise the README env section) gets a documented `GULLYTRADER_DECISION_MODE=shadow` row.

## Components

### 3a. `agents/researcher.py`

**Signature:**
```python
def research(market: KalshiMarket, live: LiveScore | None) -> ResearchNote: ...
```

The orchestrator calls `get_feed().live_match()` once per pipeline pass and threads the result into every `research()` call (testability — researcher does not call `get_feed()` itself).

**Output dataclass:** existing `ResearchNote` — no field changes.
```python
@dataclass
class ResearchNote:
    ticker: str
    estimated_yes_probability: float   # 0.0 - 1.0
    confidence: float                  # 0.0 - 1.0
    reasoning: str
```

**System prompt:**
> You are a quantitative cricket prediction-market analyst. Given live IPL match state and a YES/NO market, estimate the true probability that YES resolves. Return ONLY this JSON shape: `{"estimated_probability": <0.0-1.0>, "confidence": <0.0-1.0>, "reasoning": "<paragraph>"}`. No prose around the JSON.

**User prompt fields:**
- Market: `ticker`, `title`, `yes_price`, `no_price` (cents)
- Live block (if `live is not None`): teams, runs/wickets/overs for both, batting side, target, RRR, on-strike batter, non-strike batter, bowler, last_balls
- Live block (if `live is None`): "no live match — score on pre-game context only."

**Validation & fallback:**
- Clamp `estimated_probability` to `[0.0, 1.0]`.
- If LLM returns `None` or parsed_json is not a dict or required fields missing or wrong type:
  ```python
  ResearchNote(
      ticker=market.ticker,
      estimated_yes_probability=market.yes_price / 100,
      confidence=0.0,
      reasoning="fallback: LLM unavailable",
  )
  ```
- The `confidence=0.0` is the **load-bearing signal** that makes the decision agent skip.

**LLM call:** `chat_json(agent="researcher", model=settings.research_model, system=..., user=..., temperature=0.2, max_tokens=900, log_ticker=market.ticker)`.

### 3b. `agents/decision.py`

**Signature:**
```python
def decide(note: ResearchNote, *, bankroll_cents: int, market: KalshiMarket) -> TradeDecision: ...
```

**No LLM call.** Pure math. Justification: researcher's output is already an LLM-derived probability with confidence; the decision agent's job is mechanical sizing on that signal. Keeps the agent cheap (no per-candidate LLM cost), deterministic, and trivial to test (no `chat_json` mock needed). The user spec's test list never mentions mocking `chat_json` for decision tests.

**Output dataclass:** existing `TradeDecision` — no field changes.
```python
@dataclass
class TradeDecision:
    ticker: str
    action: str           # 'pass' | 'buy_yes' | 'buy_no'
    contracts: int
    limit_price_cents: int
    reasoning: str
```

**Constants** (already in stub, keep):
```python
KELLY_FRACTION = 0.25
MIN_EDGE = 0.05            # 5¢
MAX_POSITION_PCT = 0.05    # 5% of bankroll
```

**Logic:**
1. If `note.confidence == 0.0` → pass with reasoning "researcher fell back, no signal".
2. `implied = market.yes_price / 100`.
3. `edge = note.estimated_yes_probability - implied` (positive → underpriced YES; negative → overpriced YES = buy NO).
4. If `abs(edge) < MIN_EDGE` → pass with reasoning showing edge value.
5. Side: `buy_yes` if edge > 0, else `buy_no`.
6. Kelly fraction:
   - For YES: `kelly = edge / (1 - implied)` (positive)
   - For NO: `kelly = -edge / implied` (positive — flip sign)
7. `fraction = min(kelly * KELLY_FRACTION, MAX_POSITION_PCT)`.
8. `dollars_to_risk_cents = bankroll_cents * fraction`.
9. `price_to_buy = market.yes_price if buy_yes else market.no_price`.
10. `contracts = int(dollars_to_risk_cents / max(1, price_to_buy))`.
11. If `contracts < 1` → pass with reasoning "size too small".
12. `limit_price_cents = max(1, min(99, price_to_buy + 1))` (option C: passive at top of queue, TODO for `yes_ask`/`no_ask`).
13. Return `TradeDecision(action=side, contracts, limit_price_cents, reasoning="edge=%.0f¢ fraction=%.3f bankroll=$%.2f")`.

**Bankroll note:** orchestrator passes `KalshiClient.get_balance().get("balance", 0)` as `bankroll_cents`. Zero-bankroll → step 8 → step 11 → pass.

### 3c. `agents/portfolio_exit.py`

**Signature:**
```python
def decide(snap: PositionSnapshot, live: LiveScore | None) -> ExitDecision: ...
```

**Output dataclass:** existing `ExitDecision` — no field changes. Trigger always = `"llm"`. Action ∈ `{'hold', 'sell'}`.

**System prompt:**
> You are a quantitative cricket trader managing an open IPL position. Decide whether to HOLD or SELL given current match state and position P&L. Return ONLY this JSON shape: `{"action": "hold"|"sell", "confidence": <0.0-1.0>, "reasoning": "<paragraph>"}`. No prose around the JSON.

**User prompt fields:**
- Position: ticker, side (yes/no), entry_price_cents, mark_price_cents, contracts, per-contract pnl, total pnl_cents
- Live block (same as researcher) or "no live match — score on pre-game context only."

**Validation & fallback:**
- Action must be `"hold"` or `"sell"`. Anything else → coerce to `"hold"` with note "fallback: invalid action".
- If LLM returns `None` or malformed JSON: `ExitDecision(trigger="llm", action="hold", mode=settings.exit_mode, mark_price_cents=snap.mark_price_cents, pnl_cents_at_decision=<computed>, note="fallback: LLM unavailable")`.

**LLM call:** `chat_json(agent="portfolio_exit", model=settings.exit_model, ...)` with `log_ticker=snap.ticker`.

**Per-contract pnl computation** (mirror exit_monitor's `_hard_stop`):
```python
direction = 1 if snap.side == "yes" else -1
pnl_per_contract_cents = direction * (snap.mark_price_cents - snap.entry_price_cents)
contracts = max(snap.yes_count, snap.no_count)
pnl_cents = pnl_per_contract_cents * contracts
```

## Wiring changes

### `orchestrator.run_entry_pipeline_once`

Replace the `# TODO: researcher / decision agents (next phase)` block with:

```python
balance = client.get_balance().get("balance", 0)
market_by_ticker = {m.ticker: m for m in markets}
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
        order_resp = client.place_limit_order(
            ticker=dec.ticker,
            side=side,
            action="buy",
            count=dec.contracts,
            limit_price_cents=dec.limit_price_cents,
        )
    results.append({
        "ticker": c.ticker, "score": c.score, "scan_reason": c.reason,
        "research": {"estimated_yes_probability": note.estimated_yes_probability,
                     "confidence": note.confidence, "reasoning": note.reasoning},
        "decision": {"action": dec.action, "contracts": dec.contracts,
                     "limit_price_cents": dec.limit_price_cents, "reasoning": dec.reasoning},
        "order": order_resp,
    })
return {"status": "ok", "markets_scanned": len(markets), "decision_mode": settings.decision_mode,
        "candidates": results, "live": bool(live)}
```

Imports added at module top (use `from ... import` to avoid name-shadowing of the local `dec` / `note` vars):
```python
from agents.researcher import research
from agents.decision import decide
```

### `orchestrator.run_exit_monitor_once`

Replace the snapshot-build block with real mark prices:

```python
client = KalshiClient()
positions = client.list_positions()
decisions = []
now = int(time.time())
for p in positions:
    side = "yes" if p.yes_count >= p.no_count else "no"
    market = client.get_market(p.ticker)
    if market is None:
        mark = p.avg_cost_cents   # fallback: stale mark; LLM will see zero P&L
    else:
        mark = market.yes_price if side == "yes" else market.no_price
    snap = PositionSnapshot(
        ticker=p.ticker,
        entry_price_cents=p.avg_cost_cents,
        mark_price_cents=mark,
        yes_count=p.yes_count, no_count=p.no_count,
        side=side,
        opened_at=now - 600,    # TODO(phase-4): track real open time
        peak_pnl_cents=0,       # TODO(phase-4): track peak P&L for trailing-stop hard-stop
    )
    exit_dec = evaluate(snap, now=now)
    order_resp = None
    if exit_dec.action == "sell" and settings.exit_mode == "live":
        order_resp = client.place_limit_order(
            ticker=p.ticker, side=side, action="sell",
            count=max(p.yes_count, p.no_count),
            limit_price_cents=max(1, mark - 1),
        )
    decisions.append({
        "ticker": exit_dec.ticker, "action": exit_dec.action, "trigger": exit_dec.trigger,
        "mode": exit_dec.mode, "note": exit_dec.note, "order": order_resp,
    })
return {"status": "ok", "evaluated": len(decisions), "exit_mode": settings.exit_mode, "actions": decisions}
```

### `exit_monitor.evaluate`

Replace the `# LLM path — wired up later in agents/portfolio_exit.py. For now: hold.` block with:

```python
# LLM path — delegate to portfolio_exit agent.
from agents.portfolio_exit import decide as llm_decide
from cricket_data import get_feed
return llm_decide(snap, live=get_feed().live_match())
```

(Imports inside the function: `agents.portfolio_exit` imports `ExitDecision` and `PositionSnapshot` from `exit_monitor`, so a top-level import here would be circular.)

## Error handling

| Failure mode | Behavior |
|---|---|
| `chat_json` returns `None` | Researcher: confidence=0 fallback. PortfolioExit: hold fallback. |
| Malformed JSON / wrong shape | Same as None. |
| Researcher confidence=0 | Decision passes (no signal). |
| Probability outside [0,1] | Clamp at researcher boundary. |
| Decision action ∉ {pass, buy_yes, buy_no} | Not possible (pure math). |
| PortfolioExit action ∉ {hold, sell} | Default to hold. |
| `place_limit_order` returns `{"error": ...}` | Captured into the orchestrator response, loop continues. Don't raise. |
| KalshiClient unauthed in shadow | Works fine (mock data path). |
| KalshiClient unauthed in prod | Already raises at init (Phase 2 strict-mode guarantee). |
| DB write failure in `_persist_agent_log` | Already swallowed in `llm.py` — no change. |
| Empty candidate list | Each agent returns `[]`; orchestrator returns `candidates: []`. |

## Testing

Three new test files mirroring [`test_scanner.py`](../../../gully-engine/tests/test_scanner.py) exactly: `_llm_resp` helper, `patch("agents.<name>.chat_json", return_value=...)`. External services always mocked.

### `tests/test_researcher.py` (~7 tests)
1. happy-path probability extraction
2. fallback when LLM returns None (confidence=0, prob=implied)
3. fallback on malformed JSON (no `estimated_probability` field)
4. fallback when parsed_json is not a dict
5. probability clamp at upper bound (>1 → 1.0)
6. probability clamp at lower bound (<0 → 0.0)
7. no-live-match path (live=None) — should still call LLM with pre-game prompt

### `tests/test_decision.py` (~8 tests)
1. confidence=0 → pass
2. low edge (<5¢) → pass
3. buy_yes happy path (positive edge above 5¢)
4. buy_no happy path (negative edge below -5¢)
5. max-position clamp (huge edge clipped to 5% bankroll)
6. zero-bankroll → contracts=0 → pass
7. tiny-bankroll → contracts<1 → pass
8. limit_price = bid+1, clamped at 99 (test with yes_price=99 → still 99)

### `tests/test_portfolio_exit.py` (~6 tests)
1. happy-path sell
2. happy-path hold
3. fallback when LLM returns None (action=hold)
4. fallback on malformed JSON
5. invalid action ('exit_now', 'liquidate', etc.) → hold
6. no-live-match path

### `tests/test_orchestrator.py` (~6 tests, NEW FILE)
1. entry pipeline shadow mode: `place_limit_order` NOT called even when decision = buy_yes
2. entry pipeline live mode: `place_limit_order` IS called when decision = buy_yes
3. entry pipeline live mode: `place_limit_order` NOT called when decision = pass
4. exit pipeline shadow mode: `place_limit_order` NOT called even when exit = sell
5. exit pipeline live mode: `place_limit_order` IS called when exit = sell
6. exit pipeline fetches real mark prices via `get_market`

External services (`KalshiClient`, `chat_json`, `get_feed`) all mocked.

**Total target:** 102 → ~130 tests passing.

## Documentation updates required

Per [CLAUDE.md mandate](../../../CLAUDE.md), every code change updates README + relevant docs:

- **README.md** — flip "Researcher / Decision / PortfolioExit" status from stub → wired. Add `GULLYTRADER_DECISION_MODE` to env table. Bump test count to ~130.
- **docs/HANDOFF.md** — move Phase 3 items from "Next-up" to "Current state". Note that orchestrator's entry pipeline is now end-to-end. Note known limitations (`peak_pnl_cents=0`, `opened_at=placeholder`, `yes_ask`/`no_ask` not exposed).
- **docs/ARCHITECTURE.md** — update agent rows in module-responsibilities table from "Stub" → real description. Update entry/exit data-flow blocks to show researcher/decision/portfolio_exit.

## Manual smoke verification (post-merge)

These are the human-operator steps for the PR description, not test cases:

1. Boot uvicorn with `KALSHI_API_ENV=demo`, `GULLYTRADER_DECISION_MODE=shadow`, real OpenRouter key.
2. `POST /api/orchestrator/run-entry` — verify response shape includes `research` and `decision` blocks per candidate; verify `agent_logs` table has fresh `scanner`, `researcher` rows. (Decision agent doesn't write agent_logs since it has no LLM call.)
3. `POST /api/orchestrator/run-exit` against the mock positions — verify response shape; verify `agent_logs` has `portfolio_exit` rows where no hard stop fired.
4. With strict mode + missing OpenRouter key — verify researcher and portfolio_exit gracefully fall back (decision passes; exit holds); orchestrator response still well-formed.
5. (Live-money — DEFER until at least one full IPL match has been observed in shadow mode without errors.) Set `GULLYTRADER_DECISION_MODE=live`, `GULLYTRADER_EXIT_MODE=live`, watch first place_limit_order go out, verify Kalshi accepts.

## Open questions resolved (audit trail)

- **Q1 (limit price):** option C — `bid + 1¢`, TODO for `yes_ask`/`no_ask`. (User picked.)
- **Q2 (DECISION_MODE shape):** `GULLYTRADER_DECISION_MODE` env var, `decision_mode` settings field. (User: "go with ur recommendation".)
- **Q3 (where sells get placed):** orchestrator (option B). (User picked.)
- **Q4 (PR strategy):** one PR, branch `feat/phase-3-agents`. (Claude decision: matches established pattern of one-PR-per-phase; reduces reviewer overhead for solo project.)
- **Q5 (LLM in decide()?):** no — pure math. (Claude decision: user's test list never mentions mocking `chat_json` for decision; researcher already provides the LLM signal.)
- **Q6 (researcher inputs):** `(market, live)` only — don't pass scanner reason through. (Claude decision: keeps coupling minimal; rationale lives in agent_logs.)
- **Q7 (mark price fix in exit pipeline):** in scope — fix orchestrator.py:99 to call `client.get_market()`. (Claude decision: without it, the LLM exit agent has zero P&L signal and Phase 3c acceptance is bunk.)
- **Q8 (peak_pnl_cents / opened_at fixes):** out of scope, TODO comments only. (Claude decision: per user's "Phase 4 out of scope" instruction; non-trivial state tracking.)
- **Q9 (sell limit price):** `max(1, snap.mark_price_cents - 1)` — give up 1¢ to be marketable. TODO for proper sell ladder.
