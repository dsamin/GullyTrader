"""Orchestrator wiring tests — mock all external services and agents.

Verifies the shadow/live gate around place_limit_order in both pipelines
and that the exit pipeline fetches real mark prices via get_market.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

import database
import orchestrator
from agents.decision import TradeDecision
from agents.researcher import ResearchNote
from exit_monitor import ExitDecision
from kalshi_client import KalshiMarket, KalshiPosition


@pytest.fixture
def tmp_db(tmp_path):
    """Point settings.db_path at a tmp file and run schema."""
    from settings import settings as _settings
    db_path = tmp_path / "test.db"
    original = _settings.db_path
    object.__setattr__(_settings, "db_path", db_path)
    try:
        database.initialize(db_path)
        yield db_path
    finally:
        object.__setattr__(_settings, "db_path", original)


def _set_settings(**overrides):
    """Override frozen Settings dataclass for the duration of a test."""
    from settings import settings as _settings
    originals = {k: getattr(_settings, k) for k in overrides}
    for k, v in overrides.items():
        object.__setattr__(_settings, k, v)
    def restore():
        for k, v in originals.items():
            object.__setattr__(_settings, k, v)
    return restore


def _market(ticker: str = "KXIPLGAME-T", yes: int = 50) -> KalshiMarket:
    return KalshiMarket(
        ticker=ticker, event_ticker=ticker, title="t",
        yes_price=yes, no_price=100 - yes, status="open",
    )


def _position(ticker: str = "KXIPLGAME-T", side: str = "yes") -> KalshiPosition:
    return KalshiPosition(
        ticker=ticker,
        yes_count=100 if side == "yes" else 0,
        no_count=0 if side == "yes" else 100,
        avg_cost_cents=50,
        market_exposure_cents=5000,
    )


def _seed_position_row(db_path, ticker: str = "KXIPLGAME-T", side: str = "yes") -> None:
    """Insert a positions row so run_exit_monitor_once can SELECT opened_at + peak.

    Required since orchestrator.py reads opened_at + peak_pnl_cents from DB and
    skips Kalshi-reported positions absent from the DB (race-with-sync defense).
    """
    import sqlite3
    import time
    conn = sqlite3.connect(str(db_path), isolation_level=None)
    try:
        conn.execute(
            "INSERT INTO positions (ticker, side, yes_count, no_count, "
            "avg_cost_cents, market_exposure_cents, peak_pnl_cents, "
            "opened_at, status) VALUES (?, ?, ?, ?, 50, 5000, 0, ?, 'open')",
            (
                ticker, side,
                100 if side == "yes" else 0,
                0 if side == "yes" else 100,
                int(time.time()) - 600,
            ),
        )
    finally:
        conn.close()


# ── Entry pipeline ─────────────────────────────────────────────────────


def test_entry_shadow_mode_does_not_place_order():
    restore = _set_settings(decision_mode="shadow")
    try:
        client = MagicMock()
        client.list_ipl_markets.return_value = [_market(yes=40)]
        client.get_balance.return_value = {"balance": 100_000}
        client.place_limit_order = MagicMock()

        with patch("orchestrator.KalshiClient", return_value=client), \
             patch("orchestrator.get_feed") as gf, \
             patch("orchestrator.scanner_shortlist") as sc, \
             patch("orchestrator.research") as rs, \
             patch("orchestrator.decide") as dc:
            gf.return_value.live_match.return_value = None
            sc.return_value = [MagicMock(ticker="KXIPLGAME-T", score=80, reason="ok")]
            rs.return_value = ResearchNote("KXIPLGAME-T", 0.7, 0.6, "yes")
            dc.return_value = TradeDecision("KXIPLGAME-T", "buy_yes", 5, 41, "edge")
            result = orchestrator.run_entry_pipeline_once(force=True)

        assert result["status"] == "ok"
        assert result["decision_mode"] == "shadow"
        client.place_limit_order.assert_not_called()
        assert result["candidates"][0]["decision"]["action"] == "buy_yes"
        assert result["candidates"][0]["order"] is None
    finally:
        restore()


def test_entry_live_mode_places_order_on_buy():
    restore = _set_settings(decision_mode="live")
    try:
        client = MagicMock()
        client.list_ipl_markets.return_value = [_market(yes=40)]
        client.get_balance.return_value = {"balance": 100_000}
        client.place_limit_order.return_value = {"order_id": "o-1", "status": "queued"}

        with patch("orchestrator.KalshiClient", return_value=client), \
             patch("orchestrator.get_feed") as gf, \
             patch("orchestrator.scanner_shortlist") as sc, \
             patch("orchestrator.research") as rs, \
             patch("orchestrator.decide") as dc:
            gf.return_value.live_match.return_value = None
            sc.return_value = [MagicMock(ticker="KXIPLGAME-T", score=80, reason="ok")]
            rs.return_value = ResearchNote("KXIPLGAME-T", 0.7, 0.6, "yes")
            dc.return_value = TradeDecision("KXIPLGAME-T", "buy_yes", 5, 41, "edge")
            result = orchestrator.run_entry_pipeline_once(force=True)

        client.place_limit_order.assert_called_once_with(
            ticker="KXIPLGAME-T", side="yes", action="buy",
            count=5, limit_price_cents=41,
        )
        assert result["candidates"][0]["order"] == {"order_id": "o-1", "status": "queued"}
    finally:
        restore()


def test_entry_live_mode_does_not_place_order_on_pass():
    restore = _set_settings(decision_mode="live")
    try:
        client = MagicMock()
        client.list_ipl_markets.return_value = [_market(yes=50)]
        client.get_balance.return_value = {"balance": 100_000}
        client.place_limit_order = MagicMock()

        with patch("orchestrator.KalshiClient", return_value=client), \
             patch("orchestrator.get_feed") as gf, \
             patch("orchestrator.scanner_shortlist") as sc, \
             patch("orchestrator.research") as rs, \
             patch("orchestrator.decide") as dc:
            gf.return_value.live_match.return_value = None
            sc.return_value = [MagicMock(ticker="KXIPLGAME-T", score=80, reason="ok")]
            rs.return_value = ResearchNote("KXIPLGAME-T", 0.51, 0.6, "low edge")
            dc.return_value = TradeDecision("KXIPLGAME-T", "pass", 0, 50, "edge too low")
            result = orchestrator.run_entry_pipeline_once(force=True)

        client.place_limit_order.assert_not_called()
        assert result["candidates"][0]["decision"]["action"] == "pass"
    finally:
        restore()


# ── Exit pipeline ──────────────────────────────────────────────────────


def _hold_decision(ticker: str, mark: int) -> ExitDecision:
    return ExitDecision(ticker=ticker, trigger="llm", action="hold",
                        mode="shadow", mark_price_cents=mark,
                        pnl_cents_at_decision=0, note="t")


def _sell_decision(ticker: str, mark: int, mode: str) -> ExitDecision:
    return ExitDecision(ticker=ticker, trigger="llm", action="sell",
                        mode=mode, mark_price_cents=mark,
                        pnl_cents_at_decision=100, note="t")


def test_exit_shadow_mode_does_not_place_sell_on_sell_decision(tmp_db):
    _seed_position_row(tmp_db, ticker="KXIPLGAME-T", side="yes")
    restore = _set_settings(exit_mode="shadow")
    try:
        client = MagicMock()
        client.list_positions.return_value = [_position(ticker="KXIPLGAME-T", side="yes")]
        client.get_market.return_value = _market(ticker="KXIPLGAME-T", yes=70)
        client.place_limit_order = MagicMock()

        with patch("orchestrator.KalshiClient", return_value=client), \
             patch("orchestrator.evaluate") as ev:
            ev.return_value = _sell_decision("KXIPLGAME-T", 70, "shadow")
            result = orchestrator.run_exit_monitor_once(force=True)

        client.place_limit_order.assert_not_called()
        assert result["actions"][0]["action"] == "sell"
        assert result["actions"][0]["order"] is None
        assert result["exit_mode"] == "shadow"
    finally:
        restore()


def test_exit_live_mode_places_sell_on_sell_decision(tmp_db):
    _seed_position_row(tmp_db, ticker="KXIPLGAME-T", side="yes")
    restore = _set_settings(exit_mode="live")
    try:
        client = MagicMock()
        client.list_positions.return_value = [_position(ticker="KXIPLGAME-T", side="yes")]
        client.get_market.return_value = _market(ticker="KXIPLGAME-T", yes=70)
        client.place_limit_order.return_value = {"order_id": "sell-1", "status": "queued"}

        with patch("orchestrator.KalshiClient", return_value=client), \
             patch("orchestrator.evaluate") as ev:
            ev.return_value = _sell_decision("KXIPLGAME-T", 70, "live")
            result = orchestrator.run_exit_monitor_once(force=True)

        client.place_limit_order.assert_called_once_with(
            ticker="KXIPLGAME-T", side="yes", action="sell",
            count=100, limit_price_cents=69,   # mark - 1
        )
        assert result["actions"][0]["order"] == {"order_id": "sell-1", "status": "queued"}
    finally:
        restore()


def test_exit_pipeline_fetches_real_mark_via_get_market(tmp_db):
    """The snapshot passed into evaluate() must use yes_price/no_price from
    get_market, not avg_cost_cents."""
    _seed_position_row(tmp_db, ticker="KXIPLGAME-T", side="yes")
    restore = _set_settings(exit_mode="shadow")
    try:
        client = MagicMock()
        client.list_positions.return_value = [_position(ticker="KXIPLGAME-T", side="yes")]
        client.get_market.return_value = _market(ticker="KXIPLGAME-T", yes=73)
        client.place_limit_order = MagicMock()

        captured = {}
        def _eval(snap, *, now=None):
            captured["mark"] = snap.mark_price_cents
            return _hold_decision(snap.ticker, snap.mark_price_cents)

        with patch("orchestrator.KalshiClient", return_value=client), \
             patch("orchestrator.evaluate", side_effect=_eval):
            orchestrator.run_exit_monitor_once(force=True)

        assert captured["mark"] == 73   # yes_price from get_market, not avg_cost_cents (50)
        client.get_market.assert_called_once_with("KXIPLGAME-T")
    finally:
        restore()


def test_run_entry_pipeline_writes_decision_to_agent_logs(tmp_db):
    """Each candidate's decision must land in agent_logs as agent='decision'."""
    market = _market("KXIPLGAME-26-MUM", yes=58)
    fake_client = type("C", (), {})()
    fake_client.list_ipl_markets = lambda: [market]
    fake_client.get_balance = lambda: {"balance": 100_00}
    fake_client.place_limit_order = lambda **kw: {"order_id": "o1"}

    note = ResearchNote(
        ticker=market.ticker, estimated_yes_probability=0.65,
        confidence=0.8, reasoning="strong form",
    )
    decision = TradeDecision(
        ticker=market.ticker, action="buy_yes", contracts=10,
        limit_price_cents=59, reasoning="edge=+7c kelly=0.20 -> 10 ct",
    )

    candidate = type("C", (), {"ticker": market.ticker, "score": 9, "reason": "x"})()

    with patch("orchestrator.KalshiClient", return_value=fake_client), \
         patch("orchestrator.scanner_shortlist", return_value=[candidate]), \
         patch("orchestrator.research", return_value=note), \
         patch("orchestrator.decide", return_value=decision), \
         patch("orchestrator.get_feed") as gf:
        gf.return_value.live_match = lambda: None
        orchestrator.run_entry_pipeline_once(force=True)

    with database.connect(tmp_db) as conn:
        rows = conn.execute(
            "SELECT agent, ticker, decision, reasoning FROM agent_logs WHERE agent='decision'"
        ).fetchall()
    assert len(rows) == 1
    assert rows[0]["ticker"] == market.ticker
    assert rows[0]["decision"] == "buy_yes"
    assert "edge=+7c" in rows[0]["reasoning"]


def test_run_exit_monitor_writes_exit_to_agent_logs(tmp_db):
    """Each evaluated position must land an agent_logs row keyed agent='exit'."""
    import database
    pos = _position("KXIPL-T", side="yes")
    _seed_position_row(tmp_db, ticker=pos.ticker, side="yes")
    market = _market(pos.ticker, yes=58)
    exit_dec = ExitDecision(
        ticker=pos.ticker, trigger="llm", action="hold", mode="shadow",
        mark_price_cents=58, pnl_cents_at_decision=800, note="hold: still positive momentum",
    )
    fake_client = type("C", (), {})()
    fake_client.list_positions = lambda: [pos]
    fake_client.get_market = lambda t: market
    fake_client.place_limit_order = lambda **kw: {}

    with patch("orchestrator.KalshiClient", return_value=fake_client), \
         patch("orchestrator.evaluate", return_value=exit_dec):
        orchestrator.run_exit_monitor_once(force=True)

    with database.connect(tmp_db) as conn:
        rows = conn.execute(
            "SELECT agent, ticker, decision, reasoning FROM agent_logs WHERE agent='exit'"
        ).fetchall()
    assert len(rows) == 1
    assert rows[0]["ticker"] == pos.ticker
    assert rows[0]["decision"] == "hold"
    assert "llm" in rows[0]["reasoning"]


@pytest.fixture
def _stub_orchestrator_loops():
    """Replace orchestrator's _entry_loop / _exit_loop with no-op waiters.

    The lifecycle tests below care about thread-state semantics (start/stop/
    is_running), not about what the loops do. Stubbing them prevents real
    Kalshi/CricAPI calls and DB writes during these tests, and makes the
    threads exit promptly when _stop_flag is set.
    """
    import orchestrator
    orig_entry = orchestrator._entry_loop
    orig_exit = orchestrator._exit_loop

    def _waiter():
        orchestrator._stop_flag.wait()

    orchestrator._entry_loop = _waiter
    orchestrator._exit_loop = _waiter
    yield
    orchestrator._entry_loop = orig_entry
    orchestrator._exit_loop = orig_exit


def test_orchestrator_start_threads_clears_stop_flag(tmp_db, _stub_orchestrator_loops):
    """A start_threads() call after stop() must clear _stop_flag so the new
    threads don't see is_set() and immediately bail."""
    import orchestrator
    orchestrator.stop()
    assert orchestrator._stop_flag.is_set()
    try:
        orchestrator.start_threads()
        assert not orchestrator._stop_flag.is_set()
    finally:
        orchestrator.stop()


def test_orchestrator_start_threads_is_idempotent(tmp_db, _stub_orchestrator_loops):
    """Calling start_threads twice must not spawn two pairs of loops."""
    import orchestrator
    try:
        orchestrator.start_threads()
        threads_after_first = list(orchestrator._threads)
        result = orchestrator.start_threads()    # second call is a no-op
        assert result is None
        assert orchestrator._threads == threads_after_first   # same Thread objects
        assert orchestrator.is_running() is True
    finally:
        orchestrator.stop()


def test_orchestrator_is_running_reflects_state(tmp_db, _stub_orchestrator_loops):
    import orchestrator
    orchestrator.stop()
    assert orchestrator.is_running() is False
    try:
        orchestrator.start_threads()
        assert orchestrator.is_running() is True
    finally:
        orchestrator.stop()
        assert orchestrator.is_running() is False


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
                ticker="KXIPL-OLD",
                yes_count=10, no_count=0,
                avg_cost_cents=45, market_exposure_cents=480,
            )
        ]
        fake_client.get_market.return_value = KalshiMarket(
            ticker="KXIPL-OLD", event_ticker="KXIPL-25", title="t",
            yes_price=48, no_price=52, status="open",
        )
        # Capture PositionSnapshot passed to evaluate
        captured = []
        def fake_evaluate(snap, **kw):
            captured.append(snap)
            from exit_monitor import ExitDecision
            return ExitDecision(
                ticker=snap.ticker, trigger="none", action="hold",
                mode="shadow", mark_price_cents=snap.mark_price_cents,
                pnl_cents_at_decision=0, note="test",
            )

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
                ticker="KXIPL-NEW",
                yes_count=5, no_count=0,
                avg_cost_cents=50, market_exposure_cents=250,
            )
        ]
        fake_client.get_market.return_value = KalshiMarket(
            ticker="KXIPL-NEW", event_ticker="KXIPL-25", title="t",
            yes_price=50, no_price=50, status="open",
        )

        def fake_evaluate(snap, **kw):
            raise AssertionError("evaluate should not be called for missing-row position")

        with patch("orchestrator.KalshiClient", return_value=fake_client), \
             patch("orchestrator.evaluate", side_effect=fake_evaluate), \
             caplog.at_level(logging.WARNING, logger="orchestrator"):
            orchestrator.run_exit_monitor_once(force=True)

        # No crash + warning logged
        assert any("KXIPL-NEW" in rec.message for rec in caplog.records), \
            "expected warning about missing position row"
    finally:
        object.__setattr__(_settings, "db_path", original_path)
