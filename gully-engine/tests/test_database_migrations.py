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
