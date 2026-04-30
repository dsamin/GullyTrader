"""Background reconciliation loop.

Pulls orders / fills / settlements / positions from Kalshi every
SYNC_INTERVAL_SECONDS and updates the local DB. Survives transient SQLite
open failures and Kalshi rate limits — the loop must never die from a single
error.

Inherited from KalshiTrader PR #54: when SQLite open fails (e.g. file moved
or temp lock), log + sleep + retry rather than letting the thread crash.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import time

from settings import settings


log = logging.getLogger(__name__)

_stop_flag = threading.Event()


def stop() -> None:
    _stop_flag.set()


def _reconcile_once() -> None:
    """One pass: pull positions, orders, fills, settlements; upsert into DB.

    TODO: fill in the actual reconciliation logic. Kept as a placeholder so
    the loop scaffolding can be exercised before the Kalshi client is
    authenticated.
    """
    log.debug("sync_service: reconcile pass (stub)")


def run() -> None:
    """Run the loop until stop() is called.

    Caller is responsible for spinning this in a daemon thread.
    """
    backoff = 1.0
    while not _stop_flag.is_set():
        try:
            _reconcile_once()
            backoff = 1.0
        except sqlite3.OperationalError as exc:
            # PR #54: keep loop alive when SQLite open fails
            log.warning("sync_service: SQLite error, retrying after backoff: %s", exc)
            time.sleep(min(30.0, backoff))
            backoff = min(30.0, backoff * 2)
            continue
        except Exception:  # noqa: BLE001 — top-level loop must not die
            log.exception("sync_service: unexpected error, sleeping before retry")
            time.sleep(min(30.0, backoff))
            backoff = min(30.0, backoff * 2)
            continue

        if _stop_flag.wait(timeout=settings.sync_interval_seconds):
            break


def start_in_thread() -> threading.Thread:
    t = threading.Thread(target=run, daemon=True, name="sync_service")
    t.start()
    log.info("sync_service: started thread")
    return t
