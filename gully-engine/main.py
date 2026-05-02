"""FastAPI app — serves the dashboard and REST endpoints.

Routes:
    GET /                              → dashboard (static index.html)
    GET /static/*                      → JSX/CSS assets
    GET /api/portfolio                 → balance, day P&L, ROI ring
    GET /api/positions                 → open + recently settled
    GET /api/match/live                → current live match (or null)
    GET /api/match/{match_id}/markets  → markets attached to a match
    GET /api/fixtures                  → upcoming fixtures
    GET /api/standings                 → IPL points table
    GET /api/bot/status                → autotrader status pill data
    POST /api/bot/toggle               → toggle autotrader on/off
    POST /api/orders                   → place a limit order
    POST /api/orchestrator/run-entry   → manual entry pipeline trigger
    POST /api/orchestrator/run-exit    → manual exit monitor trigger
"""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import database
import orchestrator
import portfolio
import sync_service
from cricket_data import get_feed
from kalshi_client import KalshiClient
from pnl import normalize_position_side, position_contract_count
from reconciler import (
    kalshi_event_for_fixture,
    kalshi_event_for_live_match,
)
from settings import settings


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s :: %(message)s")
log = logging.getLogger("gullytrader")

STATIC_DIR = Path(__file__).parent / "static"


# ── Lifecycle ─────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("startup: initializing DB at %s", settings.db_path)
    database.initialize()
    purged = database.purge_old_agent_logs()
    log.info("startup: purged %d old agent_logs rows", purged)

    if settings.enable_orchestrator:
        sync_service.start_in_thread()
        orchestrator.start_threads()
    else:
        log.info("startup: orchestrator disabled (GULLYTRADER_ENABLE_ORCHESTRATOR=0)")

    yield

    log.info("shutdown: stopping orchestrator + sync")
    orchestrator.stop()
    sync_service.stop()


app = FastAPI(title="GullyTrader", version="0.1.0", lifespan=lifespan)


# ── Static frontend ────────────────────────────────────────────────────


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", include_in_schema=False)
async def root() -> FileResponse:
    return FileResponse(str(STATIC_DIR / "index.html"))


# ── API ────────────────────────────────────────────────────────────────


@app.get("/api/portfolio")
async def get_portfolio() -> dict:
    client = KalshiClient()
    bal = client.get_balance()
    metrics = portfolio.compute_metrics()
    return {
        "balance_cents": bal.get("balance", 0),
        "portfolio_value_cents": bal.get("portfolio_value", 0),
        **metrics,
    }


@app.get("/api/positions")
async def list_positions() -> dict:
    client = KalshiClient()
    raw = client.list_positions()
    open_positions = []
    for p in raw:
        side = normalize_position_side(p.yes_count, p.no_count)
        contracts = position_contract_count(p.yes_count, p.no_count)
        effective_side = side if side != "paired" else "yes"

        # Real mark price from Kalshi. If the market isn't returnable
        # (delisted, transient API miss), fall back to entry price → 0 P&L.
        market = None
        try:
            market = client.get_market(p.ticker)
        except Exception:
            log.exception("api.positions: get_market failed for %s", p.ticker)
        if market is not None:
            mark = market.yes_price if effective_side == "yes" else market.no_price
        else:
            mark = p.avg_cost_cents
        pnl = (mark - p.avg_cost_cents) * contracts

        open_positions.append(
            {
                "ticker": p.ticker,
                "title": (market.title if market else p.ticker),
                "match": _match_label(p.ticker),
                "side": effective_side,
                "entry_cents": p.avg_cost_cents,
                "mark_cents": mark,
                "contracts": contracts,
                "pnl_cents": pnl,
                "exit_chip": "TP near" if pnl > 1500 else ("SL hit" if pnl < -300 else "Hold"),
            }
        )

    settled = portfolio.recent_settled_positions()
    active_cents = sum(p["entry_cents"] * p["contracts"] for p in open_positions)
    return {
        "open": open_positions,
        "settled": settled,
        "totals": {
            "active_dollars": round(active_cents / 100.0, 2),
            "today_pnl_cents": portfolio.compute_metrics()["day_pnl_abs_cents"],
        },
    }


@app.get("/api/trades")
async def list_trades(limit: int = 50) -> dict:
    """Recent fills (executions) — populated by sync_service from Kalshi."""
    return {"trades": portfolio.recent_fills(limit=limit)}


@app.get("/api/match/live")
async def get_live_match() -> dict:
    """Live cricket state plus the matching Kalshi event_ticker if found.

    The frontend uses `kalshi_event_ticker` to deep-link from the dashboard's
    "Live now" strip into match centre / bet sheet without re-resolving.
    """
    feed = get_feed()
    live = feed.live_match()
    if not live:
        return {"live": None}

    kalshi_ev = None
    try:
        kalshi_ev = kalshi_event_for_live_match(live, KalshiClient().list_ipl_events())
    except Exception:
        log.exception("api.live: kalshi reconciliation failed (non-fatal)")

    return {
        "live": {
            "match_id": live.match_id,
            "team_a": live.team_a, "team_b": live.team_b,
            "runs_a": live.runs_a, "wickets_a": live.wickets_a, "overs_a": live.overs_a,
            "runs_b": live.runs_b, "wickets_b": live.wickets_b, "overs_b": live.overs_b,
            "target": live.target, "required_run_rate": live.required_run_rate,
            "on_strike_batter": live.on_strike_batter,
            "non_strike_batter": live.non_strike_batter,
            "bowler": live.bowler,
            "last_balls": live.last_balls,
            "win_probability_a": live.win_probability_a,
            "status_text": live.status_text,
            "kalshi_event_ticker": kalshi_ev.event_ticker if kalshi_ev else None,
        }
    }


@app.get("/api/match/{event_ticker}/markets")
async def get_match_markets(event_ticker: str) -> dict:
    """Markets for a single Kalshi event (e.g. KXIPLGAME-26MAY07RCBLSG)."""
    client = KalshiClient()
    markets = client.list_event_markets(event_ticker)
    return {
        "event_ticker": event_ticker,
        "markets": [
            {
                "ticker": m.ticker,
                "title": m.title or m.metadata.get("yes_sub_title", ""),
                "yes": m.yes_price,
                "no": m.no_price,
                "kind": m.metadata.get("yes_sub_title", "")
                        or m.metadata.get("kind", "winner"),
                "you_in": False,
                "hot": False,
            }
            for m in markets
        ],
    }


@app.get("/api/events/ipl")
async def list_ipl_events() -> dict:
    """All open IPL events on Kalshi (matches, season, playoffs, props)."""
    client = KalshiClient()
    events = client.list_ipl_events()
    return {
        "events": [
            {
                "event_ticker": e.event_ticker,
                "series_ticker": e.series_ticker,
                "title": e.title,
                "sub_title": e.sub_title,
                "status": e.status,
                "category": e.category,
                "is_match": e.series_ticker == "KXIPLGAME",
            }
            for e in events
        ],
    }


@app.get("/api/fixtures")
async def get_fixtures() -> dict:
    """Upcoming fixtures with the matching Kalshi event_ticker attached when known."""
    feed = get_feed()
    fixtures = feed.upcoming_fixtures()

    kalshi_events = []
    try:
        kalshi_events = KalshiClient().list_ipl_events()
    except Exception:
        log.exception("api.fixtures: kalshi reconciliation failed (non-fatal)")

    out = []
    for f in fixtures:
        ev = kalshi_event_for_fixture(f, kalshi_events) if kalshi_events else None
        out.append({
            "match_id": f.match_id,
            "team_a": f.team_a, "team_b": f.team_b,
            "venue": f.venue, "start_time": f.start_time_iso,
            "head_to_head": f.head_to_head, "weather": f.weather,
            "expected_yes_a": f.expected_yes_a,
            "is_hot": f.is_hot,
            "kalshi_event_ticker": ev.event_ticker if ev else None,
        })
    return {"fixtures": out}


@app.get("/api/standings")
async def get_standings() -> dict:
    feed = get_feed()
    return {
        "rows": [
            {
                "code": r.code, "name": r.name,
                "played": r.played, "wins": r.wins, "losses": r.losses,
                "points": r.points, "nrr": r.nrr,
                "last_5": r.last_5,
                "playoff_probability": r.playoff_probability,
            }
            for r in feed.standings()
        ]
    }


@app.get("/api/bot/status")
async def get_bot_status() -> dict:
    return {
        "active": settings.enable_orchestrator,
        "mode": settings.exit_mode,
        "last_action": "bought MUM YES @ 58¢",
        "last_action_seconds_ago": 120,
        "scanner_model": settings.scanner_model,
        "decision_model": settings.decision_model,
        "exit_model": settings.exit_model,
    }


class BotToggleBody(BaseModel):
    active: bool


@app.post("/api/bot/toggle")
async def toggle_bot(body: BotToggleBody) -> dict:
    # In a real impl this would flip an env-backed flag, restart threads, etc.
    return {"active": body.active, "note": "stub — threads not actually toggled"}


class OrderBody(BaseModel):
    ticker: str
    side: str           # 'yes' | 'no'
    action: str         # 'buy' | 'sell'
    count: int
    limit_price_cents: int


@app.post("/api/orders")
async def place_order(body: OrderBody) -> dict:
    if body.side not in {"yes", "no"} or body.action not in {"buy", "sell"}:
        raise HTTPException(400, "invalid side/action")
    client = KalshiClient()
    return client.place_limit_order(
        ticker=body.ticker, side=body.side, action=body.action,
        count=body.count, limit_price_cents=body.limit_price_cents,
    )


@app.post("/api/orchestrator/run-entry")
async def trigger_entry() -> dict:
    return orchestrator.run_entry_pipeline_once(force=True)


@app.post("/api/orchestrator/run-exit")
async def trigger_exit() -> dict:
    return orchestrator.run_exit_monitor_once(force=True)


# ── helpers ────────────────────────────────────────────────────────────


def _match_label(ticker: str) -> str:
    """Best-effort match label parsed from a Kalshi ticker.

    Real IPL match tickers look like `KXIPLGAME-26MAY07RCBLSG-LSG` — the
    middle segment encodes both teams. We extract them when possible; fall
    back to the raw ticker otherwise.
    """
    parts = ticker.split("-")
    if len(parts) >= 2 and len(parts[1]) >= 6:
        # date prefix like "26MAY07" then 6 alphabetic team chars
        seg = parts[1]
        # find the index where the alphabetic team-pair starts
        for i in range(len(seg) - 5):
            if seg[i:i + 6].isalpha():
                team_a, team_b = seg[i:i + 3], seg[i + 3:i + 6]
                return f"{team_a}·{team_b}"
    return "—"
