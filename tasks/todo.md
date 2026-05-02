# GullyTrader — Open Tasks

The ranked engineering plan with implementation notes lives in [`docs/HANDOFF.md`](../docs/HANDOFF.md). This file tracks check-the-box state.

## Now (next code task)

- [ ] **Researcher agent** — consume scanner candidates, return estimated probability + confidence + grounded reasoning. Pattern: copy `agents/scanner.py`. ~1.5 hrs.
- [ ] **Decision agent** — consume `ResearchNote`, compute Kelly fraction, return `TradeDecision`. ~1.5 hrs. Hold in review longer than the others (real-money risk).
- [ ] **Portfolio-exit agent** — LLM-driven nuanced exits when no hard stop fires. Must run shadow-mode for a full match before flipping to live. ~1.5 hrs.
- [ ] **Sync service real reconciliation** — pull orders/fills/settlements/balance from Kalshi, upsert into local DB. Currently a `log.debug` stub. ~1 hr.

## Operational follow-ups (don't block agents)

- [ ] Wire `database.purge_old_agent_logs()` into the lifespan startup hook (defined, not called)
- [ ] Persist `closed_market_cache` table actually getting written/read (table exists, nothing populates it)
- [ ] Add request-level logging middleware on FastAPI
- [ ] Backfill test coverage toward 170+ (KalshiTrader's bench). Priorities: orchestrator manual-trigger lock semantics, sync_service keep-alive, exit_monitor hard-stop matrix, kalshi_client RSA signing format
- [ ] Add Playwright visual regression for the 8 screens

## UX polish

- [ ] Confetti animation on winning settlement (CSS in `styles.css`, just needs trigger)
- [ ] Pull-to-refresh on Home + Match Centre
- [ ] Long-press on position cards for quick close / set alert
- [ ] Reduced-motion media query support (rules already in styles.css, just verify)

## Deploy (when ready)

- [ ] Pick a host (parent KalshiTrader uses `kalshi.devanvibes.work`)
- [ ] `KALSHI_API_ENV=prod` in deployed env
- [ ] Audit any keys that may have leaked into commits (none should have)
- [ ] Process supervisor (systemd / fly.io / similar)
- [ ] `/health` endpoint + external uptime monitoring

## Done

- [x] Project skeleton + README + CLAUDE.md (2026-04-30)
- [x] Backend module stubs ported from KalshiTrader (2026-04-30)
- [x] Frontend lifted from claude.ai/design bundle, hash-router (2026-04-30)
- [x] P&L paired-position correction implementation + tests (2026-04-30)
- [x] Kalshi RSA-PSS auth wired and verified against prod (2026-04-30)
- [x] CricAPI integration via /series_info + /series_points + 60s cache (2026-04-30 → 2026-05-01)
- [x] Reconciler: Kalshi event ticker parsing + Kalshi↔CricAPI fixture matcher (2026-04-30)
- [x] Scanner agent against real OpenRouter — ranked candidates with grounded reasoning (2026-04-30)
- [x] llm.py — OpenRouter client with agent_logs audit trail (2026-04-30)
- [x] Public GitHub repo with PR workflow (2026-04-30)
- [x] 61-test bench covering P&L, cricket feed, scanner, reconciler (2026-05-01)
- [x] Comprehensive doc set: AGENTS.md, ARCHITECTURE.md, HANDOFF.md, RUNBOOK.md, CONTRIBUTING.md (2026-05-01)
