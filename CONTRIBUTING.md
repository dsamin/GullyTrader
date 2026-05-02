# Contributing

Quick guide for adding code to GullyTrader. For deeper context see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) and [docs/HANDOFF.md](docs/HANDOFF.md).

## Setup

```bash
git clone https://github.com/dsamin/GullyTrader.git
cd GullyTrader/gully-engine
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp ../../KalshiTrader/kalshi-engine/.env .env   # if you have it; otherwise cp .env.example .env
python -m pytest                                  # should be green
uvicorn main:app --reload --port 8001
```

## Branch + PR workflow

1. `git checkout -b feat/short-description` — branch from `main`
2. Write code + tests in the same commit (or one PR)
3. `python -m pytest` from `gully-engine/` — must be green before pushing
4. Update the relevant doc (README.md, the matching `docs/*.md`) in the same PR
5. `git push -u origin feat/short-description`
6. `gh pr create --title "..." --body "..."` — PR body includes a `## Test plan` checklist
7. Self-merge after review (no CI yet)

## Tests are required

Every new module gets a corresponding `tests/test_*.py`. External services are always mocked:

- HTTP (CricAPI, Kalshi): mock `requests.Session` with canned JSON per endpoint. See [`tests/test_cricket_data.py`](gully-engine/tests/test_cricket_data.py) for the canonical pattern.
- LLM (OpenRouter): patch `chat_json` to return a fake `LlmResponse`. See [`tests/test_scanner.py`](gully-engine/tests/test_scanner.py).

Live verification (booting uvicorn, hitting a real endpoint, watching `agent_logs`) is operational testing, not unit testing — both matter. See [docs/RUNBOOK.md#smoke-test-sequence](docs/RUNBOOK.md).

## Code style

- Python 3.11+ syntax (`X | None`, `match`, `dataclass(frozen=True)`)
- Type hints on every public function signature
- Module-level `log = logging.getLogger(__name__)`; use `log.warning` for recoverable issues, `log.exception` inside `except`
- Defensive over fail-fast for external services. Network errors, bad JSON, missing fields → log and return empty result, don't raise into the caller
- Constants in UPPER_CASE at module top
- Dataclasses for structured returns

For frontend (the `static/*.jsx` files):

- React 18 + Babel-via-CDN — **do not** add a build step
- Components use `Object.assign(window, {...})` at the bottom to register globally
- All design tokens come from CSS custom properties in [`styles.css`](gully-engine/static/styles.css). Don't hardcode colors.
- Mobile-first: design at 390×844; desktop is a stretch goal

## Commit messages

Follow the parent KalshiTrader's pattern — short imperative title, body explains the why:

```
Wire LLM scanner agent + Kalshi↔CricAPI reconciler

Scanner: prompts qwen-2.5-72b via OpenRouter to rank open IPL markets...
[2-3 paragraphs of context]

Co-Authored-By: ...
```

## Dependencies

`requirements.txt` is intentionally short. Before adding a dependency:
- Is it for a single function call you can write in 10 lines?
- Does it pull in a transitive dependency tree we don't want?
- Is it well-maintained as of the current year?

If yes-no-yes, add it. Otherwise inline the equivalent.

## Mandatory README updates

When you change anything observable — API endpoints, env vars, agent behavior, schema — you update [README.md](README.md) and the relevant doc in the same PR. This rule from [CLAUDE.md](CLAUDE.md) is non-negotiable.

## Security

- Never commit `.env`
- Never put secrets in commit messages or PR descriptions
- The `.gitignore` excludes `.env`, `.venv`, `*.db`, `*.log` — but verify `git status` before staging
- The Kalshi private key path in `.env` should point to a file outside the repo (the convention is `~/Projects/keys/<keyname>.txt`)

## Patterns to follow

When implementing a new LLM agent (researcher, decision, exit), use [`agents/scanner.py`](gully-engine/agents/scanner.py) as the template. It demonstrates:

- System + user prompt structure
- JSON-mode response parsing
- Hallucination filtering (drop tickers the LLM made up)
- Score/threshold filtering
- Fallback when the LLM is unreachable
- `agent_logs` audit trail (free via `llm.chat_json`)

When adding a new external data feed, copy [`cricket_data.CricApiFeed`](gully-engine/cricket_data.py)'s shape: protocol-conforming class, defensive HTTP layer, in-memory caching, factory wired in `get_feed()`.

When fixing a bug, the test for it goes in the same commit. The [`test_pnl.py`](gully-engine/tests/test_pnl.py) test docstrings ("the canonical scenario from KalshiTrader, 2026-03-02") are the model.
