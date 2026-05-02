# GullyTrader

Autonomous IPL prediction-market trader for Kalshi. Multi-agent LLM pipeline picks markets, sizes positions, and manages exits; a mobile-first cricket dashboard lets you watch the bot work and override when needed.

> **Sister project to [KalshiTrader](https://github.com/dsamin/KalshiTrader).** Same engine architecture (Python/FastAPI + SQLite/WAL + multi-agent LLM pipeline) — narrowed to IPL cricket markets and paired with a dedicated mobile UI.

## Status

**Pre-alpha, foundation complete.** Scanner agent proven against live OpenRouter and live Kalshi, reconciler bridges Kalshi events ↔ CricAPI fixtures, full mobile UI renders against real data.

| Component | State |
|---|---|
| Frontend (8 screens, mobile-first React) | ✅ rendering against live data |
| Kalshi RSA-PSS auth (prod) | ✅ verified — balance + 18 IPL events surface |
| Kalshi orders / fills / settlements ingest | ✅ real client methods + sync-service reconciliation |
| Portfolio metrics (day P&L, ROI, win rate, sparkline) | ✅ DB-derived from real settlements |
| Real mark prices on open positions | ✅ via `KalshiClient.get_market(ticker)` |
| `/api/trades` (executed-fills history) | ✅ wired |
| CricAPI integration (live + fixtures + standings) | ✅ wired with 60s in-process cache |
| Kalshi ↔ CricAPI reconciler (event-ticker parsing) | ✅ 8/10 fixtures correlate to Kalshi events |
| Scanner agent (LLM-ranked market candidates) | ✅ ~16s round-trip, real grounded reasoning |
| Researcher agent (LLM probability estimator) | ✅ wired (Phase 3) — settings.research_model |
| Decision agent (Quarter-Kelly sizer, pure math) | ✅ wired (Phase 3) — gated by `GULLYTRADER_DECISION_MODE` |
| PortfolioExit agent (LLM hold/sell on open positions) | ✅ wired (Phase 3) — gated by `GULLYTRADER_EXIT_MODE` |
| Strict-mode auth gating (prod-default; raises on missing creds) | ✅ live |
| Bot toggle + status (real, persisted) | ✅ live (Phase 4) |
| Trailing-stop reads real `peak_pnl_cents` from DB (Phase 5) | ✅ live |
| Honest dashboard (no fake mobile chrome, no fake trends panels) | ✅ live (Phase 5) |
| Tests | ✅ 157 passing |

**Phase 4 cleanup (2026-05-01):** Real bot status pill (reads recent decisions from `agent_logs`), real bot toggle (persists to `bot_state`, starts/stops orchestrator threads idempotently), `cricket_matches` table populated each sync pass, `closed_market_cache` orphan removed, position filter pills derive from open positions, `purge_old_agent_logs` runs daily from sync loop in addition to the lifespan startup.

**Phase 5 cleanup (2026-05-02):** Honest dashboard + trailing-stop fix + DB hygiene. (1) Frontend: removed fake iPhone status bar, hidden Trends panels with no real data source (Manhattan, last-balls, head-to-head, form guide, pitch & weather, win-prob SVG), removed dead Notify/Autotrade buttons, neutral Scoreboard defaults. (2) Trailing-stop correctness: orchestrator reads real `opened_at` and `peak_pnl_cents` from positions DB instead of hardcoded `now-600` and `0`. New `peak_pnl_cents` column tracked monotonically per sync; paired positions skip peak tracking (cost basis math doesn't apply to hedged positions). (3) DB hygiene: dropped dead `markets` and `exit_decisions` tables; one-time purge of 28 orphan zero-contract positions; sync_service skips writing flat positions.

## Stack

- **Backend:** Python 3.11+ / FastAPI / SQLite (WAL)
- **Frontend:** React 18 + Babel standalone (CDN, no build step) — matches the design prototype runtime
- **LLMs:** Configurable via OpenRouter (`qwen/qwen-2.5-72b-instruct` default)
- **Markets:** Kalshi binary YES/NO contracts (1–99¢, $1 payout)
- **Cricket data:** CricAPI ([cricketdata.org](https://cricketdata.org)) — `stub` provider also available

## Architecture

```
┌────────────────────────────────────────────────────────────────┐
│                      gully-engine                              │
│                                                                │
│  Orchestrator (2 threads, optional)                            │
│   ├─ Entry pipeline ── Scanner → Researcher (LLM) → Decision → │
│   │                    place_limit_order (gated DECISION_MODE) │
│   └─ Exit monitor   ── always-on; hard stops bypass LLM,       │
│                       PortfolioExit LLM for nuanced cases;     │
│                       shadow logs decisions, live places sells │
│                                                                │
│  Sync service ── pulls orders / fills / settlements / positions│
│                  from Kalshi, upserts into SQLite (60s default)│
│                                                                │
│  Cricket feed (CricAPI) ── live match + fixtures + standings   │
│  Reconciler ── parses KXIPLGAME tickers, pairs Kalshi↔CricAPI  │
│                                                                │
│  FastAPI ── /static (React UI), /api/* (REST)                  │
└────────────────────────────────────────────────────────────────┘
```

For the deeper picture (data flow, sequence diagrams, design decisions): [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Quickstart

```bash
cd gully-engine
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Option 1 — share the KalshiTrader account (recommended for hobby use):
cp ../../KalshiTrader/kalshi-engine/.env .env

# Option 2 — fresh credentials:
cp .env.example .env   # then fill in KALSHI_*, OPENROUTER_API_KEY, CRICKET_FEED_API_KEY

# run dev server (auto-reload on edits)
uvicorn main:app --reload --port 8001

# run with orchestrator + sync threads enabled
GULLYTRADER_ENABLE_ORCHESTRATOR=1 uvicorn main:app --port 8001
```

Open http://localhost:8001 — the dashboard pulls real balance + IPL events from Kalshi and live IPL fixtures from CricAPI.

### Production safety: strict mode

By default, missing Kalshi creds or a missing CricAPI key fall back to mock data — handy in dev (you can hit the dashboard without filling out `.env` first), dangerous in prod (a real-money order routed to a stub returns `{"order_id": "stub-order"}` and silently no-ops).

**Strict mode** is auto-enabled when `KALSHI_API_ENV=prod` and turns these silent fallbacks into loud startup failures:

| Condition | Strict (prod default) | Non-strict (dev default) |
|---|---|---|
| Kalshi creds missing at boot | refuses to start | logs warning, mocks data |
| `CRICKET_FEED_PROVIDER=cricapi` but no key | refuses to start | logs warning, falls back to stub |
| `CRICKET_FEED_PROVIDER=stub` | logs WARNING (you're on mock cricket data!) | quiet (expected dev posture) |
| `place_limit_order` in `KALSHI_API_ENV=prod` with no creds | **always raises**, regardless of strict flag | n/a |

Override via env: `GULLYTRADER_STRICT_EXTERNAL_SERVICES=1` to force strict, `=0` to force non-strict. Useful for staging environments that point at prod Kalshi but want explicit control.

The startup banner logs the resolved state on one grep-friendly line:

```
startup: GullyTrader auth state — kalshi=authed cricket=cricapi strict=on env=prod
```

### Production safety: shadow vs live order placement

Two independent flags control whether Kalshi `place_limit_order` calls are real:

| Env var | Default | Effect |
|---|---|---|
| `GULLYTRADER_DECISION_MODE=shadow` | shadow | Decision agent's `buy_yes` / `buy_no` decisions are logged to `agent_logs` but never placed. |
| `GULLYTRADER_DECISION_MODE=live` | — | Buys are placed via `KalshiClient.place_limit_order`. Bankroll comes from `get_balance().balance`; sizing is Quarter-Kelly clamped at 5% per position. |
| `GULLYTRADER_EXIT_MODE=shadow` | shadow | Hard-stop and LLM `sell` decisions are logged but never placed. |
| `GULLYTRADER_EXIT_MODE=live` | — | Sells are placed via `KalshiClient.place_limit_order(action='sell')` at `mark - 1¢`. |

Both default to `shadow` — the bot will run end-to-end against real Kalshi data and a real OpenRouter LLM with no real-money writes until you flip these. Mandatory: watch one full IPL match in shadow mode without errors before flipping either to `live`.

For day-to-day operations (debugging, inspecting logs, triggering manual passes): [docs/RUNBOOK.md](docs/RUNBOOK.md).

## Mobile UI

The 8-screen mobile UI lives under `gully-engine/static/`. Routes:

| Route        | Screen           |
|--------------|------------------|
| `#/`         | Dashboard home   |
| `#/match`    | Match centre     |
| `#/trends`   | Trends & insights|
| `#/standings`| Points table     |
| `#/upcoming` | Upcoming fixtures|
| `#/positions`| Positions / history |

The bet sheet is a modal overlay, launched from market rows in the match centre.

## Kalshi IPL coverage (verified 2026-05-01)

Kalshi lists IPL markets under these series:

| Series ticker | What it covers |
|---|---|
| `KXIPLGAME` | Per-match winner (e.g. `KXIPLGAME-26MAY07RCBLSG` = LSG vs RCB on May 7) |
| `KXIPL` | Season champion |
| `KXIPLPLAYOFF` | Playoff qualifiers |
| `KXIPLTEAMTOTAL` | Team total runs |
| `KXIPLSIX` / `KXIPLFOUR` | Sixes / fours props |

Filter is `series_ticker.startswith("KXIPL")` — correctly excludes `KXSAUDIPL*` (Saudi Pro League soccer, which would otherwise sneak in via substring matching). See [`reconciler.py`](gully-engine/reconciler.py) for the ticker parser.

## Cricket data feed

Pluggable via `CRICKET_FEED_PROVIDER`:

```bash
# default — design's reference figures, no network calls
CRICKET_FEED_PROVIDER=stub

# live — needs CRICKET_FEED_API_KEY (free key at https://cricketdata.org)
CRICKET_FEED_PROVIDER=cricapi
CRICKET_FEED_API_KEY=...
```

If `cricapi` is selected but the key is missing, the engine logs a warning and falls back to `stub` rather than crashing.

The CricAPI client uses the IPL series_id approach (1 hit to find the season's series, 1 hit per polling window for the full match list). Free tier is 100 hits/day; with the 60s in-process cache, all-day polling stays under the limit.

For the full provider survey (and why we picked CricAPI over Roanuz/SportMonks/scrapers): [docs/HANDOFF.md#cricket-data-decision](docs/HANDOFF.md).

## Inherited Kalshi learnings

These are the things you will get wrong if you reinvent them. They're documented inline in the relevant modules and tested:

1. **Binary contracts pay $1 (100¢).** Kalshi's API sometimes returns `value=0` — always default to 100. See [`pnl.py`](gully-engine/pnl.py).
2. **Paired-position P&L correction.** When a position has both YES and NO contracts, add `min(yes,no) * 100¢` to revenue. See [`pnl.py`](gully-engine/pnl.py) and [`tests/test_pnl.py`](gully-engine/tests/test_pnl.py).
3. **Hard stops bypass the LLM.** Stop loss, trailing stop, and time-based exits fire deterministically. See [`exit_monitor.py`](gully-engine/exit_monitor.py).
4. **Shadow → live always.** Run any new exit logic in shadow mode for a full session before flipping to live.
5. **Sync loop must keep alive.** Wrap DB writes in try/finally, swallow transient SQLite errors. See [`sync_service.py`](gully-engine/sync_service.py).
6. **WAL mode + agent_logs TTL.** SQLite WAL for concurrency, log rotation (default 7 days). See [`database.py`](gully-engine/database.py).
7. **Filter parlay/multi-game spam.** Drop `KXMVECROSSCATEGORY*` and `KXMVESPORTSMULTIGAME*`. See [`kalshi_client.py`](gully-engine/kalshi_client.py).
8. **Restart resilience.** Persist a current-state snapshot (the `cricket_matches` table is upserted each sync pass) + startup grace window so the exit monitor doesn't re-log noise.

## Project structure

```
GullyTrader/
├── README.md                       # You are here
├── CLAUDE.md                       # Working instructions for Claude Code
├── AGENTS.md                       # Same content for non-Claude AI agents
├── CONTRIBUTING.md                 # How to contribute
├── docs/
│   ├── ARCHITECTURE.md             # Deep architectural reference
│   ├── HANDOFF.md                  # Current state + next-up work
│   └── RUNBOOK.md                  # Operations / debugging
├── gully-engine/
│   ├── main.py                     # FastAPI app + REST endpoints
│   ├── orchestrator.py             # 2-thread orchestrator
│   ├── sync_service.py             # Background reconciliation
│   ├── database.py                 # SQLite schema (WAL)
│   ├── kalshi_client.py            # Kalshi API client (signed v2)
│   ├── cricket_data.py             # CricAPI + stub feeds
│   ├── reconciler.py               # Kalshi event ↔ CricAPI fixture matcher
│   ├── portfolio.py                # DB-derived metrics (day P&L, ROI, …)
│   ├── llm.py                      # OpenRouter client + agent_logs writer
│   ├── pnl.py                      # Paired-position P&L correction
│   ├── exit_monitor.py             # Hard-stop + LLM exit decisions
│   ├── settings.py                 # Env-driven config
│   ├── agents/
│   │   ├── scanner.py              # Implemented (LLM-ranked candidates)
│   │   ├── researcher.py           # LLM probability estimator (Phase 3)
│   │   ├── decision.py             # Quarter-Kelly sizer, pure math (Phase 3)
│   │   └── portfolio_exit.py       # LLM hold/sell, safety-default hold (Phase 3)
│   ├── static/                     # 8-screen React UI (no build step)
│   ├── tests/                      # 145 tests
│   └── requirements.txt
└── tasks/
    └── todo.md
```

## Continuing this work

If you're picking this up cold (Claude session, new contributor, future you), start with [docs/HANDOFF.md](docs/HANDOFF.md) — it has the current state, decisions log, and the ranked next-step list with concrete entry points.
