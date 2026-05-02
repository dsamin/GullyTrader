# Architecture

Deep reference for how GullyTrader's pieces fit together. For "what's done / what's next" see [HANDOFF.md](HANDOFF.md). For day-to-day operations see [RUNBOOK.md](RUNBOOK.md).

## High-level diagram

```
                            ┌────────────────────────┐
                            │   FastAPI (main.py)    │
                            │                        │
   browser ───── HTTP ─────▶│  /         (React UI)  │
                            │  /static/* (assets)    │
                            │  /api/portfolio        │  ←── portfolio.compute_metrics()
                            │  /api/positions        │
                            │  /api/trades           │  ←── portfolio.recent_fills()
                            │  /api/match/live       │◀──── reconciler ───▶ Kalshi event
                            │  /api/match/{id}/...   │                       (KXIPLGAME-...)
                            │  /api/events/ipl       │
                            │  /api/fixtures         │◀──── reconciler
                            │  /api/standings        │
                            │  /api/bot/status       │
                            │  /api/orchestrator/*   │
                            └──────────┬─────────────┘
                                       │
                  ┌────────────────────┼────────────────────────┐
                  │                    │                        │
        ┌─────────▼────────┐  ┌────────▼────────┐  ┌────────────▼─────────────┐
        │  KalshiClient    │  │  CricApiFeed    │  │   Orchestrator           │
        │  (signed v2)     │  │  (cricketdata)  │  │   (2 daemon threads)     │
        │                  │  │                 │  │                          │
        │  • balance       │  │  • live_match   │  │  Entry pipeline ─────────┤
        │  • IPL events    │  │  • fixtures     │  │    Scanner ─→ Researcher │
        │  • markets/event │  │  • standings    │  │           ─→ Decision    │
        │  • positions     │  │                 │  │           ─→ buy order   │
        │  • orders        │  │  60s match-list │  │                          │
        │  • fills         │  │  in-proc cache  │  │                          │
        │  • settlements   │  │                 │  │                          │
        │                  │  │  in-proc cache  │  │  Exit monitor ───────────┤
        │  RateLimiter:    │  │                 │  │    hard stops bypass LLM │
        │  18 reads/sec    │  │  IPL series_id  │  │    LLM for nuanced exits │
        │  8 writes/sec    │  │  cached forever │  │    shadow|live mode      │
        └──────────────────┘  └─────────────────┘  └──────────────────────────┘
                  │                    │                        │
                  └────────────────────┼────────────────────────┘
                                       │
                            ┌──────────▼─────────┐
                            │  SQLite (WAL)      │
                            │                    │
                            │  positions ◀───────┼─── sync_service writes peak_pnl_cents
                            │                    │     (Phase 5; trailing-stop reads it)
                            │  orders / fills    │
                            │  settlements       │
                            │  agent_logs ◀──────┼─── llm.py writes here on every LLM call
                            │                    │     + orchestrator writes decision/exit rows
                            │  cricket_matches   │
                            │  bot_state         │
                            └────────────────────┘
                            (Phase 5: dropped dead `markets` and
                             `exit_decisions` tables — never written.)

        ┌───────────────────────────────────────────────────┐
        │  Sync service (3rd daemon thread, when enabled)   │
        │   pulls positions / orders / fills / settlements  │
        │   from Kalshi every SYNC_INTERVAL_SECONDS (60s),  │
        │   upserts into SQLite (idempotent — trade_id /    │
        │   order_id / ticker uniques). Settlements update  │
        │   the matching positions row → status='closed'.   │
        │   Per-endpoint try/except keeps loop alive on     │
        │   transient SQLite or Kalshi failures.            │
        └───────────────────────────────────────────────────┘
```

## Module responsibilities

| File | Responsibility |
|---|---|
| [`main.py`](../gully-engine/main.py) | FastAPI app. Mounts `/static`, exposes `/api/*`, manages lifespan (DB init, log purge, optional thread spin-up). Lifespan startup logs a one-line auth-state banner (kalshi authed/unauthed, cricket stub/cricapi, strict on/off, env demo/prod). |
| [`settings.py`](../gully-engine/settings.py) | Single Settings dataclass loaded from `.env`. Mirrors KalshiTrader's env naming so a single `.env` powers both projects. Owns the strict_external_services flag — defaults to True when KALSHI_API_ENV=prod, overridable via GULLYTRADER_STRICT_EXTERNAL_SERVICES. |
| [`database.py`](../gully-engine/database.py) | SQLite schema + WAL connection helpers. `write_conn` is a context manager that try/finally-closes (PR #50 pattern from KalshiTrader). |
| [`kalshi_client.py`](../gully-engine/kalshi_client.py) | Kalshi v2 client. RSA-PSS-SHA256 signing (`KALSHI-ACCESS-*` headers, signed path includes `/trade-api/v2`), built-in rate limiter, defensive parsing (defaults `value=0` to 100, `yes_price=None` to 0). Read methods: `list_ipl_events`, `list_event_markets`, `get_market`, `list_positions`, `list_orders`, `list_fills`, `list_settlements`, `get_balance`. Write methods: `place_limit_order`, `cancel_order`. `list_settlements` applies the paired-position correction inline so callers always get the corrected `net_pnl_cents`. Returns mock data when unauthed. In strict mode, __init__ raises on missing creds rather than silently mocking; place_limit_order always raises when KALSHI_API_ENV=prod and unauthed (real-money path is never silently stubbed). |
| [`portfolio.py`](../gully-engine/portfolio.py) | DB-derived metrics. `compute_metrics()` aggregates `settlements` and `positions` into the day-P&L / ROI / win-rate / streak / 20-day sparkline blob `/api/portfolio` returns. `recent_fills()` and `recent_settled_positions()` back `/api/trades` and the Positions screen. All metrics return zero / empty when the DB is empty (fresh install) — never raise. |
| [`cricket_data.py`](../gully-engine/cricket_data.py) | `CricketFeed` protocol with `StubCricketFeed` (design figures) and `CricApiFeed` (cricketdata.org). The cricapi feed locates the IPL series_id once per process, then pulls all 70 matches from `/series_info` with a 60s in-process cache. In strict mode, get_feed() raises if provider=cricapi and no key is set; logs WARNING when provider=stub (you're on mock data). |
| [`reconciler.py`](../gully-engine/reconciler.py) | Parses Kalshi event tickers like `KXIPLGAME-26MAY07RCBLSG` → `(2026-05-07, RCB, LSG)`. Greedy-splits the franchise concatenation against a known set (PBKS resolves before PB+KS). Maps Kalshi codes ↔ design codes (MI→MUM, CSK→CHE, etc.). Used by `/api/match/live` and `/api/fixtures` to attach a `kalshi_event_ticker` to each cricket-feed match. |
| [`pnl.py`](../gully-engine/pnl.py) | The paired-position P&L correction (load-bearing — see [README#inherited-kalshi-learnings](../README.md#inherited-kalshi-learnings)). |
| [`exit_monitor.py`](../gully-engine/exit_monitor.py) | Hard-stop matrix (stop loss / trailing / time). Returns an `ExitDecision`; LLM is only called when none of the deterministic stops fire. Trailing-stop and time-stop both depend on real per-position state (`peak_pnl_cents` and `opened_at`) — Phase 5 wired these from DB instead of hardcoded placeholders. |
| [`orchestrator.py`](../gully-engine/orchestrator.py) | Two daemon threads (entry + exit). Manual triggers use non-blocking locks so calls don't queue on a long-running pass. Exit pipeline reads `opened_at` and `peak_pnl_cents` from `positions` once per tick to build `PositionSnapshot` (Phase 5). |
| [`sync_service.py`](../gully-engine/sync_service.py) | Background reconciliation loop. `_reconcile_once()` pulls positions / orders / fills / settlements from Kalshi and upserts them into the matching SQLite tables (`UNIQUE(ticker)` for positions/settlements, `UNIQUE(kalshi_order_id)` for orders, `UNIQUE(kalshi_trade_id)` partial index for fills). Skips writing flat positions (yes_count + no_count == 0) so they don't accumulate as ghost rows. Computes per-tick unrealized P&L and updates `peak_pnl_cents` via SQL `MAX()` so peak only ever rises (Phase 5). Each endpoint is independently try/except'd so one Kalshi 503 can't kill the loop. Loop keep-alive logic from KalshiTrader PR #54. |
| [`llm.py`](../gully-engine/llm.py) | OpenRouter chat-completions client with JSON mode. Persists every call to `agent_logs` (audit trail). Failures return `None` rather than raising so the caller decides on fallback. |
| [`agents/scanner.py`](../gully-engine/agents/scanner.py) | Implemented. Prompts qwen-2.5-72b to rank open IPL markets by edge. Drops scores < 30, drops hallucinated tickers, falls back to first-N when LLM is unreachable. |
| [`agents/researcher.py`](../gully-engine/agents/researcher.py) | Implemented (Phase 3). Calls `settings.research_model` via OpenRouter to estimate true YES probability for one market. Returns `ResearchNote{estimated_yes_probability, confidence, reasoning}`. Probability clamped to `[0,1]`. Fallback on LLM failure → `confidence=0` (load-bearing: makes Decision skip). |
| [`agents/decision.py`](../gully-engine/agents/decision.py) | Implemented (Phase 3). Pure-math Quarter-Kelly sizing on `ResearchNote` (no LLM call — the LLM signal lives in the note). Returns `TradeDecision{action, contracts, limit_price_cents, reasoning}`. `pass` if edge<5¢, confidence=0, or contracts<1. Limit price = best-bid + 1¢, clamped `[1, 99]`. Sizing uses limit price (not bid) so the 5%-of-bankroll cap holds at execution. |
| [`agents/portfolio_exit.py`](../gully-engine/agents/portfolio_exit.py) | Implemented (Phase 3). LLM hold/sell on a single open position. Defaults to HOLD on any failure (LLM unavailable, malformed JSON, invalid action) — never accidentally sells on a bad LLM response. |

## Notable tables

The full schema lives in [`database.py`](../gully-engine/database.py). Two non-obvious tables worth calling out:

- **`bot_state`** — singleton row (CHECK `id = 1`). Holds `active` (int 0/1) and `updated_at`. Seeded by `database.ensure_bot_state(default_active=...)` from `GULLYTRADER_ENABLE_ORCHESTRATOR` on first lifespan boot. Mutated by `/api/bot/toggle`. Source of truth for whether the orchestrator threads are started at boot.

- **`cricket_matches`** — current live-match snapshot, written by `sync_service._upsert_cricket_match` each pass. Single row per `match_id`, upsert-on-conflict. Status `'live'` when populated. The dashboard's `/api/match/live` endpoint still reads through `CricApiFeed`'s 60s in-memory cache — `cricket_matches` is for restart resilience and historical lookback.

### `agent_logs` row taxonomy

Every row carries `agent`, `ticker`, `decision`, `reasoning`, `created_at`. LLM-driven agents also populate `model`, `latency_ms`, `confidence`.

| agent | written by | trigger |
|-------|------------|---------|
| `scanner` | `llm.chat_json` (auto) | each LLM scan call |
| `researcher` | `llm.chat_json` (auto) | each LLM research call |
| `portfolio_exit` | `llm.chat_json` (auto) | LLM-driven exit branch only |
| `decision` | `orchestrator.run_entry_pipeline_once` (explicit) | each `decide()` result |
| `exit` | `orchestrator.run_exit_monitor_once` (explicit) | each `evaluate()` result |

The `agent='exit'` `reasoning` column carries the trigger prefix (`stop_loss:`, `trailing_stop:`, `time:`, `llm:`, `manual:`) so a single sqlite `LIKE 'stop_loss:%'` query buckets exits by cause.

An LLM-driven exit produces TWO rows per evaluation — one `portfolio_exit` (from `llm.chat_json`, with model/latency/full reasoning) and one `exit` (from the orchestrator, with structured `{trigger}: {note}`). Complementary, not duplicate.

## Key data flows

### 1. Dashboard load (read-only)

```
browser GET /
   ├─ FastAPI returns static/index.html (React + Babel via CDN)
   └─ React mounts, calls /api/portfolio, /api/positions, /api/match/live,
      /api/fixtures, /api/standings, /api/bot/status in parallel.
        ├─ /api/portfolio    → KalshiClient.get_balance() + portfolio.compute_metrics()
        │                      (metrics derived from settlements + positions tables)
        ├─ /api/positions    → KalshiClient.list_positions()
        │                      + KalshiClient.get_market(ticker) per row for real mark
        │                      + portfolio.recent_settled_positions() for the settled tab
        ├─ /api/trades       → portfolio.recent_fills()  (latest 50 executions from DB)
        ├─ /api/match/live   → CricApiFeed.live_match()
        │                      + reconciler.kalshi_event_for_live_match()
        │                        (matches the live game to a Kalshi KXIPLGAME event)
        ├─ /api/fixtures     → CricApiFeed.upcoming_fixtures()
        │                      + reconciler.kalshi_event_for_fixture() per row
        ├─ /api/standings    → CricApiFeed.standings()
        └─ /api/bot/status   → bot_state.active + most recent agent_logs row
                                  WHERE agent IN ('decision','exit') AND created_at > now-3600
```

### 1b. Background reconciliation (when orchestrator enabled)

```
sync_service thread (every SYNC_INTERVAL_SECONDS, default 60):
   _reconcile_once()
     ├─ KalshiClient.list_positions()    →  upsert into positions     (UNIQUE ticker)
     ├─ KalshiClient.list_orders()       →  upsert into orders        (UNIQUE kalshi_order_id)
     ├─ KalshiClient.list_fills()        →  insert into fills          (dedup kalshi_trade_id)
     └─ KalshiClient.list_settlements()  →  upsert into settlements   (UNIQUE ticker)
                                          + UPDATE positions SET status='closed',
                                                                realized_pnl_cents=...
                                                                WHERE ticker=...
```

### 2. Manual entry-pipeline trigger (current state)

```
POST /api/orchestrator/run-entry
   └─ orchestrator.run_entry_pipeline_once(force=True)
       ├─ acquire non-blocking _entry_lock (skip if already running)
       ├─ feed.live_match()                         (cached, ~free)
       ├─ KalshiClient.list_ipl_markets()           (paginates /events; ~5-10s)
       ├─ KalshiClient.get_balance()                 → bankroll_cents
       ├─ scanner_shortlist(markets, max_results=5) (calls OpenRouter; ~15s)
       └─ for each candidate:
           ├─ researcher.research(market, live)      → ResearchNote (LLM)
           │   └─ chat_json(agent="researcher", model=settings.research_model, ...)
           │       └─ writes agent_logs row (audit trail)
           ├─ decision.decide(note, bankroll, market) → TradeDecision (pure math)
           └─ if action != 'pass' and decision_mode == 'live':
                 KalshiClient.place_limit_order(side, action='buy', count, limit)
       └─ return {status, markets_scanned, decision_mode, live, candidates: [
              {ticker, score, scan_reason, research, decision, order}
          ]}
```

### 3. Manual exit-monitor trigger

```
POST /api/orchestrator/run-exit
   └─ orchestrator.run_exit_monitor_once(force=True)
       ├─ KalshiClient.list_positions()
       └─ for each position:
           ├─ KalshiClient.get_market(ticker)         → real mark price
           ├─ build PositionSnapshot (mark = yes_price/no_price for side)
           └─ exit_monitor.evaluate(snap)
               ├─ check stop_loss (% drawdown vs entry)
               ├─ check trailing_stop (% giveback vs peak P&L)
               ├─ check time_stop (open > N minutes)
               └─ if no hard stop: agents.portfolio_exit.decide(snap, live)
                   └─ chat_json(agent="portfolio_exit", model=settings.exit_model, ...)
           └─ if action == 'sell' and exit_mode == 'live':
                 KalshiClient.place_limit_order(side, action='sell', count, limit=mark-1)
       └─ return {status, evaluated, exit_mode, actions: [
              {ticker, action, trigger, mode, note, order}
          ]}
```

The orchestrator's daemon threads run these loops on a `live_poll_interval_seconds` cadence when `GULLYTRADER_ENABLE_ORCHESTRATOR=1`.

## Design decisions worth knowing

### Why no frontend build step

The design [delivered from claude.ai/design](https://github.com/dsamin/GullyTrader/blob/main/gully-engine/static/index.html) used React 18 + Babel standalone via CDN with no bundler. We kept that approach because:

- It cuts ~30 dependencies and a webpack/vite config out of the picture
- The whole frontend is ~12 files, all readable as plain JSX in any editor
- The dashboard's bottleneck is API latency (Kalshi auth, OpenRouter), not bundle size
- A new contributor can hit save and refresh — no `npm run dev` ritual

If/when you outgrow this (e.g. need npm packages, code splitting, TS), bundle as a separate phase.

### Why CricAPI over Cricbuzz

Researched in detail (see [HANDOFF.md#cricket-data-decision](HANDOFF.md)):
- Cricbuzz Plus is consumer ad-free viewing — not API access
- Cricbuzz Official API on AllThingsDev is enterprise-only, opaque pricing
- Unofficial Cricbuzz scrapers on RapidAPI are legally fragile, technically unstable
- CricAPI has transparent pricing ($0/100/day → $12.99/10K/day), permissive ToS allowing trading use, and a clean JSON API

Cricsheet (free, MIT-licensed historical) is recommended as a complement for backtesting.

### Why one `.env` shared with KalshiTrader

The user already has Kalshi credentials and an OpenRouter key set up for KalshiTrader. Adopting the same env var names (`KALSHI_KEY_ID`, `OPENROUTER_API_KEY`, per-agent `*_LLM_*` overrides) means `cp ../KalshiTrader/kalshi-engine/.env .env` is the entire setup. New contributors don't have to re-provision auth.

### Why the IPL series_id approach for CricAPI

`/currentMatches` returns 25 most-relevant entries across all cricket. `/matches` paginates through 14,548 records globally. Neither makes IPL findable on the free 100/day tier.

`/series` lists tournaments — find IPL once (typically in the first 50–75), cache the series_id forever. Then `/series_info?id={sid}` returns all 70 matches of the season in one call. Combined with a 60s in-process cache, the dashboard can poll all day on the free tier.

### Why we re-derive points in standings

CricAPI's `/series_points` returns rows with `wins / loss / ties / nr` but no `points` column. T20 league rule is `2*wins + ties + nr` (1 point each for tie/no-result). Net run rate isn't on the free tier — we leave it as `0.000` and revisit if/when we upgrade.

### Why the team-code mapping is dual

Three different code spaces are in play:
- **Kalshi codes** (real franchise abbreviations): MI, CSK, RCB, KKR, DC, PBKS, SRH, RR, LSG, GT
- **Design codes** (the abstract codes in the original mockup): MUM, CHE, BLR, KOL, DEL, PUN, HYD, RAJ, LSG, GUJ
- **Full franchise names** (what CricAPI returns): "Mumbai Indians", "Chennai Super Kings", etc.

`reconciler.py` carries both `KALSHI_TO_DESIGN_CODE` and `KALSHI_TO_FRANCHISE` so we can correlate Kalshi event tickers (Kalshi codes embedded) ↔ CricAPI fixtures (full names → design codes via `cricket_data._team_code()`).

## Testing approach

- **External services are always mocked.** OpenRouter, Kalshi, CricAPI never get hit during `pytest`. The mock pattern in [`test_cricket_data.py`](../gully-engine/tests/test_cricket_data.py) (a fake `requests.Session` returning canned JSON per endpoint) is the canonical example.
- **Live verification is its own thing.** "Boot uvicorn, hit `POST /api/orchestrator/run-entry`, see agent_logs row land" is operational verification — not a unit test. Both matter.
- **Test the gotchas first.** [`test_pnl.py`](../gully-engine/tests/test_pnl.py) is the model: every test case maps to a real bug we've paid for. Future agent implementations should add similar regression coverage as their first commit.

## When this doc is wrong

Either the design changed and this wasn't updated, or you found a real bug. Either way, fix it in the same PR as your code change — the rule from [CLAUDE.md](../CLAUDE.md): "every code change updates the relevant doc" applies here too.
