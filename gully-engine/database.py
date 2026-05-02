"""SQLite schema (WAL mode) for GullyTrader.

Mirrors the KalshiTrader engine's table layout, narrowed to cricket-specific tables.
WAL mode is non-negotiable: it lets the orchestrator / sync service / FastAPI
process concurrent reads while writes serialize cleanly.
"""

from __future__ import annotations

import contextlib
import sqlite3
from pathlib import Path
from typing import Iterator

from settings import settings


SCHEMA = """
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

CREATE INDEX IF NOT EXISTS positions_status_idx ON positions(status);

CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kalshi_order_id TEXT UNIQUE,
    ticker TEXT NOT NULL,
    side TEXT NOT NULL,
    action TEXT NOT NULL,              -- 'buy' | 'sell'
    count INTEGER NOT NULL,
    limit_price_cents INTEGER,
    status TEXT NOT NULL,
    placed_at INTEGER,
    filled_at INTEGER,
    settled_at INTEGER,
    metadata_json TEXT
);

CREATE INDEX IF NOT EXISTS orders_ticker_idx ON orders(ticker);

CREATE TABLE IF NOT EXISTS fills (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kalshi_trade_id TEXT,
    kalshi_order_id TEXT,
    order_id INTEGER REFERENCES orders(id),
    ticker TEXT NOT NULL,
    side TEXT NOT NULL,
    action TEXT,
    count INTEGER NOT NULL,
    price_cents INTEGER NOT NULL,
    is_taker INTEGER DEFAULT 0,
    filled_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS fills_ticker_idx ON fills(ticker);

CREATE TABLE IF NOT EXISTS settlements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    market_result TEXT,                -- 'yes' | 'no' | 'void'
    revenue_cents INTEGER,
    cost_cents INTEGER,
    net_pnl_cents INTEGER,
    settled_at INTEGER NOT NULL,
    category TEXT,                     -- e.g. 'cricket-match-winner', 'cricket-total-runs'
    UNIQUE(ticker)
);

CREATE TABLE IF NOT EXISTS agent_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent TEXT NOT NULL,               -- scanner | researcher | decision | exit
    ticker TEXT,
    decision TEXT,
    confidence REAL,
    reasoning TEXT,
    model TEXT,
    latency_ms INTEGER,
    created_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS agent_logs_created_idx ON agent_logs(created_at);

CREATE TABLE IF NOT EXISTS cricket_matches (
    match_id TEXT PRIMARY KEY,
    series TEXT,
    team_a TEXT NOT NULL,
    team_b TEXT NOT NULL,
    venue TEXT,
    start_time INTEGER,
    status TEXT,                       -- scheduled | live | completed
    score_a TEXT,
    score_b TEXT,
    overs_a TEXT,
    overs_b TEXT,
    win_prob_a INTEGER,                -- 0-100
    last_update INTEGER
);

CREATE INDEX IF NOT EXISTS cricket_matches_status_idx ON cricket_matches(status);

CREATE TABLE IF NOT EXISTS bot_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    active INTEGER NOT NULL DEFAULT 0,
    updated_at INTEGER NOT NULL
);
"""


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    """Open a SQLite connection in WAL mode."""
    db_path = Path(path) if path else settings.db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=30.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def initialize(path: Path | str | None = None) -> None:
    """Apply schema (idempotent)."""
    with connect(path) as conn:
        conn.executescript(SCHEMA)
        _migrate(conn)


def _migrate(conn: sqlite3.Connection) -> None:
    """Apply column additions for tables that pre-date a schema change.

    SQLite's ALTER TABLE ADD COLUMN is not idempotent on its own, so we wrap
    each new column in a try/except. Pre-alpha migration discipline; sufficient
    while the engine is still hobby-tier.
    """
    additions = [
        ("fills", "kalshi_trade_id", "TEXT"),
        ("fills", "kalshi_order_id", "TEXT"),
        ("fills", "action", "TEXT"),
        ("fills", "is_taker", "INTEGER DEFAULT 0"),
        ("positions", "peak_pnl_cents", "INTEGER NOT NULL DEFAULT 0"),
    ]
    for table, col, decl in additions:
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
        except sqlite3.OperationalError:
            pass   # column already exists

    # Index creation has to run AFTER any ADD COLUMN — the index references
    # kalshi_trade_id, which doesn't exist on pre-migration DBs.
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS fills_trade_id_idx "
        "ON fills(kalshi_trade_id) WHERE kalshi_trade_id IS NOT NULL"
    )

    # Phase 4: drop orphan closed_market_cache table (never written/read).
    try:
        conn.execute("DROP TABLE IF EXISTS closed_market_cache")
    except sqlite3.OperationalError:
        pass

    # Phase 5: drop dead schema tables (markets, exit_decisions).
    # Both were scaffolded but never written to or read from outside CREATE.
    for dead_table in ("markets", "exit_decisions"):
        try:
            conn.execute(f"DROP TABLE IF EXISTS {dead_table}")
        except sqlite3.OperationalError:
            pass

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


@contextlib.contextmanager
def write_conn() -> Iterator[sqlite3.Connection]:
    """Wrap a write connection with try/finally close.

    *Inherited from KalshiTrader (PR #50):* always close write connections in
    a finally block so a transient SQLite open failure can't leak handles and
    grind the orchestrator to a halt over time.
    """
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()


def purge_old_agent_logs(max_age_days: int | None = None) -> int:
    """Delete agent_logs older than max_age_days. Returns rows deleted."""
    import time

    days = max_age_days or settings.agent_logs_max_age_days
    cutoff = int(time.time()) - days * 86_400
    with write_conn() as conn:
        cur = conn.execute("DELETE FROM agent_logs WHERE created_at < ?", (cutoff,))
        return cur.rowcount or 0


def ensure_bot_state(default_active: bool = False) -> None:
    """Insert the singleton bot_state row if it doesn't exist yet."""
    import time
    with write_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO bot_state (id, active, updated_at) "
            "VALUES (1, ?, ?)",
            (1 if default_active else 0, int(time.time())),
        )


def get_bot_active() -> bool:
    with connect() as conn:
        row = conn.execute("SELECT active FROM bot_state WHERE id = 1").fetchone()
    return bool(row and row["active"])


def set_bot_active(active: bool) -> None:
    import time
    with write_conn() as conn:
        conn.execute(
            "INSERT INTO bot_state (id, active, updated_at) VALUES (1, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET active=excluded.active, "
            "updated_at=excluded.updated_at",
            (1 if active else 0, int(time.time())),
        )
