# AGENTS.md

> Instructions for AI coding assistants picking up work on GullyTrader.
> (Same content as `CLAUDE.md` — keeping a copy here because some agents look for `AGENTS.md` by convention.)

## Read these first, in order

1. **[README.md](README.md)** — what this project is, current state, quickstart
2. **[docs/HANDOFF.md](docs/HANDOFF.md)** — what's done, what's next, the decision log
3. **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** — how the pieces fit together
4. **[docs/RUNBOOK.md](docs/RUNBOOK.md)** — how to run / debug / inspect logs

That's enough context to start contributing. Don't read code files first — the docs reference the relevant ones.

## Non-negotiables

These rules come from real incidents in the parent project (KalshiTrader). Violating them re-creates bugs we've already paid for.

1. **Binary Kalshi contracts pay $1 (100¢).** API sometimes returns `value=0` — always default to 100. Never trust the raw value field.
2. **Paired-position P&L correction.** When a position has both YES and NO counts > 0, add `min(yes,no) * 100¢` to revenue. Without this, profitable early-exit trades show as phantom losses.
3. **Hard-stop exits bypass the LLM.** Stop loss, trailing stop, time-based exits fire deterministically. Use the LLM only for nuanced "should I take profit early?" calls.
4. **Shadow → live always.** New exit logic runs in `EXIT_MODE=shadow` for a full session before flipping to `live`. No exceptions.
5. **Sync / orchestrator loops must keep alive.** Wrap DB writes in try/finally. Swallow transient SQLite open failures with backoff. Never let a single exception crash a daemon thread.
6. **Filter parlay/multi-game Kalshi markets.** Drop tickers starting with `KXMVECROSSCATEGORY` or `KXMVESPORTSMULTIGAME`. Already implemented in `kalshi_client.is_parlay_spam()`.
7. **IPL series prefix is `KXIPL` (NOT `KXSAUDIPL`).** Use `series_ticker.startswith("KXIPL")` — the leading `KXSAUDI` of Saudi Pro League soccer correctly excludes itself. A naive `"ipl"` substring search would mistakenly include them.
8. **Verify deployed `.env` LLM model names match code defaults.** Once burned by `qwen/qwen2.5-72b` (no hyphen) vs `qwen/qwen-2.5-72b-instruct` (with hyphen). The code default is the hyphenated form.

## Workflow

1. **Plan first.** For non-trivial work (3+ files, new module, API contract change), enter plan mode and write what you'll change before touching code.
2. **Branch + PR.** `git checkout -b feat/something`, push, open a PR via `gh pr create`. Don't push directly to `main` for feature work.
3. **Tests required.** Every new module gets a corresponding `tests/test_*.py`. Mock external services (LLM, Kalshi, CricAPI). Run `python -m pytest` from `gully-engine/` before committing.
4. **Update README + the relevant doc** when you change anything observable: API endpoints, env vars, agent behavior, schema. The mandatory README update rule from `CLAUDE.md` applies.
5. **Verify against live data** when reasonable. The dashboard at http://localhost:8001 shows the full pipeline. For LLM agents, trigger `POST /api/orchestrator/run-entry` and check that `agent_logs` got a row.

## Don't do these

- Don't add a build step to the frontend. The design uses React 18 + Babel-via-CDN, and that no-build simplicity is intentional. If you need to import from npm, you're probably solving the wrong problem.
- Don't introduce new colors. Use the design tokens in [`gully-engine/static/styles.css`](gully-engine/static/styles.css). The `--saffron / --pitch / --crimson / --gold / --navy` palette is fixed.
- Don't commit `.env`. The repo's `.gitignore` already excludes it; double-check before staging.
- Don't put secrets in commit messages or PR descriptions.
- Don't skip the shadow-mode period for exit logic.

## Where things live

- API endpoints + lifespan: [`gully-engine/main.py`](gully-engine/main.py)
- LLM client (OpenRouter): [`gully-engine/llm.py`](gully-engine/llm.py)
- Scanner agent (implemented reference for new agents): [`gully-engine/agents/scanner.py`](gully-engine/agents/scanner.py)
- Kalshi event ↔ CricAPI match correlator: [`gully-engine/reconciler.py`](gully-engine/reconciler.py)
- Frontend entry: [`gully-engine/static/app.jsx`](gully-engine/static/app.jsx)
- Test fixtures pattern: [`gully-engine/tests/test_cricket_data.py`](gully-engine/tests/test_cricket_data.py) (HTTP mocking), [`gully-engine/tests/test_scanner.py`](gully-engine/tests/test_scanner.py) (LLM mocking)

## When in doubt

The handoff doc is the single source of truth for "what should I work on next?". Default to the highest-ranked open item in [docs/HANDOFF.md](docs/HANDOFF.md) unless the user redirects you.
