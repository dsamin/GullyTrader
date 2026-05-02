"""Tests for KalshiClient — orders / fills / settlements / positions read paths.

Focus on the new Phase-1 reconciliation methods. We stub `_request` and force
`_authed=True` so we exercise the real parsing path without making real HTTP
calls or signing.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from kalshi_client import (
    KalshiClient,
    KalshiFill,
    KalshiOrder,
    KalshiSettlement,
)


def _client() -> KalshiClient:
    """Build a client with auth bypassed so _request paths are taken."""
    c = KalshiClient()
    c._authed = True   # noqa: SLF001 — test scaffolding
    return c


# ── list_orders ────────────────────────────────────────────────────────


def test_list_orders_parses_kalshi_response():
    resp = {
        "orders": [
            {
                "order_id": "ord-1",
                "ticker": "KXIPLGAME-26MAY07RCBLSG-LSG",
                "side": "yes",
                "action": "buy",
                "type": "limit",
                "status": "resting",
                "yes_price": 42,
                "count": 100,
                "place_count": 100,
                "remaining_count": 100,
                "created_time": "2026-05-01T10:00:00Z",
            },
            {
                "order_id": "ord-2",
                "ticker": "KXIPLGAME-26MAY07RCBLSG-RCB",
                "side": "no",
                "action": "buy",
                "type": "limit",
                "status": "executed",
                "no_price": 55,
                "count": 50,
                "place_count": 50,
                "remaining_count": 0,
                "created_time": "2026-05-01T11:00:00Z",
                "last_update_time": "2026-05-01T11:00:30Z",
            },
        ],
        "cursor": "",
    }
    c = _client()
    with patch.object(c, "_request", return_value=resp):
        orders = c.list_orders()

    assert len(orders) == 2
    assert all(isinstance(o, KalshiOrder) for o in orders)

    o1, o2 = orders
    assert o1.order_id == "ord-1"
    assert o1.ticker == "KXIPLGAME-26MAY07RCBLSG-LSG"
    assert o1.side == "yes"
    assert o1.action == "buy"
    assert o1.status == "resting"
    assert o1.limit_price_cents == 42
    assert o1.count == 100

    assert o2.order_id == "ord-2"
    assert o2.side == "no"
    assert o2.status == "executed"
    assert o2.limit_price_cents == 55   # picks no_price for no-side orders


def test_list_orders_pages_via_cursor():
    page1 = {"orders": [{"order_id": "a", "ticker": "T", "side": "yes",
                          "action": "buy", "type": "limit", "status": "resting",
                          "yes_price": 50, "count": 10}], "cursor": "tok"}
    page2 = {"orders": [{"order_id": "b", "ticker": "T", "side": "yes",
                          "action": "buy", "type": "limit", "status": "executed",
                          "yes_price": 50, "count": 10}], "cursor": ""}
    c = _client()
    seen_cursors: list[str | None] = []

    def fake_req(method, path, params=None, body=None):
        seen_cursors.append(params.get("cursor") if params else None)
        return page1 if not seen_cursors[-1] else page2

    with patch.object(c, "_request", side_effect=fake_req):
        orders = c.list_orders()

    assert [o.order_id for o in orders] == ["a", "b"]
    assert seen_cursors[1] == "tok"


def test_list_orders_returns_empty_on_error():
    c = _client()
    with patch.object(c, "_request", return_value={"error": "boom"}):
        assert c.list_orders() == []


def test_list_orders_handles_none_price_field():
    """Regression: live Kalshi sometimes returns yes_price=None on a yes-side
    order (e.g. canceled / fully-executed). Don't crash, default to 0.

    Caught by smoke test 2026-05-01 against live /portfolio/orders."""
    resp = {
        "orders": [
            {"order_id": "o1", "ticker": "T", "side": "yes", "action": "buy",
             "type": "limit", "status": "canceled",
             "yes_price": None, "no_price": None, "count": 0},
        ],
        "cursor": "",
    }
    c = _client()
    with patch.object(c, "_request", return_value=resp):
        orders = c.list_orders()
    assert len(orders) == 1
    assert orders[0].limit_price_cents == 0


def test_list_orders_uses_mock_when_unauthed():
    c = KalshiClient()
    c._authed = False
    # Unauthed path should NOT crash and should not call _request
    orders = c.list_orders()
    assert isinstance(orders, list)


# ── list_fills ─────────────────────────────────────────────────────────


def test_list_fills_parses_kalshi_response():
    resp = {
        "fills": [
            {
                "trade_id": "trade-1",
                "order_id": "ord-1",
                "ticker": "KXIPLGAME-26MAY07RCBLSG-LSG",
                "side": "yes",
                "action": "buy",
                "count": 100,
                "yes_price": 42,
                "is_taker": True,
                "created_time": "2026-05-01T10:00:05Z",
            },
            {
                "trade_id": "trade-2",
                "order_id": "ord-2",
                "ticker": "KXIPLGAME-26MAY07RCBLSG-LSG",
                "side": "no",
                "action": "buy",
                "count": 80,
                "no_price": 55,
                "is_taker": False,
                "created_time": "2026-05-01T11:00:30Z",
            },
        ],
        "cursor": "",
    }
    c = _client()
    with patch.object(c, "_request", return_value=resp):
        fills = c.list_fills()

    assert len(fills) == 2
    assert all(isinstance(f, KalshiFill) for f in fills)
    assert fills[0].trade_id == "trade-1"
    assert fills[0].price_cents == 42      # yes-side fill price
    assert fills[1].price_cents == 55      # no-side fill price
    assert fills[0].count == 100
    assert fills[1].is_taker is False


def test_list_fills_returns_empty_on_error():
    c = _client()
    with patch.object(c, "_request", return_value={"error": "rate limited"}):
        assert c.list_fills() == []


def test_list_fills_handles_none_price_field():
    """Regression: live Kalshi can return yes_price=None on a yes-side fill.
    Same pattern as orders — caught by 2026-05-01 smoke test."""
    resp = {
        "fills": [
            {"trade_id": "t1", "order_id": "o1", "ticker": "T",
             "side": "yes", "action": "buy", "count": 10,
             "yes_price": None, "no_price": None, "is_taker": True},
        ],
        "cursor": "",
    }
    c = _client()
    with patch.object(c, "_request", return_value=resp):
        fills = c.list_fills()
    assert len(fills) == 1
    assert fills[0].price_cents == 0


# ── list_settlements ───────────────────────────────────────────────────


def test_list_settlements_parses_kalshi_response_with_paired_correction():
    """Paired-position settlements must add min(yes,no)*100c to revenue.

    Carries forward the load-bearing pnl correction (test_pnl.py:44).
    """
    resp = {
        "settlements": [
            {
                # Plain YES win: 100 contracts × 100¢ payout
                "ticker": "KXIPLGAME-26APR30RCBPBKS-RCB",
                "market_result": "yes",
                "yes_count": 100,
                "yes_total_cost": 4_200,
                "no_count": 0,
                "no_total_cost": 0,
                "revenue": 10_000,
                "settled_time": "2026-04-30T18:00:00Z",
            },
            {
                # Paired exit: 100 YES @ 42, 100 NO @ 60. Kalshi reports revenue=0.
                # We must apply paired correction → revenue += 100*100 = 10_000c.
                "ticker": "KXIPLGAME-26APR29MUMCHE-MUM",
                "market_result": "no",
                "yes_count": 100,
                "yes_total_cost": 4_200,
                "no_count": 100,
                "no_total_cost": 6_000,
                "revenue": 0,
                "settled_time": "2026-04-29T18:00:00Z",
            },
        ],
        "cursor": "",
    }
    c = _client()
    with patch.object(c, "_request", return_value=resp):
        settlements = c.list_settlements()

    assert len(settlements) == 2
    assert all(isinstance(s, KalshiSettlement) for s in settlements)

    s_plain, s_paired = settlements
    assert s_plain.ticker == "KXIPLGAME-26APR30RCBPBKS-RCB"
    assert s_plain.revenue_cents == 10_000
    assert s_plain.cost_cents == 4_200
    assert s_plain.net_pnl_cents == 5_800

    # Paired correction kicks in: revenue raised from 0 → 10_000.
    assert s_paired.revenue_cents == 10_000
    assert s_paired.cost_cents == 10_200
    assert s_paired.net_pnl_cents == -200    # cost-of-spread, NOT phantom -10_200


def test_list_settlements_returns_empty_on_error():
    c = _client()
    with patch.object(c, "_request", return_value={"error": "boom"}):
        assert c.list_settlements() == []


# ── Strict-mode auth gating ────────────────────────────────────────────


def _set_settings(**overrides):
    """Mutate the frozen Settings singleton for the duration of a test.

    Returns a callable that restores the originals. Same pattern as
    test_sync_service.tmp_db.
    """
    from settings import settings as _settings
    originals = {k: getattr(_settings, k) for k in overrides}
    for k, v in overrides.items():
        object.__setattr__(_settings, k, v)

    def _restore():
        for k, v in originals.items():
            object.__setattr__(_settings, k, v)
    return _restore


def test_init_raises_in_strict_mode_when_unauthed():
    """Strict mode + missing creds = refuse to start (loud failure)."""
    restore = _set_settings(
        strict_external_services=True,
        kalshi_key_id="",
        kalshi_private_key_path="",
    )
    try:
        with pytest.raises(RuntimeError, match="Kalshi credentials missing"):
            KalshiClient()
    finally:
        restore()


def test_init_succeeds_in_strict_mode_when_authed(tmp_path, monkeypatch):
    """Strict mode + valid creds = startup proceeds normally."""
    # Generate a throwaway PEM the client can load.
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )
    key_path = tmp_path / "kalshi.pem"
    key_path.write_bytes(pem)

    restore = _set_settings(
        strict_external_services=True,
        kalshi_key_id="key-abc",
        kalshi_private_key_path=str(key_path),
    )
    try:
        c = KalshiClient()
        assert c._authed is True
    finally:
        restore()


def test_init_does_not_raise_in_non_strict_mode_when_unauthed():
    """Default dev posture: missing creds → mock fallbacks, no exception."""
    restore = _set_settings(
        strict_external_services=False,
        kalshi_key_id="",
        kalshi_private_key_path="",
    )
    try:
        c = KalshiClient()
        assert c._authed is False
    finally:
        restore()


def test_place_limit_order_in_prod_unauthed_raises():
    """Real-money path: prod env + no creds must NEVER return stub-order.

    This is independent of strict mode — even if strict is somehow off, prod
    writes to Kalshi must not silently no-op. Catches deploy misconfigs where
    KALSHI_API_ENV got set but the key path didn't.
    """
    # Force-construct a non-strict client (so __init__ doesn't raise),
    # then flip env to prod and re-check place_limit_order.
    restore = _set_settings(
        strict_external_services=False,
        kalshi_key_id="",
        kalshi_private_key_path="",
        kalshi_api_env="demo",        # let __init__ pass
    )
    try:
        c = KalshiClient()
        assert c._authed is False
        # Now flip to prod — place_limit_order must refuse.
        # Safe to bare-mutate here: _set_settings captured the original
        # kalshi_api_env above, so restore() will revert this in the finally.
        from settings import settings as _settings
        object.__setattr__(_settings, "kalshi_api_env", "prod")
        with pytest.raises(RuntimeError, match="prod.*unauthenticated|unauthenticated.*prod"):
            c.place_limit_order(
                ticker="KXIPLGAME-26MAY07RCBLSG-LSG",
                side="yes", action="buy", count=10, limit_price_cents=42,
            )
    finally:
        restore()


def test_place_limit_order_unauthed_demo_returns_stub():
    """Demo env preserves the dev-friendly stub-order fallback."""
    restore = _set_settings(
        strict_external_services=False,
        kalshi_key_id="",
        kalshi_private_key_path="",
        kalshi_api_env="demo",
    )
    try:
        c = KalshiClient()
        result = c.place_limit_order(
            ticker="KXIPL-26-MUMCHE-MUM",
            side="yes", action="buy", count=10, limit_price_cents=42,
        )
        assert result["order_id"] == "stub-order"
    finally:
        restore()
