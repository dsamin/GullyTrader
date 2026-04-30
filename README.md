# GullyTrader

Autonomous IPL prediction-market trader for Kalshi. Multi-agent LLM pipeline picks markets, sizes positions, and manages exits; a mobile-first dashboard lets you watch the bot work and override when needed.

> **Sister project to [KalshiTrader](https://github.com/dsamin/KalshiTrader).** Same engine architecture (Python/FastAPI + SQLite/WAL + multi-agent LLM pipeline) — narrowed to IPL cricket markets and paired with a dedicated mobile UI.

## Stack

- **Backend:** Python 3.11+ / FastAPI / SQLite (WAL)
- **Frontend:** React 18 + Babel standalone (CDN, no build step) — matches the design prototype runtime
- **LLMs:** Configurable via OpenRouter (`qwen/qwen-2.5-72b-instruct` default)
- **Markets:** Kalshi binary YES/NO contracts (1–99¢, $1 payout)
- **Data feed:** Pluggable cricket feed (CricBuzz / SportMonks / fixture stub)

## Architecture

```
┌────────────────────────────────────────────────────────────────┐
│                     gully-engine                                │
│                                                                 │
│  Orchestrator (2 threads)                                       │
│    ├─ Entry pipeline   ── only when matches are active          │
│    │    Scanner → Researcher → Decision → place order           │
│    └─ Exit monitor     ── always-on                             │
│         hard stops (TP/SL/time) bypass LLM                      │
│         shadow mode logs decisions; live mode places sells      │
│                                                                 │
│  Sync service (background, 45–180s)                             │
│    reconciles orders / fills / settlements                      │
│    keep-alive on transient SQLite/Kalshi failures               │
│                                                                 │
│  Cricket data feed                                              │
│    ball-by-ball state for live LLM context                      │
│    fixtures, standings, H2H, form                               │
│                                                                 │
│  FastAPI                                                        │
│    serves /static (React UI)                                    │
│    REST endpoints under /api/*                                  │
└────────────────────────────────────────────────────────────────┘
```

## Quickstart

```bash
cd gully-engine
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Option 1 — share the KalshiTrader account (recommended for hobby use):
cp ../../KalshiTrader/kalshi-engine/.env .env

# Option 2 — fresh credentials:
cp .env.example .env   # then fill in KALSHI_*, OPENROUTER_API_KEY, etc.

# run dev server (no orchestrator threads)
uvicorn main:app --reload --port 8001

# run with orchestrator + sync threads enabled
GULLYTRADER_ENABLE_ORCHESTRATOR=1 uvicorn main:app --port 8001
```

Open http://localhost:8001 — when authed, the dashboard pulls real balance + IPL events from Kalshi.

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

The bet sheet is a modal overlay, launched from match centre or quick actions.

## Kalshi integration learnings carried over from KalshiTrader

These are the things you will get wrong if you reinvent them. They are documented inline in the relevant modules:

1. **Binary contracts pay $1 (100¢).** Kalshi's API sometimes returns `value=0` — always default to 100. See `kalshi_client.py`.
2. **Paired-position P&L correction.** When a position has both YES and NO contracts (early-exit residue), add `min(yes,no) * 100¢` to revenue. See `pnl.py`.
3. **Hard stops bypass the LLM.** Stop loss, trailing stop, and time-based exits fire deterministically. Only use the LLM for nuanced "should I take profit early" calls. See `exit_monitor.py`.
4. **Shadow → live always.** Run any new exit logic in shadow mode for a full session before flipping to live.
5. **Sync loop must keep alive.** Wrap DB writes in try/finally, swallow transient SQLite errors, never let a single failure kill the loop. See `sync_service.py`.
6. **WAL mode + agent_logs TTL.** SQLite WAL mode for concurrency, log rotation (default 7 days) to prevent unbounded growth.
7. **Filter parlay/multi-game spam.** Kalshi's API surfaces parlay markets like `KXMVECROSSCATEGORY*` — they're not relevant here, drop them at scanner level.
8. **Restart resilience.** Persist closed-market cache so the exit monitor doesn't re-log the same noise on every restart. Use a startup grace window.

## Project structure

```
GullyTrader/
├── README.md
├── CLAUDE.md                       # Working instructions for Claude
├── gully-engine/
│   ├── main.py                     # FastAPI app + REST endpoints
│   ├── orchestrator.py             # 2-thread orchestrator
│   ├── sync_service.py             # Background reconciliation
│   ├── database.py                 # SQLite schema (WAL)
│   ├── kalshi_client.py            # Kalshi API client
│   ├── cricket_data.py             # Sports data feed (CricBuzz/SportMonks)
│   ├── pnl.py                      # Paired-position correction
│   ├── exit_monitor.py             # Hard-stop + LLM exits
│   ├── settings.py                 # Env-driven config
│   ├── agents/                     # Multi-agent LLM pipeline
│   │   ├── scanner.py
│   │   ├── researcher.py
│   │   ├── decision.py
│   │   └── portfolio_exit.py
│   ├── static/                     # React UI (no build step)
│   ├── tests/
│   └── requirements.txt
└── tasks/
    └── todo.md                     # Bug tracker
```

## Kalshi IPL coverage (verified 2026-04-30)

Kalshi already lists IPL markets — 18 open events at the time of writing across these series:

| Series ticker | What it covers |
|---|---|
| `KXIPLGAME` | Per-match winner (e.g. `KXIPLGAME-26MAY07RCBLSG` = LSG vs RCB on May 7) |
| `KXIPL` | Season champion |
| `KXIPLPLAYOFF` | Playoff qualifiers |
| `KXIPLTEAMTOTAL` | Team total runs |
| `KXIPLSIX` / `KXIPLFOUR` | Sixes / fours props |

The series-prefix filter `KXIPL` correctly excludes `KXSAUDIPL*` (Saudi Pro League soccer, which would otherwise sneak in via substring matching).

## Cricket data feed

Kalshi gives us markets and prices. For ball-by-ball state, scores, fixtures, and standings we need a separate feed. After surveying the market (April 2026):

- **CricketData / CricAPI** ([cricketdata.org](https://cricketdata.org/pricing/)) — **implemented**. $12.99/mo for 10K hits/day; free tier is 100 hits/day (fine for development, too small for live polling). Permissive ToS (allows trading use).
- **SportMonks Cricket** — €29/mo, explicit ToS coverage for betting/fantasy/gaming. Good fallback if CricAPI doesn't pan out.
- **Cricsheet.org** — MIT-licensed, free, **historical only** — perfect for backtesting against 1,200+ archived IPL matches.
- **Avoid:** Roanuz (ToS forbids monetized use), unofficial Cricbuzz scrapers on RapidAPI (legally fragile).

**Recommended stack:** Cricsheet (free, historical) + CricAPI ($12.99/mo, live).

### Switching between providers

```bash
# default — design's reference figures, no network calls
CRICKET_FEED_PROVIDER=stub

# live — needs CRICKET_FEED_API_KEY set (free key at https://cricketdata.org)
CRICKET_FEED_PROVIDER=cricapi
CRICKET_FEED_API_KEY=...
```

If `cricapi` is selected but the key is missing, the engine logs a warning and falls back to `stub` rather than crashing. The CricAPI client is defensive: HTTP errors, rate-limit responses, and malformed payloads all return empty results instead of raising.

## Status

Pre-alpha.

✅ Frontend renders all 8 screens (mobile + desktop phone-shell preview)
✅ Kalshi RSA-PSS auth works against prod — real balance, real IPL events
✅ Paired-position P&L correction tested
✅ 18 real IPL events surface through `/api/events/ipl`

✅ CricAPI cricket feed wired (defensive: handles errors, rate limits, shape variation)
✅ 25 tests passing (P&L correction + cricket feed coverage)

⏳ LLM agents (scanner/researcher/decision/exit) all return `pass` / `hold` until wired
⏳ Test bench is at 25; needs to grow to KalshiTrader's 170+ rigor
