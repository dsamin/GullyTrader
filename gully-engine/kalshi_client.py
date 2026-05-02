"""Kalshi API client — IPL-focused subset with real v2 RSA-PSS auth.

Auth scheme (Kalshi v2):
    Headers:
        KALSHI-ACCESS-KEY:       <key_id>
        KALSHI-ACCESS-SIGNATURE: base64(RSA-PSS-SHA256(timestamp + METHOD + path))
        KALSHI-ACCESS-TIMESTAMP: <ms_since_epoch>
    The signed `path` includes the `/trade-api/v2` prefix.

What's already encoded that you should NOT relearn:
- Always default contract `value` to 100¢ (API returns 0 sometimes).
- Filter parlay/multi-game spam markets via `is_parlay_spam()`.
- Always normalize position side via `pnl.normalize_position_side()`.
- Rate limit at 18 reads/sec, 8 writes/sec (under the 20/10 Basic tier ceiling).
"""

from __future__ import annotations

import base64
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from pnl import normalize_contract_value, realized_pnl
from settings import settings


log = logging.getLogger(__name__)


@dataclass
class KalshiMarket:
    ticker: str
    event_ticker: str
    title: str
    yes_price: int        # cents (1-99)
    no_price: int         # cents
    status: str           # 'open' | 'closed' | 'settled'
    close_time: int | None = None
    contract_value: int = 100
    metadata: dict = field(default_factory=dict)


@dataclass
class KalshiPosition:
    ticker: str
    yes_count: int
    no_count: int
    avg_cost_cents: int
    market_exposure_cents: int


@dataclass
class KalshiEvent:
    event_ticker: str
    series_ticker: str
    title: str
    sub_title: str = ""
    status: str = "open"
    category: str = ""
    mutually_exclusive: bool = False
    metadata: dict = field(default_factory=dict)


@dataclass
class KalshiOrder:
    order_id: str
    ticker: str
    side: str                  # 'yes' | 'no'
    action: str                # 'buy' | 'sell'
    status: str                # 'resting' | 'executed' | 'canceled' | ...
    count: int
    limit_price_cents: int
    created_time: str = ""
    last_update_time: str = ""
    metadata: dict = field(default_factory=dict)


@dataclass
class KalshiFill:
    trade_id: str
    order_id: str
    ticker: str
    side: str                  # 'yes' | 'no'
    action: str                # 'buy' | 'sell'
    count: int
    price_cents: int
    is_taker: bool
    created_time: str = ""


@dataclass
class KalshiSettlement:
    ticker: str
    market_result: str         # 'yes' | 'no' | 'void'
    revenue_cents: int         # already includes paired-position correction
    cost_cents: int
    net_pnl_cents: int
    yes_count: int
    no_count: int
    settled_time: str = ""


# IPL series tickers Kalshi actually uses (verified 2026-04-30):
#   KXIPL          — season champion
#   KXIPLGAME      — per-match winner (e.g. KXIPLGAME-26MAY07RCBLSG)
#   KXIPLPLAYOFF   — playoff qualifiers
#   KXIPLTEAMTOTAL — team total runs
#   KXIPLSIX       — sixes-related markets
#   KXIPLFOUR      — fours-related markets
# NOTE: KXSAUDIPL* is Saudi Pro League soccer — excluded automatically because
# `series.startswith("KXIPL")` doesn't match `KXSAUDI...`.
IPL_SERIES_PREFIXES = ("KXIPL",)


def is_parlay_spam(ticker: str) -> bool:
    """Drop multi-game / cross-category parlay markets."""
    return any(ticker.startswith(prefix) for prefix in settings.parlay_market_prefixes)


def is_ipl_event(series_ticker: str | None, event_ticker: str | None = None) -> bool:
    """True if this series/event belongs to IPL cricket (not Saudi Pro League)."""
    series = (series_ticker or "").upper()
    event = (event_ticker or "").upper()
    if any(series.startswith(p) for p in IPL_SERIES_PREFIXES):
        return True
    return any(event.startswith(p) for p in IPL_SERIES_PREFIXES)


def is_ipl_market(ticker: str, event_ticker: str | None = None) -> bool:
    """Backwards-compatible: True if a market's ticker/event indicates IPL."""
    return is_ipl_event(None, event_ticker) or ticker.upper().startswith(tuple(IPL_SERIES_PREFIXES))


class _RateLimiter:
    """Sliding-window rate limiter — ported verbatim from KalshiTrader."""

    def __init__(self, max_calls: int, period: float = 1.0):
        self.max_calls = max_calls
        self.period = period
        self._calls: list[float] = []
        self._lock = threading.Lock()

    def acquire(self) -> None:
        with self._lock:
            now = time.time()
            self._calls = [t for t in self._calls if now - t < self.period]
            if len(self._calls) >= self.max_calls:
                sleep_time = self.period - (now - self._calls[0])
                if sleep_time > 0:
                    time.sleep(sleep_time)
            self._calls.append(time.time())


class KalshiClient:
    """Kalshi v2 API client with RSA-PSS request signing.

    Falls back to mock data when private key / key id are missing — that lets
    the dashboard render with realistic shape during development without
    Kalshi credentials.
    """

    def __init__(self) -> None:
        self.base_url = settings.kalshi_api_base
        self.key_id = settings.kalshi_key_id
        self.private_key = self._load_private_key(settings.kalshi_private_key_path)
        self._authed = bool(self.key_id and self.private_key)
        if not self._authed:
            log.warning(
                "KalshiClient running unauthenticated (key_id=%s, key_path=%s) — returning mock data",
                bool(self.key_id), settings.kalshi_private_key_path,
            )
        self._read_limiter = _RateLimiter(max_calls=18, period=1.0)
        self._write_limiter = _RateLimiter(max_calls=8, period=1.0)

    @staticmethod
    def _load_private_key(path: str):
        if not path:
            return None
        p = Path(path)
        if not p.exists():
            log.warning("Private key file not found at %s", path)
            return None
        with p.open("rb") as f:
            return serialization.load_pem_private_key(f.read(), password=None)

    # ── Auth ───────────────────────────────────────────────────────────

    def _sign_headers(self, method: str, signed_path: str) -> dict:
        timestamp = str(int(time.time() * 1000))
        message = timestamp + method.upper() + signed_path
        signature = self.private_key.sign(
            message.encode("utf-8"),
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.MAX_LENGTH,
            ),
            hashes.SHA256(),
        )
        return {
            "KALSHI-ACCESS-KEY": self.key_id,
            "KALSHI-ACCESS-SIGNATURE": base64.b64encode(signature).decode("utf-8"),
            "KALSHI-ACCESS-TIMESTAMP": timestamp,
            "Content-Type": "application/json",
        }

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        body: dict | None = None,
    ) -> dict:
        if not self._authed:
            raise RuntimeError("KalshiClient is unauthenticated; cannot make real requests")

        if method.upper() in {"POST", "PUT", "DELETE"}:
            self._write_limiter.acquire()
        else:
            self._read_limiter.acquire()

        # Kalshi v2 requires the `/trade-api/v2` prefix in the signed message
        signed_path = f"/trade-api/v2{path}"
        headers = self._sign_headers(method.upper(), signed_path)
        url = f"{self.base_url}{path}"

        try:
            r = requests.request(method.upper(), url, headers=headers,
                                 params=params, json=body, timeout=15)
        except requests.RequestException as e:
            log.error("Kalshi request failed [%s %s]: %s", method, path, e)
            return {"error": str(e)}

        if not r.ok:
            log.error("Kalshi error [%s %s]: %s %s", method, path, r.status_code, r.text[:200])
            return {"error": r.text, "status_code": r.status_code}
        return r.json()

    # ── Events ─────────────────────────────────────────────────────────

    def list_ipl_events(self, *, max_pages: int = 25) -> list[KalshiEvent]:
        """Return open IPL events (matches, season, playoffs, props).

        Pages /events?status=open and filters by IPL_SERIES_PREFIXES. The
        startswith check on `series_ticker` correctly excludes Saudi Pro League
        events (`KXSAUDIPL*`) which would otherwise match a naive substring search.
        """
        if not self._authed:
            return [
                KalshiEvent("KXIPLGAME-26MUMCHE", "KXIPLGAME",
                            "Mumbai Marauders vs Chennai Crowns", "MUM vs CHE",
                            "open", "Sports", True),
            ]
        out: list[KalshiEvent] = []
        cursor: str | None = None
        for _ in range(max_pages):
            params: dict = {"limit": 200, "status": "open"}
            if cursor:
                params["cursor"] = cursor
            resp = self._request("GET", "/events", params=params)
            if "error" in resp:
                break
            for e in resp.get("events", []):
                if not is_ipl_event(e.get("series_ticker"), e.get("event_ticker")):
                    continue
                out.append(self._event_from_dict(e))
            cursor = resp.get("cursor")
            if not cursor:
                break
        return out

    @staticmethod
    def _event_from_dict(e: dict) -> KalshiEvent:
        return KalshiEvent(
            event_ticker=e.get("event_ticker", ""),
            series_ticker=e.get("series_ticker", ""),
            title=e.get("title", ""),
            sub_title=e.get("sub_title", ""),
            status=e.get("status", "open"),
            category=e.get("category", ""),
            mutually_exclusive=bool(e.get("mutually_exclusive", False)),
            metadata=e,
        )

    # ── Markets ────────────────────────────────────────────────────────

    def list_event_markets(self, event_ticker: str) -> list[KalshiMarket]:
        """All markets attached to a single event."""
        if not self._authed:
            return [m for m in self._mock_markets() if m.event_ticker == event_ticker]
        resp = self._request("GET", "/markets", params={"limit": 200, "event_ticker": event_ticker})
        return [self._market_from_dict(m) for m in resp.get("markets", [])
                if not is_parlay_spam(m.get("ticker", ""))]

    def list_ipl_markets(self, *, max_events: int = 50) -> list[KalshiMarket]:
        """Convenience: aggregate markets across all open IPL events.

        Calls `/events` once (cheap), then `/markets?event_ticker=...` per event.
        For ~30 IPL events this is ~31 requests — well under the 18/sec limit.
        """
        if not self._authed:
            return self._mock_markets()
        events = self.list_ipl_events()
        # Prioritize match events over season-long props for the dashboard
        events.sort(key=lambda e: (0 if e.series_ticker == "KXIPLGAME" else 1, e.event_ticker))
        out: list[KalshiMarket] = []
        for ev in events[:max_events]:
            out.extend(self.list_event_markets(ev.event_ticker))
        return out

    @staticmethod
    def _market_from_dict(m: dict) -> KalshiMarket:
        yes_bid = m.get("yes_bid") or m.get("last_price") or 50
        no_bid = m.get("no_bid") or (100 - int(yes_bid))
        return KalshiMarket(
            ticker=m["ticker"],
            event_ticker=m.get("event_ticker", ""),
            title=m.get("title", m.get("yes_sub_title", "")) or m.get("ticker", ""),
            yes_price=int(yes_bid),
            no_price=int(no_bid),
            status=m.get("status", "open"),
            close_time=m.get("close_time"),
            contract_value=normalize_contract_value(m.get("contract_value")),
            metadata={k: v for k, v in m.items() if k not in
                      {"yes_bid", "no_bid", "last_price", "ticker", "event_ticker",
                       "title", "status", "close_time", "contract_value"}},
        )

    def get_market(self, ticker: str) -> KalshiMarket | None:
        if not self._authed:
            return next((m for m in self._mock_markets() if m.ticker == ticker), None)
        resp = self._request("GET", f"/markets/{ticker}")
        if "error" in resp or "market" not in resp:
            return None
        return self._market_from_dict(resp["market"])

    # ── Positions / orders / balance ───────────────────────────────────

    def list_positions(self) -> list[KalshiPosition]:
        if not self._authed:
            return self._mock_positions()
        resp = self._request("GET", "/portfolio/positions", params={"limit": 200})
        if "error" in resp:
            return []
        return [
            KalshiPosition(
                ticker=p["ticker"],
                yes_count=int(p.get("yes_count") or 0),
                no_count=int(p.get("no_count") or 0),
                avg_cost_cents=int(p.get("avg_cost") or 0),
                market_exposure_cents=int(p.get("market_exposure") or 0),
            )
            for p in resp.get("market_positions", resp.get("positions", []))
        ]

    def list_orders(self, *, status: str | None = None, max_pages: int = 25) -> list[KalshiOrder]:
        """Fetch orders from Kalshi /portfolio/orders, paged via cursor."""
        if not self._authed:
            return []
        out: list[KalshiOrder] = []
        cursor: str | None = None
        for _ in range(max_pages):
            params: dict = {"limit": 200}
            if cursor:
                params["cursor"] = cursor
            if status:
                params["status"] = status
            resp = self._request("GET", "/portfolio/orders", params=params)
            if "error" in resp:
                break
            for o in resp.get("orders", []):
                out.append(self._order_from_dict(o))
            cursor = resp.get("cursor")
            if not cursor:
                break
        return out

    def list_fills(self, *, max_pages: int = 25) -> list[KalshiFill]:
        """Fetch executed fills from Kalshi /portfolio/fills."""
        if not self._authed:
            return []
        out: list[KalshiFill] = []
        cursor: str | None = None
        for _ in range(max_pages):
            params: dict = {"limit": 200}
            if cursor:
                params["cursor"] = cursor
            resp = self._request("GET", "/portfolio/fills", params=params)
            if "error" in resp:
                break
            for f in resp.get("fills", []):
                out.append(self._fill_from_dict(f))
            cursor = resp.get("cursor")
            if not cursor:
                break
        return out

    def list_settlements(self, *, max_pages: int = 25) -> list[KalshiSettlement]:
        """Fetch settled markets from Kalshi /portfolio/settlements.

        Applies the paired-position correction (see pnl.realized_pnl) so
        positions that exited via the opposing side don't surface phantom losses.
        """
        if not self._authed:
            return []
        out: list[KalshiSettlement] = []
        cursor: str | None = None
        for _ in range(max_pages):
            params: dict = {"limit": 200}
            if cursor:
                params["cursor"] = cursor
            resp = self._request("GET", "/portfolio/settlements", params=params)
            if "error" in resp:
                break
            for s in resp.get("settlements", []):
                out.append(self._settlement_from_dict(s))
            cursor = resp.get("cursor")
            if not cursor:
                break
        return out

    @staticmethod
    def _order_from_dict(o: dict) -> KalshiOrder:
        side = (o.get("side") or "").lower()
        price_raw = o.get("yes_price") if side == "yes" else o.get("no_price")
        price = int(price_raw or 0)
        return KalshiOrder(
            order_id=o.get("order_id", ""),
            ticker=o.get("ticker", ""),
            side=side,
            action=(o.get("action") or "").lower(),
            status=(o.get("status") or "").lower(),
            count=int(o.get("count") or 0),
            limit_price_cents=price,
            created_time=o.get("created_time", ""),
            last_update_time=o.get("last_update_time", ""),
            metadata={k: v for k, v in o.items() if k not in
                      {"order_id", "ticker", "side", "action", "status",
                       "count", "yes_price", "no_price",
                       "created_time", "last_update_time"}},
        )

    @staticmethod
    def _fill_from_dict(f: dict) -> KalshiFill:
        side = (f.get("side") or "").lower()
        price_raw = f.get("yes_price") if side == "yes" else f.get("no_price")
        price = int(price_raw or 0)
        return KalshiFill(
            trade_id=f.get("trade_id", ""),
            order_id=f.get("order_id", ""),
            ticker=f.get("ticker", ""),
            side=side,
            action=(f.get("action") or "").lower(),
            count=int(f.get("count") or 0),
            price_cents=price,
            is_taker=bool(f.get("is_taker", False)),
            created_time=f.get("created_time", ""),
        )

    @staticmethod
    def _settlement_from_dict(s: dict) -> KalshiSettlement:
        yes_count = int(s.get("yes_count") or 0)
        no_count = int(s.get("no_count") or 0)
        api_revenue = int(s.get("revenue") or 0)
        cost = int(s.get("yes_total_cost") or 0) + int(s.get("no_total_cost") or 0)
        # Apply paired-position correction. realized_pnl adds min(yes,no)*100¢
        # to settlement_revenue — the canonical fix from KalshiTrader 2026-03-02.
        pnl = realized_pnl(
            yes_count=yes_count,
            no_count=no_count,
            cost_cents=cost,
            settlement_revenue_cents=api_revenue,
        )
        return KalshiSettlement(
            ticker=s.get("ticker", ""),
            market_result=(s.get("market_result") or "").lower(),
            revenue_cents=pnl.revenue_cents,
            cost_cents=pnl.cost_cents,
            net_pnl_cents=pnl.net_cents,
            yes_count=yes_count,
            no_count=no_count,
            settled_time=s.get("settled_time", ""),
        )

    def place_limit_order(
        self,
        *,
        ticker: str,
        side: str,             # 'yes' | 'no'
        action: str,           # 'buy' | 'sell'
        count: int,
        limit_price_cents: int,
    ) -> dict:
        if not self._authed:
            return {"order_id": "stub-order", "ticker": ticker, "status": "queued"}
        body: dict = {
            "ticker": ticker,
            "side": side.lower(),
            "action": action.lower(),
            "type": "limit",
            "count": count,
        }
        if side.lower() == "yes":
            body["yes_price"] = limit_price_cents
        else:
            body["no_price"] = limit_price_cents
        return self._request("POST", "/portfolio/orders", body=body)

    def cancel_order(self, order_id: str) -> dict:
        if not self._authed:
            return {"order_id": order_id, "status": "canceled"}
        return self._request("DELETE", f"/portfolio/orders/{order_id}")

    def get_balance(self) -> dict:
        if not self._authed:
            return {"balance": 4287_50, "portfolio_value": 5230_00}
        return self._request("GET", "/portfolio/balance")

    # ── Mocks ──────────────────────────────────────────────────────────

    def _mock_markets(self) -> list[KalshiMarket]:
        return [
            KalshiMarket("KXIPL-26-MUMCHE-MUM",  "KXIPL-26-MUMCHE", "Mumbai Marauders win",
                         62, 39, "open", metadata={"team_a": "MUM", "team_b": "CHE", "kind": "match_winner"}),
            KalshiMarket("KXIPL-26-MUMCHE-OVER", "KXIPL-26-MUMCHE", "Total match runs > 318.5",
                         71, 31, "open", metadata={"team_a": "MUM", "team_b": "CHE", "kind": "total_runs"}),
            KalshiMarket("KXIPL-26-MUMCHE-TOPBAT","KXIPL-26-MUMCHE", "Top batter: R. Sharma",
                         45, 56, "open", metadata={"team_a": "MUM", "team_b": "CHE", "kind": "top_batter"}),
            KalshiMarket("KXIPL-26-MUMCHE-SO",   "KXIPL-26-MUMCHE", "Match goes to super over",
                         9, 92, "open", metadata={"team_a": "MUM", "team_b": "CHE", "kind": "super_over"}),
        ]

    def _mock_positions(self) -> list[KalshiPosition]:
        return [
            KalshiPosition("KXIPL-26-MUMCHE-MUM",  120, 0, 42, 120 * 42),
            KalshiPosition("KXIPL-26-MUMCHE-OVER", 80,  0, 55, 80 * 55),
            KalshiPosition("KXIPL-26-BLRKOL-KOH",  50,  0, 38, 50 * 38),
            KalshiPosition("KXIPL-26-BLRKOL-PP",   60,  0, 47, 60 * 47),
        ]
