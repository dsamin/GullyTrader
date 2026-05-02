# RUNBOOK

Day-to-day operations: run, debug, inspect, troubleshoot.

## Running the dev server

```bash
cd gully-engine
source .venv/bin/activate                     # (one-time: python -m venv .venv && pip install -r requirements.txt)
uvicorn main:app --reload --port 8001
```

Open http://localhost:8001. The dashboard pulls real data when `.env` has Kalshi + OpenRouter + CricAPI credentials.

To enable the orchestrator's daemon threads (entry pipeline + exit monitor running on a loop):

```bash
GULLYTRADER_ENABLE_ORCHESTRATOR=1 uvicorn main:app --port 8001
```

The orchestrator loop polls every `GULLYTRADER_LIVE_POLL_INTERVAL_SECONDS` (default 5s) when enabled. The sync service polls every `GULLYTRADER_SYNC_INTERVAL_SECONDS` (default 60s).

## Running tests

```bash
cd gully-engine
python -m pytest                # full suite
python -m pytest -v             # verbose
python -m pytest tests/test_scanner.py -v   # one file
python -m pytest -k "paired"    # by name pattern
```

Tests are fully mocked — no network, no real DB writes. Should run in < 0.5s.

## Triggering the LLM pipeline manually

The orchestrator's entry pipeline is heavy (Kalshi pagination + OpenRouter call ~15-20s). Trigger it on demand without enabling the daemon threads:

```bash
# Scan + score open IPL markets
curl -sS -X POST http://localhost:8001/api/orchestrator/run-entry | jq

# Evaluate exit decisions for all open positions
curl -sS -X POST http://localhost:8001/api/orchestrator/run-exit | jq
```

The endpoints use non-blocking locks. If a pass is already running, you get `{"status": "skipped", "reason": "already_running"}` immediately rather than queuing.

## Inspecting state

### Agent decision audit log

Every LLM call writes a row. Sorted newest-first:

```bash
sqlite3 gullytrader.db "
  SELECT agent, ticker, model, latency_ms,
         datetime(created_at, 'unixepoch', 'localtime') as t
  FROM agent_logs
  ORDER BY created_at DESC LIMIT 20"
```

Full reasoning text per call:

```bash
sqlite3 gullytrader.db "
  SELECT agent, substr(reasoning, 1, 200) as preview
  FROM agent_logs
  ORDER BY created_at DESC LIMIT 5"
```

### Open positions snapshot

```bash
sqlite3 gullytrader.db "
  SELECT ticker, yes_count, no_count, avg_cost_cents,
         realized_pnl_cents, unrealized_pnl_cents, status
  FROM positions WHERE status='open'"
```

### Exit decisions (shadow + live)

Exit decisions are logged into `agent_logs` with `agent='exit'`. The
`reasoning` column carries the trigger as a prefix (e.g. `stop_loss:`,
`trailing_stop:`, `time:`, `llm:`, `manual:`) so a single `LIKE` query
buckets exits by cause. (The dedicated `exit_decisions` table was dropped
in Phase 5 — agent_logs is the single source of truth.)

```bash
sqlite3 gullytrader.db "
  SELECT ticker, decision, reasoning,
         datetime(created_at, 'unixepoch', 'localtime') as t
  FROM agent_logs
  WHERE agent='exit'
  ORDER BY created_at DESC LIMIT 20"
```

## Bot toggle

### Toggle the bot on/off

From the dashboard, click the bot pill. The toggle persists to `bot_state.active` and idempotently starts or stops the orchestrator entry/exit threads. Restarts respect the persisted toggle, not the env var.

**Known limitation:** the toggle does NOT stop `sync_service` (the Kalshi reconciliation poll). When the bot is "off," sync continues polling positions/orders/fills/settlements every 60s. This is wasteful but harmless — sync doesn't place orders. A future Phase 5 task will wire sync_service into the toggle for true symmetry.

**Manual override:**

```bash
sqlite3 gullytrader.db "UPDATE bot_state SET active=1, updated_at=strftime('%s','now') WHERE id=1"
```

**Force re-seed from env on next boot:**

```bash
sqlite3 gullytrader.db "DELETE FROM bot_state"
# next process restart will re-init from GULLYTRADER_ENABLE_ORCHESTRATOR
```

### What's the bot been doing?

```bash
sqlite3 gullytrader.db "SELECT datetime(created_at,'unixepoch'), agent, ticker, decision, substr(reasoning,1,80) FROM agent_logs WHERE agent IN ('decision','exit') ORDER BY created_at DESC LIMIT 20"
```

The `agent='exit'` rows have a trigger prefix in `reasoning` (`stop_loss: ...`, `trailing_stop: ...`, `time: ...`, `llm: ...`). To filter by trigger:

```bash
sqlite3 gullytrader.db "SELECT datetime(created_at,'unixepoch'), ticker, reasoning FROM agent_logs WHERE agent='exit' AND reasoning LIKE 'stop_loss:%' ORDER BY created_at DESC"
```

## Probing live services without booting the server

Useful when investigating an API issue without restarting uvicorn.

### Kalshi auth + IPL events

```bash
cd gully-engine && source .venv/bin/activate
python -c "
from kalshi_client import KalshiClient
c = KalshiClient()
print('authed:', c._authed)
print('balance:', c.get_balance())
events = c.list_ipl_events()
print(f'{len(events)} IPL events')
for e in events[:3]:
    print(f'  {e.event_ticker} | {e.title}')
"
```

### CricAPI quota and IPL data

```bash
cd gully-engine && source .venv/bin/activate
python -c "
from settings import settings
from cricket_data import CricApiFeed
f = CricApiFeed(api_key=settings.cricket_feed_api_key)
matches = f._ipl_match_list()
print(f'{len(matches)} IPL matches in season')
upcoming = [m for m in matches if not m.get('matchStarted')]
print(f'{len(upcoming)} upcoming')
"
```

CricAPI's free tier is 100 hits/day. Each `_ipl_match_list()` call uses 0–2 hits depending on cache state. Quota info is logged at DEBUG level whenever a real call lands.

## Common issues

### Server won't start: `[Errno 48] address already in use`

Something is already on port 8001 — likely a previous uvicorn that didn't shut down cleanly. Find and kill it:

```bash
lsof -i :8001 -sTCP:LISTEN
# Note the PID, then:
kill <pid>
```

Or just start uvicorn on a different port: `uvicorn main:app --reload --port 8002`.

### Dashboard shows stub data ("MUM 142/4 (15.2)") even though I set CRICKET_FEED_PROVIDER=cricapi

Either:
1. The `.env` change didn't take effect (uvicorn was started before the edit). With `--reload`, code edits auto-reload, but env-var changes require a full restart. Stop uvicorn, restart it.
2. The CricAPI key isn't set or is invalid. The factory falls back to stub when the key is missing — check the startup log for `CricApiFeed instantiated without an API key`.
3. CricAPI returned an error. Check uvicorn logs for `CricAPI ... returned 4xx` lines.

### `POST /api/orchestrator/run-entry` returns `{"status": "skipped", "reason": "no_live_match"}`

Pass `?force=true` to bypass the live-match gate, or wait for an actual IPL match to start. The pipeline is gated by default to avoid burning OpenRouter quota during off-hours.

Actually it's hardcoded `force=True` in the manual trigger — so this shouldn't happen. If you see this from the manual endpoint, check whether the `force` param made it through.

### Scanner returns 0 candidates with `score < 30`

Means the LLM ranked everything below the threshold. Possible causes:
- No live match → LLM has no proximity context, scores everything low
- Markets are all illiquid → LLM correctly refuses to recommend
- Prompt drift → LLM is being too conservative

Adjust `MIN_SCORE` in `agents/scanner.py` if you want a lower threshold during testing.

### `agent_logs` empty after a run

Either:
- LLM call failed before writing (check uvicorn log for `OPENROUTER_API_KEY missing` or HTTP errors)
- DB write failed (check for `failed to write agent_log` warnings in the log)
- You're looking at the wrong DB file — `gullytrader.db` is created in the working directory at startup

### Reconciler doesn't match a fixture I expect

Check both:
1. Does `KalshiClient.list_ipl_events()` actually include the expected `KXIPLGAME-{date}{teams}` event? Kalshi removes events from the open filter once they're imminent or live.
2. Does `reconciler.parse_kxiplgame_ticker(event_ticker)` return the right design codes? Edge case: if a new IPL franchise gets added, the `IPL_FRANCHISE_CODES` tuple needs an update.

## Hard reset

If the local DB gets into a weird state, just delete it. The schema is rebuilt on next startup:

```bash
rm gullytrader.db gullytrader.db-shm gullytrader.db-wal
```

This loses all `agent_logs` and any cached state. Real state lives on Kalshi — none of this is authoritative.

## Smoke-test sequence

Quick 60-second verification that everything's wired correctly:

```bash
# 1. Tests pass
cd gully-engine && source .venv/bin/activate && python -m pytest && cd ..

# 2. Server boots
cd gully-engine && uvicorn main:app --port 8001 &
sleep 3

# 3. Each major endpoint returns 200 with non-empty body
for path in /api/portfolio /api/positions /api/match/live /api/fixtures /api/standings /api/events/ipl /api/bot/status; do
  code=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8001$path)
  echo "$code $path"
done

# 4. Pipeline trigger works (slow — ~15-20s due to OpenRouter)
curl -sS -X POST http://localhost:8001/api/orchestrator/run-entry | jq '{markets_scanned, candidate_count: (.candidates | length)}'

# 5. agent_logs shows the call
sqlite3 gullytrader.db "SELECT agent, latency_ms FROM agent_logs ORDER BY created_at DESC LIMIT 1"

# Stop the server
kill %1
```

## Troubleshooting Kalshi specifically

If `/api/portfolio` returns mock-looking data ($87.89 balance specifically — that's the mock value), the client isn't authed:

1. Check `.env` has `KALSHI_API_ENV=prod`, `KALSHI_KEY_ID=<your_id>`, `KALSHI_PRIVATE_KEY_PATH=<absolute_path>`
2. Check the private key file exists at the path: `ls -la $(grep KALSHI_PRIVATE_KEY_PATH .env | cut -d= -f2-)`
3. Restart uvicorn (env changes don't hot-reload)
4. Check uvicorn log for `KalshiClient running unauthenticated — returning mock data` (means `_authed=False`)

If signing fails (`KALSHI 401` or `403`), the private key probably doesn't match the key_id. Check both came from the same Kalshi account dashboard.
