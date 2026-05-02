# HANDOFF

The single source of truth for "what's the current state and what should I work on next?". Read this first if you're picking up cold.

Last verified: **2026-05-01**.

## Current state

Verified working end-to-end against live services:

- **Kalshi auth (prod):** RSA-PSS-SHA256 signing works; balance + portfolio_value real; 18 IPL events surface from `/api/events/ipl`.
- **Kalshi reconciliation (Phase 1, 2026-05-01):** `KalshiClient.list_orders`, `list_fills`, `list_settlements` are real. Smoke run upserted **138 orders, 180 fills, 47 settlements, 28 positions** in a single pass — idempotent across re-runs. Settlements apply the paired-position P&L correction inline; matching open positions flip to `status='closed'` automatically.
- **`/api/portfolio` derives from DB**, not hardcoded. day_pnl / ROI / win_rate / streak / spark_20d come from `portfolio.compute_metrics()` reading the `settlements` + `positions` tables. Empty DB → all-zero response, no crashes.
- **`/api/positions` uses real mark prices** via `KalshiClient.get_market(ticker)`. Synthetic `+10 if MUM else -8` fudge is gone. Settled tab pulls from the `settlements` table, not `_mock_settled()`.
- **`/api/trades`:** new endpoint returning the most recent fills from the local `fills` table.
- **Frontend "Arjun" → "Devan"** (avatar default initials too).
- **CricAPI (live):** real IPL fixtures, standings, and (when matches are in-progress) live ball-by-ball state. 60s in-process cache keeps free-tier hit count < 100/day.
- **Reconciler:** 8 of 10 CricAPI fixtures correctly correlate to a Kalshi `KXIPLGAME` event. The 2 misses are real-world correctness, not bugs (Kalshi removes events from the open filter once they're imminent or past).
- **Scanner agent:** prompts qwen-2.5-72b via OpenRouter, returns ranked candidates with grounded reasoning ("SRH have a strong recent form, undervalued at 50¢"). ~16s round-trip. Persists to `agent_logs`.
- **Frontend:** all 8 screens render against live data. Hash-router navigation. Light + dark mode.
- **Tests:** **94 passing** (P&L correction, cricket feed, scanner, reconciler, kalshi client orders/fills/settlements, sync service reconciliation, portfolio metrics, API integration).

## Next-up — ranked

### 1. Researcher agent (next code task)

**Why:** the scanner returns ticker + score + 1-line reason. The researcher takes those candidates and produces an estimated YES probability + confidence + paragraph-level reasoning grounded in live ball-by-ball context. This is what the decision agent will consume.

**Estimated effort:** ~1.5 hours.

**Implementation pattern:** copy [`agents/scanner.py`](../gully-engine/agents/scanner.py).

**Concrete steps:**
1. Replace [`agents/researcher.py`](../gully-engine/agents/researcher.py) — currently returns implied probability unchanged.
2. New `ResearchNote` dataclass already exists. Add `confidence` and a richer `reasoning` field if not already there.
3. System prompt: "You are a quantitative cricket analyst. Given live match state and a YES/NO market, estimate true probability of YES. Return JSON `{estimated_probability: 0-1, confidence: 0-1, reasoning: <paragraph>}`."
4. User prompt: market title + current price + live state from `cricket_data.get_feed().live_match()` + relevant context (overs, RRR, batters, last balls).
5. Call `llm.chat_json(agent="researcher", model=settings.research_model, ...)`.
6. Add `tests/test_researcher.py` mirroring `test_scanner.py`'s mock pattern.
7. Wire into orchestrator: after `scanner_shortlist`, loop candidates through `researcher.research()`.

**Acceptance:** `POST /api/orchestrator/run-entry` returns scanner candidates + researcher notes. `agent_logs` shows both `scanner` and `researcher` rows per pass.

### 2. Decision agent

**Why:** the researcher gives us an estimated probability. Decision converts that into a sized order: action (buy YES / buy NO / pass), contracts, limit price.

**Estimated effort:** ~1.5 hours.

**Concrete steps:**
1. Replace [`agents/decision.py`](../gully-engine/agents/decision.py) — currently always returns "pass".
2. Inputs: `ResearchNote` + bankroll (from Kalshi balance) + market price.
3. Compute edge: `estimated_probability - implied_probability`.
4. Skip if edge < 5¢ (threshold defined as `MIN_EDGE` in the existing stub).
5. Size with quarter-Kelly: `fraction = (edge / (1 - implied_probability)) * 0.25`, clamped by `MAX_POSITION_PCT = 0.05`.
6. Convert to contract count + limit price (`limit_price = best_bid + 1¢` or similar).
7. Tests with mocked researcher inputs covering: pass-on-low-edge, buy-YES path, buy-NO path, max-position clamp, zero-bankroll edge case.

**Acceptance:** orchestrator's entry pipeline, end-to-end, returns decisions. With orchestrator threads enabled (`GULLYTRADER_ENABLE_ORCHESTRATOR=1`) and a real authed account, "buy" decisions actually place limit orders via `KalshiClient.place_limit_order()`.

**Risk control:** keep `EXIT_MODE=shadow` in `.env` while testing. The decision agent doesn't have a shadow mode itself — once a buy order is placed, it's real money. Hold this agent in code review longer than the others.

### 3. Portfolio-exit agent (LLM-driven exits)

**Why:** the deterministic hard stops in `exit_monitor.py` already work (stop loss, trailing, time). The portfolio_exit agent handles the nuanced cases: take profit early on momentum reversals, ride a winner through a tightening spread, etc.

**Estimated effort:** ~1.5 hours.

**Concrete steps:** same shape as scanner / researcher. Inputs: `PositionSnapshot` + live match state + recent price action. Output: `ExitDecision{action: hold|sell, mode: shadow|live, reasoning: ...}`. Already partially shaped at [`agents/portfolio_exit.py`](../gully-engine/agents/portfolio_exit.py).

**Acceptance:** `POST /api/orchestrator/run-exit` returns LLM-driven exit decisions for any position that no hard stop applied to.

**Critical:** must run in shadow mode for at least one full IPL match before flipping to live. The first session is read-only validation.

### 4. Operational follow-ups

These don't block the agents but make the engine production-ready:

- [ ] Wire `database.purge_old_agent_logs()` into the lifespan startup hook (defined, not called yet)
- [ ] Persist `closed_market_cache` table actually getting written/read (table exists, nothing populates it)
- [ ] Add request-level logging middleware on FastAPI (currently relies on uvicorn defaults)
- [ ] Backfill test coverage toward 170+ (KalshiTrader's bench). Priority adds: orchestrator manual-trigger lock semantics, sync_service keep-alive, exit_monitor hard-stop matrix, kalshi_client RSA signing format
- [ ] Add Playwright visual regression for the 8 screens

### 5. UX polish

- [ ] Confetti animation when a winning settlement lands (CSS already in `styles.css`, just needs trigger)
- [ ] Pull-to-refresh on Home + Match Centre
- [ ] Long-press on position cards for quick close / set alert
- [ ] Reduced-motion media query support (the rules are in styles.css, just verify)

### 6. Deploy

Not urgent for a hobby project, but when ready:

- Pick a host (the parent KalshiTrader is at `kalshi.devanvibes.work` — same approach works)
- Set `KALSHI_API_ENV=prod` in deployed env
- Rotate any keys that have leaked into commits (none should have, but audit before going live)
- Set up a process supervisor (systemd / fly.io / similar)
- Add a `/health` endpoint and external uptime monitoring

## Decision log

Things we've decided and shouldn't relitigate without new evidence.

### 2026-04-30 — Cricket data decision

Researched five providers. Picked **CricAPI** for these reasons:
- $0 free tier (100 hits/day) is enough for development
- $12.99/mo unlocks 10K hits/day — fine for production polling
- Permissive ToS explicitly allows trading/commercial use
- Returns clean JSON, well-documented endpoints
- Cricbuzz "official" API requires enterprise sales contact (no transparent pricing); user's Cricbuzz Plus is consumer viewing only
- Roanuz costs ~$210+/mo and ToS forbids monetized use
- Unofficial Cricbuzz scrapers on RapidAPI are legally fragile

Cricsheet (free, historical) is the recommended complement when we need to backtest.

### 2026-04-30 — Frontend stays no-build

The claude.ai/design bundle delivered React 18 + Babel-via-CDN with no bundler. We kept that approach. ~12 frontend files, no `npm install`, no dev server beyond uvicorn. Decision is reversible if we hit real bottlenecks.

### 2026-04-30 — Share `.env` with KalshiTrader

Adopted KalshiTrader's env var naming (`KALSHI_KEY_ID`, `OPENROUTER_API_KEY`, per-agent `*_LLM_*` overrides) so `cp ../KalshiTrader/kalshi-engine/.env .env` is the full setup.

### 2026-05-01 — IPL coverage strategy via series_id

`/currentMatches` and `/matches` aren't viable for finding IPL on the free tier (14K-row pagination). Switched to `/series` (find IPL once, cache series_id) → `/series_info?id={sid}` (one call returns full 70-match season). 60s in-process cache on the matchList keeps the polling cost ~free.

### 2026-05-01 — Standings derive points

CricAPI's `/series_points` returns `wins/loss/ties/nr` but no `points` column. T20 league scoring is `2*wins + ties + nr` — derive locally. NRR isn't on the free tier; leave as `0.000` until we upgrade.

## Where to find verified working snippets

| Task | Reference |
|---|---|
| Implement a new LLM agent | [`agents/scanner.py`](../gully-engine/agents/scanner.py) is the gold-standard pattern (system + user prompt, JSON parsing, fallback, hallucination filter) |
| Add a new HTTP-mocked test | [`tests/test_cricket_data.py`](../gully-engine/tests/test_cricket_data.py) — `_mock_session()` helper |
| Add a new LLM-mocked test | [`tests/test_scanner.py`](../gully-engine/tests/test_scanner.py) — `_llm_resp()` helper |
| Add an API endpoint | [`main.py`](../gully-engine/main.py) — endpoints are thin wrappers over the modules; keep them dumb |
| Add a new column / table | [`database.py`](../gully-engine/database.py) — append to `SCHEMA`. SQLite migration discipline isn't strict yet because we're pre-alpha |

## Stuck?

The patterns from KalshiTrader are documented inline in the relevant modules with comments like "Inherited from KalshiTrader (PR #50): ...". When in doubt, look at the parent project at [github.com/dsamin/KalshiTrader](https://github.com/dsamin/KalshiTrader) — it's been running in prod for months and has answered most of the questions you'll encounter.
