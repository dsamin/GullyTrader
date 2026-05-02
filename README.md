# GullyTrader

Autonomous IPL prediction-market trader for Kalshi. Multi-agent LLM pipeline picks markets, sizes positions, and manages exits; a mobile-first cricket dashboard lets you watch the bot work and override when needed.

> **Sister project to [KalshiTrader](https://github.com/dsamin/KalshiTrader).** Same engine architecture (Python/FastAPI + SQLite/WAL + multi-agent LLM pipeline) — narrowed to IPL cricket markets and paired with a dedicated mobile UI.

## Status

**Pre-alpha, foundation complete.** Scanner agent proven against live OpenRouter and live Kalshi, reconciler bridges Kalshi events ↔ CricAPI fixtures, full mobile UI renders against real data.

| Component | State |
|---|---|
| Frontend (8 screens, mobile-first React) | ✅ rendering against live data |
| Kalshi RSA-PSS auth (prod) | ✅ verified — balance + 18 IPL events surface |
| CricAPI integration (live + fixtures + standings) | ✅ wired with 60s in-process cache |
| Kalshi ↔ CricAPI reconciler (event-ticker parsing) | ✅ 8/10 fixtures correlate to Kalshi events |
| Scanner agent (LLM-ranked market candidates) | ✅ ~16s round-trip, real grounded reasoning |
| Researcher / Decision / Exit agents | ⏳ stubs — see [docs/HANDOFF.md](docs/HANDOFF.md) |
| Sync service | ⏳ scaffold only — no real reconciliation logic yet |
| Tests | ✅ 61 passing |

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
│   ├─ Entry pipeline ── Scanner → Researcher → Decision → buy   │
│   └─ Exit monitor   ── always-on; hard stops bypass LLM        │
│                       shadow logs decisions, live places sells │
│                                                                │
│  Sync service ── reconciles orders / fills / settlements       │
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
8. **Restart resilience.** Persist closed-market cache + startup grace window so the exit monitor doesn't re-log noise.

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
│   ├── llm.py                      # OpenRouter client + agent_logs writer
│   ├── pnl.py                      # Paired-position P&L correction
│   ├── exit_monitor.py             # Hard-stop + LLM exit decisions
│   ├── settings.py                 # Env-driven config
│   ├── agents/
│   │   ├── scanner.py              # Implemented (LLM-ranked candidates)
│   │   ├── researcher.py           # Stub
│   │   ├── decision.py             # Stub
│   │   └── portfolio_exit.py       # Stub
│   ├── static/                     # 8-screen React UI (no build step)
│   ├── tests/                      # 61 tests
│   └── requirements.txt
└── tasks/
    └── todo.md
```

## Continuing this work

If you're picking this up cold (Claude session, new contributor, future you), start with [docs/HANDOFF.md](docs/HANDOFF.md) — it has the current state, decisions log, and the ranked next-step list with concrete entry points.
