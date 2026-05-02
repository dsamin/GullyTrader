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
