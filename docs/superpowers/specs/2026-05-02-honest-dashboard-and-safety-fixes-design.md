# Honest Dashboard + Safety Fixes — Design Spec

**Date:** 2026-05-02
**Branch:** `feat/honest-dashboard-and-safety-fixes`
**Scope option:** B — strip placeholders that lie, AND land safety/correctness fixes the previous phases left behind.
**Status:** Pre-implementation. Plan + tests follow.

---

## 1. Background

Phase 4 cleanup (PR #5) landed Apr 30 – May 2. It wired the bot toggle, real bot-status pill from `agent_logs`, dynamic position filter pills, and a `cricket_matches` writer. After that landed, an audit surfaced a remaining list of placeholders (cosmetic and substantive) plus two safety items the strict-auth-gating plan never finished landing. This spec addresses both in one branch.

This is not a feature — it's a cleanup. **No new endpoints, no new agents, no new screens.** Every change either deletes a lie or fixes a known correctness gap.

## 2. Goals

1. **Nothing on the rendered dashboard is fake.** If we don't have real data, the panel doesn't render.
2. **Strict-auth gating is complete** — production cannot start with missing Kalshi creds, and `place_limit_order` cannot return a stub order in prod.
3. **Trailing-stop math uses real per-position state**, not a hardcoded "opened 10 minutes ago, peak P&L = 0."
4. **DB hygiene** — orphaned ghost rows in `positions` are cleaned up at the source, dead schema (`exit_decisions`, `markets`) is dropped.

## 3. Non-goals

- Building new endpoints to feed the panels we're hiding (head-to-head, form guide, pitch & weather). Those go on the roadmap.
- Replacing the hardcoded "Devan" greeting on the dashboard. User opted to leave it.
- Implementing the `yes_ask` market field for marketable orders (`agents/decision.py:11` TODO). That's a feature, not safety.
- Backfilling the 262 existing `agent_logs` rows or 138 `orders` rows.
- Frontend build pipeline (still no-build).

## 4. Architecture overview

Five units of change, each independently testable:

```
┌─────────────────────────────────────────────────────────────┐
│                    feat/honest-dashboard-...                │
├─────────────────────────────────────────────────────────────┤
│ Unit A — Frontend honesty                                   │
│   • Remove StatusBar (battery/signal/9:41) from app.jsx     │
│   • Trends: hide 5 panels when no real data                 │
│   • Standings: remove 2 dead buttons                        │
│   • Cricket-charts: neutral defaults instead of fake teams  │
├─────────────────────────────────────────────────────────────┤
│ Unit B — Strict-auth gating completion                      │
│   • KalshiClient.__init__ raises in strict mode + unauthed  │
│   • place_limit_order raises on prod + unauthed             │
├─────────────────────────────────────────────────────────────┤
│ Unit C — Trailing-stop correctness                          │
│   • Read opened_at + peak_pnl_cents from positions table    │
│   • Add peak_pnl_cents column + writer in sync_service      │
├─────────────────────────────────────────────────────────────┤
│ Unit D — Position writer hygiene                            │
│   • Skip writing flat positions (yes_count + no_count == 0) │
│   • One-time DELETE migration for existing 28 ghost rows    │
├─────────────────────────────────────────────────────────────┤
│ Unit E — Dead schema removal                                │
│   • Drop `markets` table (never written)                    │
│   • Drop `exit_decisions` table (never written; logged via  │
│     agent_logs instead per llm.py path)                     │
└─────────────────────────────────────────────────────────────┘
```

Units are mostly independent; Unit C touches `database.py` schema (adds `peak_pnl_cents` column) and `sync_service.py` writer (sets it), so it sequences before Unit D in the same file. Unit E also touches `database.py` schema. The migrations all live in the same `_migrate()` function and apply in defined order.

## 5. Component specs

### Unit A — Frontend honesty

**A1. Remove the iPhone status bar.**
- Delete the `StatusBar` component definition in `gully-engine/static/primitives.jsx:3-21`.
- Remove from the `Object.assign(window, ...)` registration line at `primitives.jsx:127`.
- Remove the `<StatusBar/>` render at `app.jsx:185`.
- No replacement. The dashboard is web-rendered; pretending to be iOS is the lie.

**A2. Trends screen — hide panels when no real data.**

In `gully-engine/static/screen-trends.jsx`:

| Panel | Current state | New state |
|---|---|---|
| Manhattan chart (lines 4-5) | Hardcoded array fallback | Render only if `live?.last_balls` array exists and length > 0; else skip |
| Last 12 balls (lines 8-9) | Hardcoded fallback | Same — no fallback, just skip the row when missing |
| Head-to-head card (lines 82-95) | Always renders fake "3 vs 2" | Delete the entire card block |
| Form guide card (lines 101-103) | Always renders fake W/L | Delete the entire card block |
| Pitch & weather card (lines 128-143) | Always renders fake "Batting · 28°C" | Delete the entire card block |

Net result: Trends screen renders only the live scoreboard + Manhattan chart + recent-balls strip when a real match feed is active. When no live match, the screen is mostly empty header + a "No live match" empty state for the whole page.

**A3. Standings — remove dead buttons.**
- `screen-standings.jsx:149-150`: delete the `<button>...🔔 Notify</button>` and `<button>...Set autotrade</button>` lines.
- The container row may collapse — verify no broken layout.

**A4. Cricket-charts neutral defaults.**
- `cricket-charts.jsx:196-202`: change `Scoreboard` defaults from `teamA="MUM", teamB="CHE", runsA=142, ..., venue="Wankhede · 19:30 IST"` to `teamA="—", teamB="—", runsA=0, wicketsA=0, oversA="0.0", runsB=0, wicketsB=0, oversB="0.0", status="", venue="", innings=""`. Defaults should never be visually fake even though they're always overridden in production.

### Unit B — Strict-auth gating completion

Reference: `docs/superpowers/plans/2026-05-01-strict-external-service-auth-gating.md` Tasks 2 & 3.

**B1. KalshiClient strict-mode init guard.**

In `gully-engine/kalshi_client.py`, after the existing init-time auth check (around line 172-189), add:
```python
if not self._authed and settings.strict_external_services:
    raise RuntimeError(
        "KalshiClient cannot start in strict mode without valid credentials. "
        "Set KALSHI_API_KEY_ID + KALSHI_PRIVATE_KEY_PATH or run with "
        "GULLYTRADER_STRICT_EXTERNAL_SERVICES=false (dev only)."
    )
```

**B2. `place_limit_order` prod guard.**

At the top of `KalshiClient.place_limit_order` (around line 493):
```python
if not self._authed:
    if settings.kalshi_api_env == "prod":
        raise RuntimeError(
            "Refusing to place stub order in prod environment without auth. "
            "This would silently no-op a real trade."
        )
    return {"order_id": "stub-order", ...}  # existing dev fallback
```

The dev path remains unchanged so local testing stays frictionless.

### Unit C — Trailing-stop correctness

**Background.** `orchestrator.py:178-179` builds `PositionSnapshot` with `opened_at=now-600` (literally "10 minutes ago, always") and `peak_pnl_cents=0`. The `exit_monitor.evaluate()` function uses both:
- `opened_at` drives `time_stop` ("close after 90 minutes").
- `peak_pnl_cents` drives `trailing_stop` ("if we've given back >20% from peak, sell").

With both faked, `time_stop` never fires (always exactly 10 min in) and `trailing_stop` never fires (peak is always 0).

**C1. Schema change — add `peak_pnl_cents` column to `positions`.**

`database.py` SCHEMA: add `peak_pnl_cents INTEGER NOT NULL DEFAULT 0` after `unrealized_pnl_cents`.

`_migrate()`: add `ALTER TABLE positions ADD COLUMN peak_pnl_cents INTEGER NOT NULL DEFAULT 0` guarded against duplicate-column errors (existing migrations already use this pattern).

**C2. Writer — update `peak_pnl_cents` on every sync.**

In `sync_service._upsert_position`, after existing INSERT/UPDATE: compute current unrealized P&L (use the same formula as `portfolio.compute_metrics`) and `UPDATE positions SET peak_pnl_cents = MAX(peak_pnl_cents, ?) WHERE ticker = ?`. Peak only ever rises — never resets.

**C3. Reader — orchestrator pulls real values.**

`orchestrator.py:172-181` builds `PositionSnapshot`. Replace the two TODO lines with real lookups: SELECT `opened_at`, `peak_pnl_cents` FROM positions WHERE ticker = ?. If row missing (race during first sync) — skip exit evaluation for that position this tick (log and continue, don't crash).

### Unit D — Position writer hygiene

**D1. Filter at the writer.**

In `sync_service._upsert_position`: at the top, `if p.yes_count + p.no_count == 0: return`. Don't insert flat positions. They represent markets the user no longer holds — the historical fill record is in `fills`/`settlements`, the `positions` row adds nothing.

This stops new ghost rows. It does not affect the existing 28.

**D2. One-time cleanup migration.**

`database._migrate()`: add `DELETE FROM positions WHERE yes_count = 0 AND no_count = 0 AND realized_pnl_cents = 0` guarded by a `_migration_applied` marker (we already have `closed_market_cache` drop using the same pattern — copy that). The `realized_pnl_cents = 0` clause prevents accidentally deleting closed-with-PnL rows.

### Unit E — Dead schema removal

**E1. Drop `markets` table.**

Confirm one more time it has zero readers (grep showed only schema definition + prose mentions). `_migrate()`: `DROP TABLE IF EXISTS markets`.

**E2. Drop `exit_decisions` table.**

Comment in `exit_monitor.py:10` says `"exit_decisions but never places sells"` — confirms intent abandoned. Decisions are now logged via `agent_logs` (Phase 3 wiring). `_migrate()`: `DROP TABLE IF EXISTS exit_decisions`.

Both drops use the same migration-marker pattern as Unit D.

## 6. Data flow

No new flows. Existing flows mutate slightly:

- **Sync tick** (every 60s): `sync_service.reconcile()` → `client.list_positions()` → `_upsert_position()` (now skips flats, also writes `peak_pnl_cents`) → `_upsert_order()` → `_upsert_settlement()` (unchanged).
- **Exit tick** (every N seconds): `orchestrator.run_exit_monitor_once()` → for each open position, SELECT `opened_at, peak_pnl_cents` FROM positions → build `PositionSnapshot` with real values → `evaluate()` → if `sell` → `place_limit_order` (now guards prod-unauthed).
- **Frontend render**: same `/api/...` calls, but the JSX now skips panels conditionally instead of rendering fakes.

## 7. Error handling

- **Missing position row at exit-monitor read time** (Unit C3): log warning, skip that position this tick. Don't raise — sync will catch up next pass.
- **Strict mode startup failure** (Unit B1): hard fail uvicorn boot. This is intentional — we'd rather crash than silently run in mock mode in prod. Banner already in `main.py:61-74` will surface the reason.
- **prod + unauthed `place_limit_order`** (Unit B2): raise `RuntimeError`. Caller (`orchestrator.run_entry_pipeline_once`) already has try/except around the agent loop — exception is logged and the next tick proceeds. Failing one trade ≠ crashing the daemon.
- **Migration failures** (Unit D2, E1, E2): `_migrate()` already wraps each step in try/except for idempotency. Same pattern.

## 8. Testing strategy

TDD per unit. New tests mocked at the same layer as existing tests (HTTP for Kalshi, in-process for DB).

| Unit | New tests | Existing tests to update |
|---|---|---|
| A1-A4 | None (no-build frontend; manual smoke) | None |
| B1 | `test_kalshi_client_strict_mode.py` — assert raises when strict + unauthed; assert OK when strict + authed; assert OK when not strict + unauthed | `test_kalshi_client.py` may need a `strict_external_services=False` setting override for any tests that construct an unauthed client |
| B2 | `test_kalshi_place_order_prod_guard.py` — assert raises when prod + unauthed; assert returns stub when demo + unauthed | None |
| C1-C3 | `test_orchestrator_exit_uses_real_position_state.py` — seed positions with known `opened_at` and `peak_pnl_cents`, assert `PositionSnapshot` reflects them; assert missing-position-row case logs and skips | `test_sync_service.py` — assert `peak_pnl_cents` is updated on each sync |
| D1 | `test_sync_service_skips_flat_positions.py` — feed mock `KalshiPosition(yes_count=0, no_count=0)`, assert no row written | `test_sync_service.py` — verify existing positions tests still pass |
| D2 | `test_database_migration_purges_orphan_positions.py` — seed pre-migration DB with mix of orphans and real positions, run migration, assert orphans gone, real preserved | None |
| E1, E2 | `test_database_migration_drops_dead_schema.py` — assert tables don't exist post-migration | None |

**Test count delta:** +6 new test files, ~15 new test cases. Current 145 → expected ~160.

**Manual verification gate** (post-implementation):
- Boot `cd gully-engine && uvicorn main:app --reload --port 8001`.
- Open dashboard in browser, verify no battery icon, no "9:41" timestamp.
- Navigate to Trends — verify panels are hidden (or empty state) when no live match.
- Navigate to Standings — verify Notify/Autotrade buttons gone.
- Run `sqlite3 gullytrader.db "SELECT COUNT(*) FROM positions WHERE yes_count + no_count = 0"` → expect 0.
- Run `sqlite3 gullytrader.db ".tables"` → expect no `markets`, no `exit_decisions`.

## 9. Sequencing & risk

Build order:
1. **Unit E** (drop dead schema) — safest, no behavior impact, just hygiene.
2. **Unit D** (position writer hygiene) — fixes ongoing ghost-row creation + cleans existing.
3. **Unit C** (trailing-stop correctness) — schema add + writer + reader; depends on `positions` being clean (Unit D first).
4. **Unit B** (strict-auth gating) — backend safety, isolated from above.
5. **Unit A** (frontend) — no test coverage, manual verify last.

**Risks:**
- **Unit C reader race**: if exit-monitor reads `positions` before the first sync writes `peak_pnl_cents`, the SELECT returns NULL. Handled in C3 (skip + log).
- **Unit D2 over-deletion**: `realized_pnl_cents = 0` filter protects closed-with-pnl rows; verified with a test.
- **Unit B1 surprise breakage**: any dev who has stale `.env` with no creds will see uvicorn refuse to start. Mitigation: the existing strict-auth-gating plan already added `_strict_default()` that returns `False` outside prod, so dev is unaffected by default.

## 10. Out of scope (future)

- `/api/profile` endpoint to dynamically render dashboard greeting.
- `/api/match/{id}/head-to-head`, `/api/team/{id}/form`, pitch/weather feed — to bring back the Trends panels with real data.
- `KalshiMarket.yes_ask` field for marketable orders (`agents/decision.py:11` TODO).
- Recurring purge cron for stale `positions` (the writer-side filter prevents future accumulation; ad-hoc cleanup is sufficient for now).
