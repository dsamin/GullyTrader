# GullyTrader — Project Instructions for Claude

## Read these first

If you're picking up cold, read in order:

1. **[README.md](README.md)** — what this project is, current state, quickstart
2. **[docs/HANDOFF.md](docs/HANDOFF.md)** — what's done, what's next, decision log
3. **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** — how the pieces fit together
4. **[docs/RUNBOOK.md](docs/RUNBOOK.md)** — how to run / debug / inspect logs
5. **[CONTRIBUTING.md](CONTRIBUTING.md)** — code style, branch/PR workflow, test conventions

The handoff doc has the ranked next-step list — default to that unless the user redirects you.

## Mandatory: README + relevant doc updates

**Every time code changes are made to logic, features, endpoints, configuration, database schema, or agent behavior, the README.md AND the relevant `docs/*.md` MUST be updated in the same PR.** Non-negotiable.

Specifically, update when:
- Adding, modifying, or removing API endpoints
- Changing the trading algorithm or agent pipeline logic
- Adding or modifying database tables/columns
- Changing configuration keys or defaults
- Adding new files or significantly restructuring existing ones
- Fixing bugs that change observable behavior (P&L calculations, exit triggers, etc.)
- Changing LLM models or provider integration
- Modifying the dashboard UI or adding new panels/features

## Workflow

1. **Plan first** — Enter plan mode for any non-trivial task (3+ files, new module, contract change)
2. **Branch + PR** — `git checkout -b feat/something`, push, open PR via `gh pr create`. Don't push directly to `main` for feature work.
3. **Test** — `cd gully-engine && python -m pytest` before committing. Mock external services.
4. **Verify against live** — boot uvicorn, hit the relevant endpoint, confirm `agent_logs` row landed (where applicable)
5. **Update docs** — README + the matching `docs/*.md` in the same PR

## Bug Tracker

Active work is tracked in [`tasks/todo.md`](tasks/todo.md). The handoff doc has the ranked engineering plan.

## Inherited learnings from KalshiTrader (don't relearn these)

These are the things you will get wrong if you reinvent them. Each is rooted in a real incident in the parent project.

1. **Kalshi binary contracts pay $1 (100¢).** API sometimes returns `value=0` — always default to 100. Never trust the raw value field.
2. **Paired-position P&L correction.** When both YES and NO counts > 0, add `min(yes,no) * 100¢` to revenue. Without this, profitable early-exit trades show as phantom losses.
3. **Hard-stop exits bypass the LLM.** Stop loss, trailing stop, time-based exits fire deterministically. LLM is only for nuanced "should I take profit early" calls.
4. **Shadow → live always.** New exit logic runs in `EXIT_MODE=shadow` for a full session before flipping to `live`.
5. **Sync / orchestrator loops must keep alive.** Wrap DB writes in try/finally. Swallow transient SQLite open failures with backoff. Never let a single exception crash a daemon thread.
6. **WAL mode + agent_logs TTL rotation** (default 7 days).
7. **Filter parlay markets** (`KXMVECROSSCATEGORY*`, `KXMVESPORTSMULTIGAME*`) at the scanner level.
8. **IPL series prefix is `KXIPL`.** Use `series_ticker.startswith("KXIPL")` — correctly excludes `KXSAUDIPL*` (Saudi Pro League soccer) which a naive `"ipl"` substring search would mistakenly include.
9. **Persist closed-market cache** to avoid restart noise; add a startup grace window.
10. **Verify deployed `.env` LLM model names match code defaults** — once burned by `qwen/qwen2.5-72b` (no hyphen) vs `qwen/qwen-2.5-72b-instruct` (with hyphen).

## Frontend rules

- **Don't add a build step.** The design uses React 18 + Babel-via-CDN, and that no-build simplicity is intentional. ~12 frontend files, all readable as plain JSX in any editor.
- **Use the design system** in [`gully-engine/static/styles.css`](gully-engine/static/styles.css). The `--saffron / --pitch / --crimson / --gold / --navy` palette is fixed. Don't introduce new colors.
- **Mobile-first** — design at 390×844 (iPhone 14). Desktop layout is a stretch goal.
- **The 8 screens** are: dashboard, match, trends, standings, upcoming, bet sheet (modal), positions, component library.
- **Bottom tab bar drives routing.** Bet sheet is a modal, not a route.
- Components register globally via `Object.assign(window, {...})` at the bottom — that's the no-bundler pattern.

## Pattern references

When implementing a new LLM agent: copy [`agents/scanner.py`](gully-engine/agents/scanner.py).
When adding a new HTTP-mocked test: copy [`tests/test_cricket_data.py`](gully-engine/tests/test_cricket_data.py).
When adding a new LLM-mocked test: copy [`tests/test_scanner.py`](gully-engine/tests/test_scanner.py).
When adding a new external data feed: copy [`cricket_data.CricApiFeed`](gully-engine/cricket_data.py) — protocol-conforming class, defensive HTTP, in-memory caching, factory wiring.
When fixing a bug: the regression test goes in the same commit. [`tests/test_pnl.py`](gully-engine/tests/test_pnl.py) is the model.

## Security

- Never commit `.env`. The `.gitignore` excludes it; double-check `git status` before staging.
- Never put secrets in commit messages or PR descriptions.
- The Kalshi private key path in `.env` points to a file outside the repo.
