# Honest Dashboard + Safety Fixes — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Strip frontend placeholders that lie, fix trailing-stop math correctness gap, and clean up DB hygiene (orphan positions + dead schema) — all on `feat/honest-dashboard-and-safety-fixes` branch.

**Architecture:** Four independent units (A frontend, C trailing-stop, D position hygiene, E dead schema). Build order: E → D → C → A. All migrations use the existing `_migrate()` try/except pattern at `database.py:182-199`. Tests follow TDD; each task lands in its own commit.

**Tech Stack:** Python 3.11+, FastAPI, SQLite (WAL mode), pytest, React 18 + Babel-via-CDN (no build).

**Reference:** Spec at `docs/superpowers/specs/2026-05-02-honest-dashboard-and-safety-fixes-design.md`.

**Working directory note:** Tests run from `gully-engine/` (`cd gully-engine && python -m pytest`). The conftest.py adds the package root to sys.path. Do NOT `cd` to repo root for pytest.

**Strict-auth note:** Spec Unit B was dropped — the kalshi_client.py:177-187 init guard and :510-519 prod guard ARE already landed and tested. Do NOT touch kalshi_client.py in this plan.

---

## Task 1: Unit E — Drop dead `markets` and `exit_decisions` tables

**Why:** Both tables defined in `database.py` schema have zero readers and zero writers (verified via grep). They're noise.

**Files:**
- Modify: `gully-engine/database.py:182-199` (extend `_migrate()`)
- Modify: `gully-engine/database.py:18-32` (remove `markets` from SCHEMA)
- Modify: `gully-engine/database.py:112-122` (remove `exit_decisions` from SCHEMA)
- Test: `gully-engine/tests/test_database_migrations.py` (NEW)

- [ ] **Step 1.1: Write the failing test**

Create `gully-engine/tests/test_database_migrations.py`:

```python
"""Tests for database migrations — table drops and orphan cleanup."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

import database


@pytest.fixture
def fresh_db(tmp_path: Path):
    """A fresh DB initialized with current schema + migrations."""
    db_path = tmp_path / "test.db"
    database.initialize(db_path)
    return db_path


@pytest.fixture
def legacy_db(tmp_path: Path):
    """A pre-migration DB with markets and exit_decisions tables present."""
    db_path = tmp_path / "legacy.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript("""
        CREATE TABLE markets (ticker TEXT PRIMARY KEY, event_ticker TEXT);
        CREATE TABLE exit_decisions (id INTEGER PRIMARY KEY, ticker TEXT);
    """)
    conn.close()
    return db_path


def _table_exists(db_path: Path, name: str) -> bool:
    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (name,),
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def test_fresh_db_does_not_create_dead_tables(fresh_db):
    """Fresh DB schema must not include markets or exit_decisions."""
    assert not _table_exists(fresh_db, "markets")
    assert not _table_exists(fresh_db, "exit_decisions")


def test_migration_drops_legacy_dead_tables(legacy_db):
    """Running initialize() against a legacy DB drops the dead tables."""
    assert _table_exists(legacy_db, "markets")
    assert _table_exists(legacy_db, "exit_decisions")

    database.initialize(legacy_db)

    assert not _table_exists(legacy_db, "markets")
    assert not _table_exists(legacy_db, "exit_decisions")
```

- [ ] **Step 1.2: Run test to verify it fails**

```bash
cd gully-engine && python -m pytest tests/test_database_migrations.py -v
```

Expected: FAIL — `test_fresh_db_does_not_create_dead_tables` fails because the SCHEMA still defines `markets` and `exit_decisions`.

- [ ] **Step 1.3: Remove `markets` table from SCHEMA**

In `gully-engine/database.py`, delete lines 18-32 (the `CREATE TABLE IF NOT EXISTS markets ...` block + its two indexes). Keep the surrounding `SCHEMA = """` literal intact.

The block to delete is:
```python
CREATE TABLE IF NOT EXISTS markets (
    ticker TEXT PRIMARY KEY,
    event_ticker TEXT NOT NULL,
    title TEXT,
    yes_price INTEGER,
    no_price INTEGER,
    status TEXT,
    close_time INTEGER,
    last_seen_at INTEGER,
    metadata_json TEXT
);

CREATE INDEX IF NOT EXISTS markets_event_idx ON markets(event_ticker);
CREATE INDEX IF NOT EXISTS markets_status_idx ON markets(status);

```

- [ ] **Step 1.4: Remove `exit_decisions` table from SCHEMA**

In the same file, delete lines 112-122 (the `CREATE TABLE IF NOT EXISTS exit_decisions ...` block):
```python
CREATE TABLE IF NOT EXISTS exit_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    trigger TEXT NOT NULL,             -- stop_loss | trailing_stop | time | llm | manual
    action TEXT NOT NULL,              -- hold | sell
    mode TEXT NOT NULL,                -- shadow | live
    mark_price_cents INTEGER,
    pnl_cents_at_decision INTEGER,
    note TEXT,
    created_at INTEGER NOT NULL
);

```

- [ ] **Step 1.5: Add migration drops to `_migrate()`**

In `gully-engine/database.py`, find the existing `_migrate()` block ending at line 199 with the `closed_market_cache` drop. Append:

```python
    # Phase 5: drop dead schema tables (markets, exit_decisions).
    # Both were scaffolded but never written to or read from outside CREATE.
    for dead_table in ("markets", "exit_decisions"):
        try:
            conn.execute(f"DROP TABLE IF EXISTS {dead_table}")
        except sqlite3.OperationalError:
            pass
```

- [ ] **Step 1.6: Run tests to verify pass**

```bash
cd gully-engine && python -m pytest tests/test_database_migrations.py -v
```

Expected: PASS — both tests green.

- [ ] **Step 1.7: Run full test suite to confirm no regressions**

```bash
cd gully-engine && python -m pytest
```

Expected: 145 passing → 147 passing. No failures.

- [ ] **Step 1.8: Commit**

```bash
git add gully-engine/database.py gully-engine/tests/test_database_migrations.py
git commit -m "$(cat <<'EOF'
Drop dead markets and exit_decisions tables

Both were defined in SCHEMA but never written to or read from outside
CREATE. Removed from SCHEMA + added DROP TABLE IF EXISTS to _migrate()
for legacy DBs. Tests verify fresh DB doesn't create them and legacy DB
gets cleaned.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Unit D1 — Skip writing flat positions in sync_service

**Why:** Kalshi's `list_positions()` returns markets with `yes_count + no_count == 0` for any ticker the user previously held but is now flat on. Writing those creates ghost rows. Filtering at the writer prevents accumulation.

**Files:**
- Modify: `gully-engine/sync_service.py:61-82` (extend `_upsert_position`)
- Test: `gully-engine/tests/test_sync_service.py` (add new test case)

- [ ] **Step 2.1: Write the failing test**

Append to `gully-engine/tests/test_sync_service.py` (after the existing tests):

```python
def test_upsert_position_skips_flat_positions(tmp_db):
    """Flat positions (yes_count + no_count == 0) must not be written.

    These come from Kalshi's API for tickers the user previously held but
    has since fully exited. Writing them creates ghost rows with no value.
    """
    import sqlite3
    from kalshi_client import KalshiPosition

    flat = KalshiPosition(
        ticker="KXIPL-25-FLAT",
        side="yes",
        yes_count=0,
        no_count=0,
        avg_cost_cents=0,
        market_exposure_cents=0,
    )

    conn = sqlite3.connect(str(tmp_db), isolation_level=None)
    try:
        sync_service._upsert_position(conn, flat)
        rows = conn.execute(
            "SELECT COUNT(*) FROM positions WHERE ticker = 'KXIPL-25-FLAT'"
        ).fetchone()
    finally:
        conn.close()

    assert rows[0] == 0, "flat position should not have been written"


def test_upsert_position_writes_real_positions(tmp_db):
    """Sanity: non-flat positions still get written."""
    import sqlite3
    from kalshi_client import KalshiPosition

    real = KalshiPosition(
        ticker="KXIPL-25-REAL",
        side="yes",
        yes_count=10,
        no_count=0,
        avg_cost_cents=45,
        market_exposure_cents=450,
    )

    conn = sqlite3.connect(str(tmp_db), isolation_level=None)
    try:
        sync_service._upsert_position(conn, real)
        rows = conn.execute(
            "SELECT COUNT(*) FROM positions WHERE ticker = 'KXIPL-25-REAL'"
        ).fetchone()
    finally:
        conn.close()

    assert rows[0] == 1, "real position should have been written"
```

- [ ] **Step 2.2: Run test to verify the flat-skip test fails**

```bash
cd gully-engine && python -m pytest tests/test_sync_service.py::test_upsert_position_skips_flat_positions -v
```

Expected: FAIL — assertion `rows[0] == 0` fails because the row IS written.

- [ ] **Step 2.3: Add filter at top of `_upsert_position`**

In `gully-engine/sync_service.py`, modify `_upsert_position` (line 61) to skip flat positions:

```python
def _upsert_position(conn: sqlite3.Connection, p: KalshiPosition) -> None:
    if p.yes_count + p.no_count == 0:
        # Flat: Kalshi reports this for tickers we previously held but
        # have since fully exited. Persisting these creates ghost rows
        # (28 such rows existed pre-Phase-5; cleaned via migration).
        return
    side = normalize_position_side(p.yes_count, p.no_count)
    conn.execute(
        """
        INSERT INTO positions (ticker, side, yes_count, no_count,
                               avg_cost_cents, market_exposure_cents,
                               opened_at, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'open')
        ON CONFLICT(ticker) DO UPDATE SET
            side=excluded.side,
            yes_count=excluded.yes_count,
            no_count=excluded.no_count,
            avg_cost_cents=excluded.avg_cost_cents,
            market_exposure_cents=excluded.market_exposure_cents
        """,
        (
            p.ticker, side if side != "flat" else "yes",
            p.yes_count, p.no_count,
            p.avg_cost_cents, p.market_exposure_cents,
            int(time.time()),
        ),
    )
```

- [ ] **Step 2.4: Run both new tests to verify pass**

```bash
cd gully-engine && python -m pytest tests/test_sync_service.py::test_upsert_position_skips_flat_positions tests/test_sync_service.py::test_upsert_position_writes_real_positions -v
```

Expected: PASS — both green.

- [ ] **Step 2.5: Run full sync_service tests to confirm no regressions**

```bash
cd gully-engine && python -m pytest tests/test_sync_service.py -v
```

Expected: all existing tests still PASS.

- [ ] **Step 2.6: Commit**

```bash
git add gully-engine/sync_service.py gully-engine/tests/test_sync_service.py
git commit -m "$(cat <<'EOF'
Skip writing flat positions in sync_service

Kalshi's list_positions() returns rows with yes_count + no_count == 0
for tickers the user previously held but has since fully exited. Persisting
these creates ghost rows with no value (28 such rows existed pre-cleanup).
Filter at the writer prevents future accumulation.

Cleanup of existing ghost rows is handled in a separate migration (Task 3).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Unit D2 — Migration to delete existing orphan positions

**Why:** Task 2 prevents new ghost rows; this cleans the 28 existing ones. Filter `realized_pnl_cents = 0` protects closed-with-pnl rows.

**Files:**
- Modify: `gully-engine/database.py:182-199` (extend `_migrate()`)
- Test: `gully-engine/tests/test_database_migrations.py` (add test)

- [ ] **Step 3.1: Write the failing test**

Append to `gully-engine/tests/test_database_migrations.py`:

```python
@pytest.fixture
def db_with_orphan_positions(tmp_path: Path):
    """Pre-migration DB with a mix of orphan, real, and closed positions."""
    db_path = tmp_path / "orphans.db"
    # Create with current schema first, then insert mixed rows.
    database.initialize(db_path)
    conn = sqlite3.connect(str(db_path), isolation_level=None)
    try:
        # Orphan: zero contracts, zero realized P&L → should be deleted
        conn.execute(
            "INSERT INTO positions (ticker, side, yes_count, no_count, "
            "avg_cost_cents, market_exposure_cents, realized_pnl_cents, "
            "opened_at, status) VALUES "
            "('KXIPL-ORPHAN', 'yes', 0, 0, 0, 0, 0, 1700000000, 'open')"
        )
        # Real open position → should survive
        conn.execute(
            "INSERT INTO positions (ticker, side, yes_count, no_count, "
            "avg_cost_cents, market_exposure_cents, realized_pnl_cents, "
            "opened_at, status) VALUES "
            "('KXIPL-REAL', 'yes', 10, 0, 45, 450, 0, 1700000000, 'open')"
        )
        # Closed with realized P&L → should survive (audit history)
        conn.execute(
            "INSERT INTO positions (ticker, side, yes_count, no_count, "
            "avg_cost_cents, market_exposure_cents, realized_pnl_cents, "
            "opened_at, closed_at, status) VALUES "
            "('KXIPL-CLOSED', 'yes', 0, 0, 45, 0, 550, "
            "1700000000, 1700001000, 'closed')"
        )
    finally:
        conn.close()
    return db_path


def test_migration_purges_orphan_positions_only(db_with_orphan_positions):
    """Orphan rows go; real and closed-with-pnl rows survive."""
    # Re-run initialize() to apply migration
    database.initialize(db_with_orphan_positions)

    conn = sqlite3.connect(str(db_with_orphan_positions))
    try:
        tickers = [
            r[0] for r in conn.execute(
                "SELECT ticker FROM positions ORDER BY ticker"
            ).fetchall()
        ]
    finally:
        conn.close()

    assert "KXIPL-ORPHAN" not in tickers, "orphan should have been purged"
    assert "KXIPL-REAL" in tickers, "real open position must survive"
    assert "KXIPL-CLOSED" in tickers, "closed-with-pnl must survive"
```

- [ ] **Step 3.2: Run test to verify it fails**

```bash
cd gully-engine && python -m pytest tests/test_database_migrations.py::test_migration_purges_orphan_positions_only -v
```

Expected: FAIL — orphan still in tickers list.

- [ ] **Step 3.3: Add purge migration to `_migrate()`**

In `gully-engine/database.py`, append to `_migrate()` after the dead-table drops from Task 1:

```python
    # Phase 5: one-time purge of orphan zero-contract zero-pnl positions.
    # These came from Kalshi's API for tickers the user is now flat on
    # (28 such rows pre-cleanup). The realized_pnl_cents=0 filter protects
    # closed-with-pnl rows that should be preserved as audit history.
    try:
        conn.execute(
            "DELETE FROM positions WHERE yes_count = 0 AND no_count = 0 "
            "AND realized_pnl_cents = 0"
        )
    except sqlite3.OperationalError:
        pass
```

- [ ] **Step 3.4: Run test to verify pass**

```bash
cd gully-engine && python -m pytest tests/test_database_migrations.py -v
```

Expected: PASS — all migration tests green.

- [ ] **Step 3.5: Run full test suite**

```bash
cd gully-engine && python -m pytest
```

Expected: 147 → ~148 passing. No failures.

- [ ] **Step 3.6: Commit**

```bash
git add gully-engine/database.py gully-engine/tests/test_database_migrations.py
git commit -m "$(cat <<'EOF'
Purge orphan zero-contract positions on migration

Cleans up the 28 existing ghost rows in production DB
(yes_count=0, no_count=0, realized_pnl_cents=0) that accumulated before
the Task 2 writer-side filter landed. Filter on realized_pnl_cents=0
protects closed-with-pnl rows preserved as audit history.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Unit C1 — Add `peak_pnl_cents` column to `positions`

**Why:** Trailing-stop logic in `exit_monitor.py:79-89` reads `peak_pnl_cents` to decide if we've given back >20% from peak. Currently the orchestrator passes `peak_pnl_cents=0` for every position, so trailing-stop never fires. Need a real DB-backed value.

**Files:**
- Modify: `gully-engine/database.py:34-49` (SCHEMA `positions` definition)
- Modify: `gully-engine/database.py:182-199` (extend `_migrate()` with ALTER)
- Test: `gully-engine/tests/test_database_migrations.py` (add test)

- [ ] **Step 4.1: Write the failing test**

Append to `gully-engine/tests/test_database_migrations.py`:

```python
def test_positions_table_has_peak_pnl_cents_column(fresh_db):
    """Schema must define peak_pnl_cents column with default 0."""
    conn = sqlite3.connect(str(fresh_db))
    try:
        cols = {
            row[1]: row[4]  # name → default value
            for row in conn.execute("PRAGMA table_info(positions)").fetchall()
        }
    finally:
        conn.close()

    assert "peak_pnl_cents" in cols, "positions must have peak_pnl_cents column"
    assert cols["peak_pnl_cents"] == "0", "default must be 0"


def test_migration_adds_peak_pnl_cents_to_legacy_db(tmp_path: Path):
    """A pre-Phase-5 DB without peak_pnl_cents gains the column on init."""
    db_path = tmp_path / "legacy_positions.db"
    conn = sqlite3.connect(str(db_path))
    try:
        # Build legacy positions table with no peak_pnl_cents column
        conn.executescript("""
            CREATE TABLE positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker TEXT NOT NULL,
                side TEXT NOT NULL,
                yes_count INTEGER NOT NULL DEFAULT 0,
                no_count INTEGER NOT NULL DEFAULT 0,
                realized_pnl_cents INTEGER NOT NULL DEFAULT 0,
                opened_at INTEGER,
                status TEXT NOT NULL DEFAULT 'open',
                UNIQUE(ticker)
            );
        """)
    finally:
        conn.close()

    database.initialize(db_path)

    conn = sqlite3.connect(str(db_path))
    try:
        cols = {
            row[1] for row in conn.execute("PRAGMA table_info(positions)").fetchall()
        }
    finally:
        conn.close()

    assert "peak_pnl_cents" in cols
```

- [ ] **Step 4.2: Run tests to verify they fail**

```bash
cd gully-engine && python -m pytest tests/test_database_migrations.py::test_positions_table_has_peak_pnl_cents_column tests/test_database_migrations.py::test_migration_adds_peak_pnl_cents_to_legacy_db -v
```

Expected: FAIL — column doesn't exist.

- [ ] **Step 4.3: Add `peak_pnl_cents` to SCHEMA**

In `gully-engine/database.py`, modify the `positions` table definition (line 34-49). Add `peak_pnl_cents` after `unrealized_pnl_cents`:

```python
CREATE TABLE IF NOT EXISTS positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    side TEXT NOT NULL,                -- 'yes' | 'no'
    yes_count INTEGER NOT NULL DEFAULT 0,
    no_count INTEGER NOT NULL DEFAULT 0,
    entry_price INTEGER,               -- cents (1-99)
    avg_cost_cents INTEGER,
    market_exposure_cents INTEGER,
    realized_pnl_cents INTEGER NOT NULL DEFAULT 0,
    unrealized_pnl_cents INTEGER NOT NULL DEFAULT 0,
    peak_pnl_cents INTEGER NOT NULL DEFAULT 0,
    opened_at INTEGER,
    closed_at INTEGER,
    status TEXT NOT NULL DEFAULT 'open',
    UNIQUE(ticker)
);
```

- [ ] **Step 4.4: Add ALTER to `_migrate()` for legacy DBs**

In `gully-engine/database.py`, the existing `additions` list at line 176-181 already follows the pattern. Add a new entry:

```python
    additions = [
        ("fills", "kalshi_trade_id", "TEXT"),
        ("fills", "kalshi_order_id", "TEXT"),
        ("fills", "action", "TEXT"),
        ("fills", "is_taker", "INTEGER DEFAULT 0"),
        ("positions", "peak_pnl_cents", "INTEGER NOT NULL DEFAULT 0"),
    ]
```

- [ ] **Step 4.5: Run tests to verify pass**

```bash
cd gully-engine && python -m pytest tests/test_database_migrations.py -v
```

Expected: PASS — all migration tests green.

- [ ] **Step 4.6: Run full test suite**

```bash
cd gully-engine && python -m pytest
```

Expected: ~148 → ~150 passing. No failures.

- [ ] **Step 4.7: Commit**

```bash
git add gully-engine/database.py gully-engine/tests/test_database_migrations.py
git commit -m "$(cat <<'EOF'
Add peak_pnl_cents column to positions table

Trailing-stop logic in exit_monitor.evaluate() needs per-position peak P&L
to decide if we've given back >20% from the high. Currently the orchestrator
hardcodes peak_pnl_cents=0 for every position, so trailing-stop never fires.

Schema add + ALTER migration for legacy DBs. Writer (Task 5) and reader
(Task 6) follow.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Unit C2 — sync_service writes `peak_pnl_cents` on every sync

**Why:** Peak only ever rises. Every sync compares current unrealized P&L vs stored peak and bumps if higher.

**Files:**
- Modify: `gully-engine/sync_service.py:61-82` (extend `_upsert_position`)
- Test: `gully-engine/tests/test_sync_service.py` (add test)

- [ ] **Step 5.1: Write the failing test**

Append to `gully-engine/tests/test_sync_service.py`:

```python
def test_upsert_position_tracks_peak_pnl_monotonically(tmp_db):
    """peak_pnl_cents only ever rises across syncs.

    On first insert: peak = current unrealized P&L (or 0 if negative).
    On subsequent updates: peak = MAX(stored peak, current).
    """
    import sqlite3
    from kalshi_client import KalshiPosition

    # First sync: yes_count=10, avg_cost=45, exposure=550 → unrealized = 550 - (10*45) = 100
    p1 = KalshiPosition(
        ticker="KXIPL-PEAK", side="yes",
        yes_count=10, no_count=0,
        avg_cost_cents=45, market_exposure_cents=550,
    )
    conn = sqlite3.connect(str(tmp_db), isolation_level=None)
    try:
        sync_service._upsert_position(conn, p1)
        peak1 = conn.execute(
            "SELECT peak_pnl_cents FROM positions WHERE ticker = 'KXIPL-PEAK'"
        ).fetchone()[0]
    finally:
        conn.close()
    assert peak1 == 100, f"expected peak 100 after first sync, got {peak1}"

    # Second sync: exposure dropped to 480 → unrealized = 480 - 450 = 30 (lower than peak)
    p2 = KalshiPosition(
        ticker="KXIPL-PEAK", side="yes",
        yes_count=10, no_count=0,
        avg_cost_cents=45, market_exposure_cents=480,
    )
    conn = sqlite3.connect(str(tmp_db), isolation_level=None)
    try:
        sync_service._upsert_position(conn, p2)
        peak2 = conn.execute(
            "SELECT peak_pnl_cents FROM positions WHERE ticker = 'KXIPL-PEAK'"
        ).fetchone()[0]
    finally:
        conn.close()
    assert peak2 == 100, f"peak must not decrease, got {peak2}"

    # Third sync: exposure rose to 700 → unrealized = 700 - 450 = 250 (new high)
    p3 = KalshiPosition(
        ticker="KXIPL-PEAK", side="yes",
        yes_count=10, no_count=0,
        avg_cost_cents=45, market_exposure_cents=700,
    )
    conn = sqlite3.connect(str(tmp_db), isolation_level=None)
    try:
        sync_service._upsert_position(conn, p3)
        peak3 = conn.execute(
            "SELECT peak_pnl_cents FROM positions WHERE ticker = 'KXIPL-PEAK'"
        ).fetchone()[0]
    finally:
        conn.close()
    assert peak3 == 250, f"expected new peak 250, got {peak3}"


def test_upsert_position_negative_unrealized_keeps_peak_at_zero(tmp_db):
    """If a position is underwater from the start, peak stays at 0."""
    import sqlite3
    from kalshi_client import KalshiPosition

    # Underwater: cost 450, exposure 300 → unrealized = -150
    underwater = KalshiPosition(
        ticker="KXIPL-DOWN", side="yes",
        yes_count=10, no_count=0,
        avg_cost_cents=45, market_exposure_cents=300,
    )
    conn = sqlite3.connect(str(tmp_db), isolation_level=None)
    try:
        sync_service._upsert_position(conn, underwater)
        peak = conn.execute(
            "SELECT peak_pnl_cents FROM positions WHERE ticker = 'KXIPL-DOWN'"
        ).fetchone()[0]
    finally:
        conn.close()
    assert peak == 0, f"peak should clamp to 0 for negative unrealized, got {peak}"
```

- [ ] **Step 5.2: Run test to verify it fails**

```bash
cd gully-engine && python -m pytest tests/test_sync_service.py::test_upsert_position_tracks_peak_pnl_monotonically -v
```

Expected: FAIL — peak is always 0 (default value).

- [ ] **Step 5.3: Update `_upsert_position` to track peak**

In `gully-engine/sync_service.py`, modify `_upsert_position` to compute current unrealized P&L and update peak. Replace the function body (after the flat-skip filter from Task 2) with:

```python
def _upsert_position(conn: sqlite3.Connection, p: KalshiPosition) -> None:
    if p.yes_count + p.no_count == 0:
        return
    side = normalize_position_side(p.yes_count, p.no_count)
    # Current unrealized P&L: current market value minus cost basis.
    # market_exposure_cents is the live mark-to-market value; avg_cost_cents
    # is per-contract cost. Total cost = avg_cost × max(yes,no) (one of them
    # is non-zero for a directional position).
    contracts = max(p.yes_count, p.no_count)
    cost_basis = p.avg_cost_cents * contracts
    unrealized = p.market_exposure_cents - cost_basis
    # Peak only rises. Clamp negative unrealized to 0 — peak represents
    # high-water mark, never goes below zero.
    new_peak = max(0, unrealized)
    conn.execute(
        """
        INSERT INTO positions (ticker, side, yes_count, no_count,
                               avg_cost_cents, market_exposure_cents,
                               unrealized_pnl_cents, peak_pnl_cents,
                               opened_at, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'open')
        ON CONFLICT(ticker) DO UPDATE SET
            side=excluded.side,
            yes_count=excluded.yes_count,
            no_count=excluded.no_count,
            avg_cost_cents=excluded.avg_cost_cents,
            market_exposure_cents=excluded.market_exposure_cents,
            unrealized_pnl_cents=excluded.unrealized_pnl_cents,
            peak_pnl_cents=MAX(positions.peak_pnl_cents, excluded.peak_pnl_cents)
        """,
        (
            p.ticker, side if side != "flat" else "yes",
            p.yes_count, p.no_count,
            p.avg_cost_cents, p.market_exposure_cents,
            unrealized, new_peak,
            int(time.time()),
        ),
    )
```

- [ ] **Step 5.4: Run new tests to verify pass**

```bash
cd gully-engine && python -m pytest tests/test_sync_service.py::test_upsert_position_tracks_peak_pnl_monotonically tests/test_sync_service.py::test_upsert_position_negative_unrealized_keeps_peak_at_zero -v
```

Expected: PASS — both green.

- [ ] **Step 5.5: Run full sync_service tests + full suite**

```bash
cd gully-engine && python -m pytest tests/test_sync_service.py -v
cd gully-engine && python -m pytest
```

Expected: all green.

- [ ] **Step 5.6: Commit**

```bash
git add gully-engine/sync_service.py gully-engine/tests/test_sync_service.py
git commit -m "$(cat <<'EOF'
Track peak_pnl_cents per position on every sync

Computes current unrealized P&L (market_exposure - cost basis), clamps
negative to 0, and writes MAX(stored peak, current) via SQL on conflict.
Peak only ever rises — required input for trailing-stop logic.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Unit C3 — Orchestrator reads real `opened_at` + `peak_pnl_cents`

**Why:** Replace the hardcoded `opened_at=now-600, peak_pnl_cents=0` in orchestrator.py:178-179 with real values from the positions DB row. This makes time-stop and trailing-stop actually fire correctly.

**Files:**
- Modify: `gully-engine/orchestrator.py:155-200` (`run_exit_monitor_once`)
- Test: `gully-engine/tests/test_orchestrator.py` (add tests)

- [ ] **Step 6.1: Read the test file to find a good insertion point**

```bash
grep -n "def test_" gully-engine/tests/test_orchestrator.py | head -20
```

Note the existing structure — match the style of existing tests (mocking pattern, fixtures used).

- [ ] **Step 6.2: Write the failing test**

Append to `gully-engine/tests/test_orchestrator.py`:

```python
def test_run_exit_monitor_uses_real_opened_at_from_db(tmp_path, monkeypatch):
    """Orchestrator must read opened_at from positions table, not fake it.

    Seeds a position with opened_at far in the past, then verifies the
    PositionSnapshot passed to exit_monitor.evaluate reflects that real
    timestamp (not now-600).
    """
    import sqlite3
    import time
    from unittest.mock import MagicMock, patch

    import database
    import orchestrator
    from kalshi_client import KalshiPosition, KalshiMarket
    from settings import settings as _settings

    # Point settings.db_path at a tmp file
    db_path = tmp_path / "exit.db"
    original_path = _settings.db_path
    object.__setattr__(_settings, "db_path", db_path)
    try:
        database.initialize(db_path)

        # Seed a position with opened_at = 2 hours ago
        old_opened_at = int(time.time()) - 7200
        conn = sqlite3.connect(str(db_path), isolation_level=None)
        try:
            conn.execute(
                "INSERT INTO positions (ticker, side, yes_count, no_count, "
                "avg_cost_cents, market_exposure_cents, "
                "peak_pnl_cents, opened_at, status) VALUES "
                "('KXIPL-OLD', 'yes', 10, 0, 45, 480, 200, ?, 'open')",
                (old_opened_at,),
            )
        finally:
            conn.close()

        # Stub Kalshi: returns the position; mark_price = avg_cost (zero P&L)
        fake_client = MagicMock()
        fake_client.list_positions.return_value = [
            KalshiPosition(
                ticker="KXIPL-OLD", side="yes",
                yes_count=10, no_count=0,
                avg_cost_cents=45, market_exposure_cents=480,
            )
        ]
        fake_client.get_market.return_value = KalshiMarket(
            ticker="KXIPL-OLD", event_ticker="KXIPL-25", title="t",
            yes_price=48, no_price=52, status="open", close_time="",
        )
        # Capture PositionSnapshot passed to evaluate
        captured = []
        def fake_evaluate(snap, **kw):
            captured.append(snap)
            from exit_monitor import ExitDecision
            return ExitDecision(ticker=snap.ticker, action="hold",
                                trigger="none", note="test")

        with patch("orchestrator.KalshiClient", return_value=fake_client), \
             patch("orchestrator.evaluate", side_effect=fake_evaluate):
            orchestrator.run_exit_monitor_once(force=True)

        assert len(captured) == 1
        assert captured[0].opened_at == old_opened_at, \
            f"expected real opened_at {old_opened_at}, got {captured[0].opened_at}"
        assert captured[0].peak_pnl_cents == 200, \
            f"expected stored peak 200, got {captured[0].peak_pnl_cents}"
    finally:
        object.__setattr__(_settings, "db_path", original_path)


def test_run_exit_monitor_skips_position_missing_from_db(tmp_path, caplog):
    """If Kalshi reports a position not yet in our DB (race during first sync),
    orchestrator must skip it gracefully — log a warning, don't crash."""
    import logging
    from unittest.mock import MagicMock, patch

    import database
    import orchestrator
    from kalshi_client import KalshiPosition, KalshiMarket
    from settings import settings as _settings

    db_path = tmp_path / "race.db"
    original_path = _settings.db_path
    object.__setattr__(_settings, "db_path", db_path)
    try:
        database.initialize(db_path)
        # Note: no INSERT — DB has no positions row for KXIPL-NEW

        fake_client = MagicMock()
        fake_client.list_positions.return_value = [
            KalshiPosition(
                ticker="KXIPL-NEW", side="yes",
                yes_count=5, no_count=0,
                avg_cost_cents=50, market_exposure_cents=250,
            )
        ]
        fake_client.get_market.return_value = KalshiMarket(
            ticker="KXIPL-NEW", event_ticker="KXIPL-25", title="t",
            yes_price=50, no_price=50, status="open", close_time="",
        )

        def fake_evaluate(snap, **kw):
            raise AssertionError("evaluate should not be called for missing-row position")

        with patch("orchestrator.KalshiClient", return_value=fake_client), \
             patch("orchestrator.evaluate", side_effect=fake_evaluate), \
             caplog.at_level(logging.WARNING):
            result = orchestrator.run_exit_monitor_once(force=True)

        # No crash + warning logged
        assert any("KXIPL-NEW" in rec.message for rec in caplog.records), \
            "expected warning about missing position row"
    finally:
        object.__setattr__(_settings, "db_path", original_path)
```

- [ ] **Step 6.3: Run tests to verify they fail**

```bash
cd gully-engine && python -m pytest tests/test_orchestrator.py::test_run_exit_monitor_uses_real_opened_at_from_db tests/test_orchestrator.py::test_run_exit_monitor_skips_position_missing_from_db -v
```

Expected: FAIL — captured opened_at is now-600 not the seeded value; missing-row test fails because evaluate IS called.

- [ ] **Step 6.4: Add `force` parameter to `run_exit_monitor_once`**

Looking at orchestrator.py:156, the signature is `def run_exit_monitor_once(*, force: bool = False)`. Verify it exists; if it does not, the test seeds need adjustment. Read the actual signature:

```bash
grep -n "def run_exit_monitor_once" gully-engine/orchestrator.py
```

If `force` isn't a parameter, change the test calls to drop `force=True` and instead release the lock manually in the test setup.

- [ ] **Step 6.5: Update `run_exit_monitor_once` to read from DB**

In `gully-engine/orchestrator.py`, modify the loop in `run_exit_monitor_once` (around lines 156-200). Replace the `PositionSnapshot` construction block:

```python
def run_exit_monitor_once(*, force: bool = False) -> dict:
    """Evaluate every open position once."""
    if not _exit_lock.acquire(blocking=False):
        return {"status": "skipped", "reason": "already_running"}
    try:
        client = KalshiClient()
        positions = client.list_positions()
        decisions = []
        now = int(time.time())
        # Read opened_at + peak_pnl_cents from DB once per tick.
        with database.write_conn() as conn:
            db_state = {
                row["ticker"]: (row["opened_at"], row["peak_pnl_cents"])
                for row in conn.execute(
                    "SELECT ticker, opened_at, peak_pnl_cents FROM positions "
                    "WHERE status = 'open'"
                ).fetchall()
            }
        for p in positions:
            if p.yes_count + p.no_count == 0:
                continue   # flat — sync filter handles this too, defense-in-depth
            if p.ticker not in db_state:
                log.warning(
                    "exit_monitor: no DB row for %s yet (race with sync); "
                    "skipping this tick", p.ticker,
                )
                continue
            opened_at, peak_pnl_cents = db_state[p.ticker]
            side = "yes" if p.yes_count >= p.no_count else "no"
            market = client.get_market(p.ticker)
            if market is not None:
                mark = market.yes_price if side == "yes" else market.no_price
            else:
                mark = p.avg_cost_cents
            snap = PositionSnapshot(
                ticker=p.ticker,
                entry_price_cents=p.avg_cost_cents,
                mark_price_cents=mark,
                yes_count=p.yes_count, no_count=p.no_count,
                side=side,
                opened_at=opened_at or now,            # fallback: row exists but opened_at NULL
                peak_pnl_cents=peak_pnl_cents or 0,
            )
            exit_dec = evaluate(snap, now=now)
            _log_decision(
                agent="exit",
                ticker=exit_dec.ticker,
                decision=exit_dec.action,
                reasoning=f"{exit_dec.trigger}: {exit_dec.note}",
            )
            order_resp = None
            if exit_dec.action == "sell" and settings.exit_mode == "live":
                try:
                    order_resp = client.place_limit_order(
                        ticker=p.ticker, side=side, action="sell",
                        count=max(p.yes_count, p.no_count),
                        limit_price_cents=max(1, mark - 1),
                    )
                except Exception as exc:
                    log.warning("exit_monitor place_order failed for %s: %s", p.ticker, exc)
            decisions.append({
                "ticker": exit_dec.ticker,
                "action": exit_dec.action,
                "trigger": exit_dec.trigger,
                "order": order_resp,
            })
        return {"status": "ok", "decisions": decisions}
    finally:
        _exit_lock.release()
```

Also add `import database` at the top of `orchestrator.py` if it's not already there:

```bash
grep -n "^import database" gully-engine/orchestrator.py
```

If missing, add it near the other imports.

- [ ] **Step 6.6: Run new orchestrator tests**

```bash
cd gully-engine && python -m pytest tests/test_orchestrator.py::test_run_exit_monitor_uses_real_opened_at_from_db tests/test_orchestrator.py::test_run_exit_monitor_skips_position_missing_from_db -v
```

Expected: PASS — both green.

- [ ] **Step 6.7: Run full orchestrator + full suite tests**

```bash
cd gully-engine && python -m pytest tests/test_orchestrator.py -v
cd gully-engine && python -m pytest
```

Expected: ~150 → ~152 passing. No regressions.

- [ ] **Step 6.8: Commit**

```bash
git add gully-engine/orchestrator.py gully-engine/tests/test_orchestrator.py
git commit -m "$(cat <<'EOF'
Read real opened_at + peak_pnl_cents from DB in exit monitor

Replaces hardcoded opened_at=now-600 and peak_pnl_cents=0 in
run_exit_monitor_once with a SELECT from the positions table. Time-stop
and trailing-stop now fire correctly based on real position state.

Race handling: if Kalshi reports a position not yet in our DB (first
sync after a fresh fill), log a warning and skip that ticker for the
tick. Sync catches up next pass.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Unit A1 — Remove iPhone status bar

**Why:** Fake "9:41" time + battery + signal bars on a web-rendered dashboard pretends to be iOS. The user explicitly called this out.

**Files:**
- Modify: `gully-engine/static/primitives.jsx` (delete StatusBar component + registration)
- Modify: `gully-engine/static/app.jsx:185` (remove `<StatusBar/>`)

- [ ] **Step 7.1: Delete the StatusBar component definition**

In `gully-engine/static/primitives.jsx`, delete lines 3-21 (the entire `const StatusBar = ...` declaration including the closing `);`).

- [ ] **Step 7.2: Remove StatusBar from window registration**

In `gully-engine/static/primitives.jsx:127`, change:
```jsx
Object.assign(window, { StatusBar, TeamCrest, Crest, TEAMS, Chip, LiveChip, TabBar, Avatar, Delta });
```
to:
```jsx
Object.assign(window, { TeamCrest, Crest, TEAMS, Chip, LiveChip, TabBar, Avatar, Delta });
```

- [ ] **Step 7.3: Remove the render in app.jsx**

In `gully-engine/static/app.jsx`, find line 185 (`<StatusBar/>`) and delete that line.

- [ ] **Step 7.4: Verify no other references**

```bash
grep -rn "StatusBar" gully-engine/static/
```

Expected: zero matches. If any remain, delete them.

- [ ] **Step 7.5: Run test suite (no JS tests, but Python tests must still pass)**

```bash
cd gully-engine && python -m pytest
```

Expected: all green.

- [ ] **Step 7.6: Commit**

```bash
git add gully-engine/static/primitives.jsx gully-engine/static/app.jsx
git commit -m "$(cat <<'EOF'
Remove fake iPhone status bar from dashboard chrome

The StatusBar component faked iOS chrome (9:41 timestamp, signal bars,
battery icon) on a web-rendered dashboard. It pretended to be a mobile
OS surface that GullyTrader is not. Removed from primitives.jsx,
app.jsx, and the window registration line.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Unit A2 — Hide trends panels with no real data

**Why:** Trends screen renders 5 panels of fake data (Manhattan chart fallback, last-12-balls fallback, head-to-head, form guide, pitch & weather). Per spec decision: hide rather than show fakes or empty states.

**Files:**
- Modify: `gully-engine/static/screen-trends.jsx` (multiple sections)

- [ ] **Step 8.1: Read the current file to understand structure**

Read `gully-engine/static/screen-trends.jsx` in full.

- [ ] **Step 8.2: Remove hardcoded array fallbacks**

At the top of the component (around lines 4-9), remove the hardcoded fallback arrays. Change:
```jsx
const runs = (live?.over_runs || [8, 12, 4, 16, 9, 18, 7, 11, 14, 6, 10, 13, 17, 9, 8, 12]);
const wickets = (live?.wickets || [3, 7, 12]);
// ...
const recent = (live?.last_balls || ['1','4','0','6','2','1','0','4','1','2','6','1']);
```
to:
```jsx
const runs = live?.over_runs || [];
const wickets = live?.wickets || [];
// ...
const recent = live?.last_balls || [];
```

(Adjust to match actual variable names in the file.)

- [ ] **Step 8.3: Conditionally render Manhattan chart**

Wrap the Manhattan chart's JSX block with a guard. Change:
```jsx
<ManhattanChart runs={runs} wickets={wickets} />
```
to:
```jsx
{runs.length > 0 && <ManhattanChart runs={runs} wickets={wickets} />}
```

- [ ] **Step 8.4: Conditionally render last-12-balls strip**

Wrap with `{recent.length > 0 && (...)}`. The exact JSX to wrap will be the `<div>` containing the recent-balls badges.

- [ ] **Step 8.5: Delete the Head-to-head card entirely**

Find and delete the entire JSX block that renders the H2H "wins" card (around lines 82-95 per the audit). Look for `<div className="display"...>3</div>` and `<div className="display"...>2</div>` — that's the giveaway. Delete the whole card container.

- [ ] **Step 8.6: Delete the Form guide card entirely**

Find and delete the JSX block that renders form arrays like `['W','W','L','W','W']`. The whole "Form" card container goes.

- [ ] **Step 8.7: Delete the Pitch & weather card entirely**

Find and delete the card containing "Batting · Avg 1st-inn 184" and "28°C · Humid · Dew @ 19:00". Whole card container.

- [ ] **Step 8.8: Verify nothing references the deleted variables**

```bash
grep -n "head_to_head\|form_guide\|pitch\|weather" gully-engine/static/screen-trends.jsx
```

Expected: no matches in active code (comments OK).

- [ ] **Step 8.9: Manual smoke test (post-execution gate)**

Note: this is a manual step deferred to the verification phase. Boot uvicorn, navigate to Trends with no live match, verify the deleted panels are gone and remaining content (live scoreboard area) renders cleanly.

- [ ] **Step 8.10: Commit**

```bash
git add gully-engine/static/screen-trends.jsx
git commit -m "$(cat <<'EOF'
Hide trends panels that have no real data source

Removed hardcoded fallback arrays for Manhattan chart and last-12-balls;
panels now skip rendering when data is empty. Deleted entire head-to-head,
form guide, and pitch & weather cards — all rendered fake data on every
page load. Future re-introduction requires real /api endpoints.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: Unit A3 — Remove dead Notify + Set-autotrade buttons

**Why:** `screen-standings.jsx:149-150` has two buttons with no onClick handlers. Per spec: remove rather than disable.

**Files:**
- Modify: `gully-engine/static/screen-standings.jsx:149-150`

- [ ] **Step 9.1: Delete both button lines**

In `gully-engine/static/screen-standings.jsx`, delete lines 149-150:
```jsx
<button className="btn btn-secondary" style={{ flex: 1, padding: '8px', fontSize: 11 }}>🔔 Notify</button>
<button className="btn btn-primary" style={{ flex: 1, padding: '8px', fontSize: 11 }}>Set autotrade</button>
```

- [ ] **Step 9.2: Check container layout**

Look at the parent `<div>` that contained the buttons (likely a `display: flex` row). If the row is now empty, delete the parent container too. If the parent had other children, no change needed.

- [ ] **Step 9.3: Run test suite**

```bash
cd gully-engine && python -m pytest
```

Expected: all green (no JS test impact).

- [ ] **Step 9.4: Commit**

```bash
git add gully-engine/static/screen-standings.jsx
git commit -m "$(cat <<'EOF'
Remove dead Notify and Set-autotrade buttons from standings

Both buttons had no onClick handlers — clicking did nothing. Removed
rather than disabled per spec ("disabled UI implies coming next sprint;
neither is on the roadmap").

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: Unit A4 — Cricket-charts neutral defaults

**Why:** `cricket-charts.jsx:196-202` has `Scoreboard` defaults like `teamA="MUM", runsA=142, venue="Wankhede · 19:30 IST"`. Always overridden in production, but a defensive change in case they ever leak.

**Files:**
- Modify: `gully-engine/static/cricket-charts.jsx:196-202`

- [ ] **Step 10.1: Replace defaults with neutral placeholders**

In `gully-engine/static/cricket-charts.jsx`, find the Scoreboard component definition and change:
```jsx
const Scoreboard = ({ teamA = "MUM", teamB = "CHE",
                      runsA = 142, wicketsA = 4, oversA = "15.2",
                      runsB = 178, wicketsB = 6, oversB = "20.0",
                      status = "MUM need 36 in 28",
                      live = true, glow = true,
                      venue = "Wankhede · 19:30 IST",
                      innings = "2nd Innings · T20" }) => {
```
to:
```jsx
const Scoreboard = ({ teamA = "—", teamB = "—",
                      runsA = 0, wicketsA = 0, oversA = "0.0",
                      runsB = 0, wicketsB = 0, oversB = "0.0",
                      status = "",
                      live = false, glow = false,
                      venue = "",
                      innings = "" }) => {
```

- [ ] **Step 10.2: Run test suite**

```bash
cd gully-engine && python -m pytest
```

Expected: all green.

- [ ] **Step 10.3: Commit**

```bash
git add gully-engine/static/cricket-charts.jsx
git commit -m "$(cat <<'EOF'
Use neutral defaults in Scoreboard component

Defaults were always overridden by screen-match.jsx in production, but
the fake values (MUM 142/4 vs CHE 178/6 at Wankhede) would have been
visually misleading if any default ever leaked through. Use 0/em-dashes
instead.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 11: Update README + docs/*.md per CLAUDE.md mandate

**Why:** CLAUDE.md mandates README + relevant docs updates in the same PR for any logic/schema/config change. This branch touches schema (Tasks 1, 3, 4), sync writer (2, 5), orchestrator (6), and frontend (7-10).

**Files:**
- Modify: `README.md` (current state section, schema notes)
- Modify: `docs/HANDOFF.md` (Phase 5 cleanup entry, ranked-next list update)
- Modify: `docs/ARCHITECTURE.md` (positions table schema note + dropped-tables note)

- [ ] **Step 11.1: Read current docs to understand format**

```bash
head -80 README.md
head -80 docs/HANDOFF.md
head -80 docs/ARCHITECTURE.md
```

Match the existing voice and structure of each.

- [ ] **Step 11.2: Update README.md**

Add a "Phase 5 cleanup (2026-05-02)" entry to whatever "recent changes" or "current state" section exists. Mention:
- Honest dashboard: removed fake iPhone chrome, hidden trends panels with no real data, removed dead standings buttons
- Trailing-stop fix: orchestrator now uses real opened_at + peak_pnl_cents
- DB hygiene: dropped markets and exit_decisions tables, purged orphan positions

If no such section exists, add it under a "## Recent changes" heading near the top.

- [ ] **Step 11.3: Update docs/HANDOFF.md**

Add a Phase 5 entry to the "what's done" section. Update the "ranked next-step list" if any of the items addressed by this branch were on it (e.g., orphan positions cleanup, trailing-stop accuracy). Remove anything completed.

- [ ] **Step 11.4: Update docs/ARCHITECTURE.md**

Update the schema section to reflect:
- `markets` and `exit_decisions` tables removed (note in a "removed" subsection)
- `positions.peak_pnl_cents` column added
- Note in the trailing-stop description that it now reads peak from DB

- [ ] **Step 11.5: Commit**

```bash
git add README.md docs/HANDOFF.md docs/ARCHITECTURE.md
git commit -m "$(cat <<'EOF'
Docs: Phase 5 honest-dashboard + safety-fixes update

README: Phase 5 entry summarizing branch scope.
HANDOFF: phase entry + ranked-next list cleanup.
ARCHITECTURE: schema note (markets/exit_decisions dropped, peak_pnl_cents
added) + trailing-stop description updated.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 12: Final verification + manual smoke + open PR

**Why:** Before merging, prove everything works end-to-end.

- [ ] **Step 12.1: Run full test suite from scratch**

```bash
cd gully-engine && python -m pytest -v
```

Expected: ~155 tests passing (145 baseline + ~10 new). Zero failures.

- [ ] **Step 12.2: Manual smoke — boot uvicorn**

```bash
cd gully-engine && uvicorn main:app --reload --port 8001
```

Open `http://localhost:8001/` in browser. Verify:
- No iPhone status bar (no "9:41", no battery icon)
- Dashboard loads
- Navigate to Trends — only live scoreboard area visible (no fake H2H, no fake form guide, no fake pitch/weather)
- Navigate to Standings — no Notify or Set-autotrade buttons

- [ ] **Step 12.3: Verify DB state post-migrations**

```bash
sqlite3 gully-engine/gullytrader.db ".tables"
```

Expected: no `markets`, no `exit_decisions`. Should see `positions, orders, fills, settlements, agent_logs, cricket_matches, bot_state`.

```bash
sqlite3 gully-engine/gullytrader.db "SELECT COUNT(*) FROM positions WHERE yes_count + no_count = 0 AND realized_pnl_cents = 0"
```

Expected: `0` (orphans purged).

```bash
sqlite3 gully-engine/gullytrader.db "PRAGMA table_info(positions)" | grep peak_pnl_cents
```

Expected: column appears with default `0`.

- [ ] **Step 12.4: Push branch + open PR**

```bash
git push -u origin feat/honest-dashboard-and-safety-fixes
```

```bash
gh pr create --title "Phase 5: Honest dashboard + trailing-stop fix + DB hygiene" --body "$(cat <<'EOF'
## Summary
- **Frontend honesty**: removed fake iPhone status bar, hidden trends panels with no real data source (Manhattan, last-balls, H2H, form, pitch/weather), removed dead Notify/Autotrade buttons, replaced cricket-chart fake defaults
- **Trailing-stop correctness**: orchestrator now reads real `opened_at` and `peak_pnl_cents` from positions DB instead of hardcoding `now-600` and `0`
- **DB hygiene**: dropped dead `markets` and `exit_decisions` tables; one-time purge of 28 orphan zero-contract positions; sync_service now skips writing flat positions

## Test plan
- [x] `cd gully-engine && python -m pytest` — ~155 passing
- [ ] Manual: boot uvicorn, verify no battery icon on dashboard
- [ ] Manual: trends page renders cleanly with no fake panels
- [ ] Manual: standings has no Notify/Autotrade buttons
- [ ] Manual: `sqlite3` verifies dropped tables + purged orphans + new column

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 12.5: Note PR URL for handoff**

Capture the PR URL from gh's output for the user.

---

## Self-review summary

**Spec coverage:** All 4 units (A, C, D, E) have tasks. Frontend (Tasks 7-10), trailing-stop (Tasks 4-6), position hygiene (Tasks 2-3), dead schema (Task 1). Plus docs (11) and verification (12).

**Placeholder scan:** No TBDs, no "TODO later", no "similar to Task N", no abstract steps. Every code change has the actual code.

**Type consistency:** `peak_pnl_cents` column name used consistently. `KalshiPosition` field names match the dataclass at `kalshi_client.py`. `PositionSnapshot` field names match `exit_monitor.py:45`.

**Spec gaps:** None.
