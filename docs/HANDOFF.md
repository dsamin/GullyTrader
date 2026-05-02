# HANDOFF

The single source of truth for "what's the current state and what should I work on next?". Read this first if you're picking up cold.

Last verified: **2026-05-02**.

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
- **Strict external-service auth gating (Phase 1.5, 2026-05-01):** missing Kalshi creds or CricAPI key default to a loud startup failure when `KALSHI_API_ENV=prod`. `place_limit_order` always raises in prod-unauthed regardless of strict flag. One-line startup banner logs resolved auth state. Override via `GULLYTRADER_STRICT_EXTERNAL_SERVICES`.
- **Researcher agent (Phase 3, 2026-05-01):** wired. LLM (`settings.research_model`, default `deepseek/deepseek-chat-v3-0324`) returns `ResearchNote{estimated_yes_probability, confidence, reasoning}`. Probability clamped to `[0,1]`. Falls back to `confidence=0` (which makes Decision skip) when LLM unavailable.
- **Decision agent (Phase 3, 2026-05-01):** wired. Pure-math Quarter-Kelly sizer; no LLM call. Skips on `edge<5¢`, `confidence=0`, contracts<1, or zero bankroll. Limit price = best-bid + 1¢, clamped `[1, 99]` (TODO: expose `yes_ask`/`no_ask` for marketable orders).
- **PortfolioExit agent (Phase 3, 2026-05-01):** wired. LLM (`settings.exit_model`, default qwen) returns `hold`/`sell`. Defaults to HOLD on any failure mode (LLM unavailable, malformed JSON, invalid action) — never accidentally sells on a bad LLM response.
- **Orchestrator entry pipeline (Phase 3, 2026-05-01):** end-to-end. `run_entry_pipeline_once` runs Scanner → Researcher → Decision per candidate; `place_limit_order` only fires when `GULLYTRADER_DECISION_MODE=live` (default `shadow`). Response shape includes per-candidate `research`, `decision`, and `order` blocks plus top-level `decision_mode`.
- **Orchestrator exit pipeline (Phase 3, 2026-05-01):** real mark prices via `client.get_market(ticker)` per position; LLM path delegates to PortfolioExit; live sells (at `mark - 1¢`) only when `GULLYTRADER_EXIT_MODE=live`.
- **Phase 4 cleanup (2026-05-01):** `/api/bot/status` reads the most recent `agent IN ('decision','exit')` row from `agent_logs` (1h window). `/api/bot/toggle` persists to a singleton `bot_state` table and starts/stops orchestrator threads idempotently. Position filter pills derive from open positions. `cricket_matches` table populated each sync pass. `closed_market_cache` orphan removed. `purge_old_agent_logs` runs once per 24h from the sync loop in addition to the lifespan startup. Tests: 145 passing.
- **Phase 5 cleanup (2026-05-02):** Honest dashboard + trailing-stop fix + DB hygiene.
  - **Frontend honesty.** Removed fake iPhone status bar (no more "9:41" + battery icon). Trends screen panels render only when backed by real data (deleted: hardcoded Manhattan runs/wickets, last-12-balls fallback, win-prob SVG with hardcoded path coords, head-to-head card with always-"3 vs 2 wins", form guide card with always-W/W/L/W/W, pitch + weather card with always-"28°C · Dew @ 19:00"). Dead Notify/Autotrade buttons removed from upcoming fixtures. Scoreboard defaults switched from "MUM 142/4 vs CHE 178/6" to neutral em-dashes/zeros.
  - **Trailing-stop correctness.** New `peak_pnl_cents` column on `positions`. `sync_service._upsert_position` computes current unrealized P&L (`market_exposure - avg_cost × max(yes,no)`) and updates peak via SQL `MAX()` in ON CONFLICT — peak only ever rises, clamped to 0 for underwater positions. **Paired positions skip peak tracking** (avg_cost is blended across legs, so the directional formula understates cost basis; trailing-stop also doesn't apply to hedged positions). `orchestrator.run_exit_monitor_once` SELECTs `opened_at` and `peak_pnl_cents` from DB once per tick instead of using `now-600` and `0`. Race handling: if Kalshi reports a position not yet in our DB, log warning and skip that ticker; sync catches up next pass.
  - **DB hygiene.** Dropped dead `markets` table (never written/read). Dropped dead `exit_decisions` table (never written; exits go to `agent_logs` instead). One-time migration purges 28 orphan zero-contract positions (where `yes_count + no_count = 0 AND realized_pnl_cents = 0` — `realized_pnl_cents` filter protects closed-with-pnl audit history). `sync_service._upsert_position` now skips flat positions at the writer to prevent re-accumulation.
- **Tests:** **157 passing** (Phase 3 added 27, Phase 4 added 16, Phase 5 added 12: 5 migration tests, 5 sync_service tests including a paired-position pin, 2 orchestrator tests for real-DB-state read + race handling; subagent C also hardened 4 existing exit-pipeline tests to seed positions DB rows since the orchestrator now requires the row).

## Next-up — ranked

### 1. Phase 5 carry-overs from Phase 4 cleanup

- **Symmetric sync_service toggle.** Today the dashboard toggle starts/stops the orchestrator entry/exit threads but doesn't touch `sync_service`. Sync continues polling Kalshi while the bot is "off". Add `sync_service.is_running()` + idempotent `start_in_thread`, then have `/api/bot/toggle` start/stop both. Documented as a known limitation in RUNBOOK; not a correctness bug, just operationally wasteful.

### 2. Phase 4 carry-overs from Phase 3 wiring

These are real bugs surfaced by the Phase 3 wiring that we deferred to keep the PR focused. Status as of Phase 5:

- [x] ~~`peak_pnl_cents=0` placeholder in orchestrator exit pipeline.~~ Resolved in Phase 5: new column on `positions`, written by `sync_service._upsert_position` via SQL `MAX()` in ON CONFLICT (peak only rises), read per-tick by orchestrator. Paired positions skip peak tracking (cost-basis math doesn't apply).
- [x] ~~`opened_at=now-600` placeholder.~~ Resolved in Phase 5: `sync_service._upsert_position` already preserved `opened_at` on conflict (existing pattern); orchestrator SELECTs the real value from DB once per tick.
- **`KalshiMarket` exposes only `yes_price`/`no_price` (bid side).** Decision posts at `bid + 1¢` which sits at top of queue but won't fill unless someone crosses. For marketable orders, expose `yes_ask`/`no_ask` from `_market_from_dict` (the API field is `yes_ask` / `no_ask`) and update Decision to use them. Still open.

### 3. Operational follow-ups

These don't block the agents but make the engine production-ready:

- [x] ~~Wire `database.purge_old_agent_logs()` into the lifespan startup hook (defined, not called yet)~~ — done at startup AND now recurring every 24h from the sync loop (Phase 4)
- [x] ~~Persist `closed_market_cache` table actually getting written/read (table exists, nothing populates it)~~ — resolved by removing the orphan; `cricket_matches` is the populated current-state snapshot (Phase 4)
- [ ] Add request-level logging middleware on FastAPI (currently relies on uvicorn defaults)
- [ ] Backfill test coverage toward 170+ (KalshiTrader's bench). Priority adds: orchestrator manual-trigger lock semantics, sync_service keep-alive, exit_monitor hard-stop matrix, kalshi_client RSA signing format
- [ ] Add Playwright visual regression for the 8 screens

### 4. UX polish

- [ ] Confetti animation when a winning settlement lands (CSS already in `styles.css`, just needs trigger)
- [ ] Pull-to-refresh on Home + Match Centre
- [ ] Long-press on position cards for quick close / set alert
- [ ] Reduced-motion media query support (the rules are in styles.css, just verify)

### 5. Deploy

Not urgent for a hobby project, but when ready:

- Pick a host (the parent KalshiTrader is at `kalshi.devanvibes.work` — same approach works)
- Set `KALSHI_API_ENV=prod` in deployed env
- Rotate any keys that have leaked into commits (none should have, but audit before going live)
- Set up a process supervisor (systemd / fly.io / similar)
- Add a `/health` endpoint and external uptime monitoring

## Decision log

Things we've decided and shouldn't relitigate without new evidence.

### 2026-05-01 — `bot_state` is the source of truth for the toggle, not the env var

`GULLYTRADER_ENABLE_ORCHESTRATOR` seeds the table on first boot via `database.ensure_bot_state(default_active=...)`. After that, the dashboard toggle wins — even across restarts. Operators can leave the env var on and turn the bot off from the UI without an env-edit + redeploy. To force a hard re-seed, delete the row: `DELETE FROM bot_state`.

### 2026-05-01 — Decision and Exit rows in agent_logs are explicit-write, not LLM-derived

The Decision agent is pure-math (no LLM call) and the deterministic exit-monitor branches (stop_loss/trailing_stop/time) bypass the LLM. Neither path touches `llm.chat_json`'s auto-logger. The orchestrator now writes explicit `agent='decision'` and `agent='exit'` rows so `/api/bot/status` can surface "what did the bot last do." LLM-driven exit branches still produce a `portfolio_exit` row from `llm.chat_json` AND an `exit` row from the orchestrator — complementary, not duplicate, because the former carries `model`/`latency_ms`/full reasoning while the latter carries structured `{trigger}: {note}`.

### 2026-05-01 — Decision agent is pure math (no LLM)

The Decision agent computes Quarter-Kelly sizing on the Researcher's `ResearchNote` and does not call the LLM itself. Reasoning: the LLM signal already lives in the probability + confidence the Researcher returns; Decision's job is mechanical sizing on that signal. Per-candidate LLM cost halved, decision tests need no `chat_json` mock, behavior is deterministic across runs.

### 2026-05-01 — Single PR for Phase 3 (one-PR-per-phase pattern)

Phase 1 = PR #2, Phase 2 = PR #3, Phase 3 = one PR. The original plan offered three branches but we shipped as one PR because all three agents share the orchestrator wiring change. Three PRs would have meant three reviewer context-switches for the same logical phase.

### 2026-05-01 — Sell limit price = `mark - 1¢` (TODO ladder)

When the LLM exit agent says SELL in live mode, the orchestrator places `place_limit_order(action='sell', limit=max(1, mark - 1))`. Marketable enough to fill in most spreads, costs ≤ 1¢/contract. Proper sell-side ladder (cross multiple ticks if not filled) deferred until after first live IPL match.

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
