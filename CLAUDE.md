# GullyTrader — Project Instructions

## Mandatory: README Updates

**Every time code changes are made to logic, features, endpoints, configuration, database schema, or agent behavior, the README.md MUST be updated to reflect those changes.** This is non-negotiable.

Specifically, update the README when:
- Adding, modifying, or removing API endpoints
- Changing the trading algorithm or agent pipeline logic
- Adding or modifying database tables/columns
- Changing configuration keys or defaults
- Adding new files or significantly restructuring existing ones
- Fixing bugs that change observable behavior (P&L calculations, exit triggers, etc.)
- Changing LLM models or provider integration
- Modifying the dashboard UI or adding new panels/features

## Workflow

1. **Plan first** — Enter plan mode for any non-trivial task (3+ steps)
2. **Branch + issue** — Create a git branch and GitHub issue before code changes
3. **Test** — Run `cd gully-engine && python -m pytest` before committing
4. **PR** — Push changes via pull request, never directly to main
5. **Verify** — Check the dashboard at http://localhost:8001 after deploys

## Bug Tracker

Active bugs and tasks are tracked in `tasks/todo.md`.

## Key Context

- All code lives under `gully-engine/`
- Frontend uses React 18 + Babel standalone (CDN, no build step) — matches the design prototype
- Backend mirrors KalshiTrader patterns: WAL SQLite, multi-agent LLM pipeline, sync service, hard-stop exits
- Markets are Kalshi binary YES/NO contracts (1–99¢, $1 payout) — never decimal odds, never accumulators
- Cricket data feed is pluggable (CricBuzz/SportMonks/fixture stub)

## Inherited learnings from KalshiTrader (don't relearn these)

1. Kalshi binary contracts pay $1 (100¢). API sometimes returns `value=0` — always default to 100.
2. Paired-position P&L correction: when both YES and NO counts > 0, add `min(yes,no) * 100¢` to revenue.
3. Hard-stop triggers (stop loss, trailing, time) BYPASS the LLM. Only use LLM for nuanced exit calls.
4. Always ship shadow mode first, flip to live after a full session of clean shadow logs.
5. Sync loop must keep alive on transient SQLite failures (try/finally on every write).
6. WAL mode + agent_logs TTL rotation (default 7 days).
7. Filter parlay markets (`KXMVECROSSCATEGORY*`, `KXMVESPORTSMULTIGAME*`).
8. Persist closed-market cache to avoid restart noise; add a startup grace window.
9. Verify deployed `.env` LLM model names match code expectations (the qwen hyphen issue).

## Frontend rules

- Don't add a build step. The design uses React 18 + Babel standalone via CDN, and that simplicity is a feature.
- Use the design system in `static/styles.css` — color tokens, type, spacing. Don't introduce new colors.
- Mobile-first: design at 390×844 (iPhone 14). Desktop layout is a stretch goal.
- The 8 screens are: dashboard, match, trends, standings, upcoming, bet sheet (modal), positions, component library.
- Bottom tab bar drives routing. Bet sheet is a modal, not a route.
