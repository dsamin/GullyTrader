"""Pluggable cricket data feed.

Provides ball-by-ball state, fixtures, standings, and head-to-head data for the
LLM agents and the dashboard. The base class defines the contract; the default
implementation is a stub that returns realistic IPL mock data.

Live providers:
    CRICKET_FEED_PROVIDER=stub      → StubCricketFeed (default; design's mock figures)
    CRICKET_FEED_PROVIDER=cricapi   → CricApiFeed (cricketdata.org / api.cricapi.com)

CricAPI free tier is 100 hits/day — fine for development, too small for live
polling during a match. Upgrade to the $12.99/mo M plan (10K hits/day) before
flipping the bot to live mode.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Protocol

import requests

from settings import settings


log = logging.getLogger(__name__)


@dataclass
class LiveScore:
    match_id: str
    team_a: str
    team_b: str
    runs_a: int
    wickets_a: int
    overs_a: str          # "15.2" format
    runs_b: int
    wickets_b: int
    overs_b: str
    batting: str          # team_a | team_b
    target: int | None
    required_run_rate: float | None
    on_strike_batter: dict | None       # {"name", "runs", "balls", "sr"}
    non_strike_batter: dict | None
    bowler: dict | None                 # {"name", "overs", "runs", "wickets", "economy"}
    last_balls: list[str] = field(default_factory=list)   # ['1','4','W','•','6',...]
    win_probability_a: int | None = None     # 0-100
    status_text: str = ""


@dataclass
class Fixture:
    match_id: str
    team_a: str
    team_b: str
    venue: str
    start_time_iso: str
    head_to_head: str
    weather: str
    expected_yes_a: int     # implied % from H2H/form
    is_hot: bool = False


@dataclass
class StandingsRow:
    code: str
    name: str
    played: int
    wins: int
    losses: int
    points: int
    nrr: str            # signed string e.g. "+0.842"
    last_5: list[str]   # ['W','W','L','W','W']
    playoff_probability: int  # 0-100


class CricketFeed(Protocol):
    def live_match(self) -> LiveScore | None: ...
    def upcoming_fixtures(self) -> list[Fixture]: ...
    def standings(self) -> list[StandingsRow]: ...


class StubCricketFeed:
    """Hardcoded mock data — matches the design's reference figures.

    The values here are deliberately the same as the design prototype so the
    UI looks identical when running against the stub.
    """

    def live_match(self) -> LiveScore | None:
        return LiveScore(
            match_id="ipl-2026-mumche-32",
            team_a="MUM",
            team_b="CHE",
            runs_a=142, wickets_a=4, overs_a="15.2",
            runs_b=178, wickets_b=6, overs_b="20.0",
            batting="team_a",
            target=178,
            required_run_rate=7.71,
            on_strike_batter={"name": "R. Sharma", "runs": 64, "balls": 42, "sr": "152.4"},
            non_strike_batter={"name": "S. Yadav", "runs": 28, "balls": 18, "sr": "155.6"},
            bowler={"name": "J. Bumrah", "overs": "3.2", "runs": 22, "wickets": 1, "economy": "6.88"},
            last_balls=["1", "4", "0", "6", "W", "•", "LB", "2", "4", "1", "6", "0", "WD", "1"],
            win_probability_a=62,
            status_text="MUM need 36 runs in 28 balls · RRR 7.71",
        )

    def upcoming_fixtures(self) -> list[Fixture]:
        return [
            Fixture("ipl-2026-blrkol", "BLR", "KOL", "Eden Gardens", "2026-04-30T19:30:00+05:30", "BLR 4-3", "24°C clear", 51, is_hot=True),
            Fixture("ipl-2026-delpun", "DEL", "PUN", "Kotla",        "2026-05-01T15:30:00+05:30", "DEL 5-2", "36°C dry",   58),
            Fixture("ipl-2026-hydraj", "HYD", "RAJ", "Uppal",        "2026-05-01T19:30:00+05:30", "HYD 6-3", "32°C humid", 67),
            Fixture("ipl-2026-mumkol", "MUM", "KOL", "Wankhede",     "2026-05-02T19:30:00+05:30", "MUM 7-4", "29°C dew",   54),
        ]

    def standings(self) -> list[StandingsRow]:
        return [
            StandingsRow("MUM", "Mumbai Marauders",  12, 9, 3, 18, "+0.842", ["W","W","L","W","W"], 96),
            StandingsRow("CHE", "Chennai Crowns",    12, 8, 4, 16, "+0.621", ["W","L","W","W","W"], 88),
            StandingsRow("BLR", "Bengaluru Bolts",   12, 7, 5, 14, "+0.310", ["L","W","W","L","W"], 71),
            StandingsRow("KOL", "Kolkata Kings",     12, 7, 5, 14, "+0.114", ["W","W","L","L","W"], 65),
            StandingsRow("DEL", "Delhi Daredevils",  12, 6, 6, 12, "-0.052", ["L","W","L","W","W"], 42),
            StandingsRow("PUN", "Punjab Pulse",      12, 5, 7, 10, "-0.187", ["L","L","W","W","L"], 18),
            StandingsRow("HYD", "Hyderabad Hawks",   12, 4, 8,  8, "-0.412", ["L","L","W","L","L"],  6),
            StandingsRow("RAJ", "Rajasthan Royals",  12, 2,10,  4, "-1.122", ["L","L","L","L","W"],  0),
        ]


# ── CricAPI / cricketdata.org ────────────────────────────────────────


# Map IPL franchise full names → 3-letter team codes used by the design.
# Both common spellings of each franchise are listed (CricAPI returns the full
# franchise name; we have to collapse it).
_TEAM_CODE_BY_NAME = {
    "mumbai indians": "MUM", "mumbai marauders": "MUM",
    "chennai super kings": "CHE", "chennai crowns": "CHE",
    "royal challengers bengaluru": "BLR", "royal challengers bangalore": "BLR",
    "bengaluru bolts": "BLR",
    "kolkata knight riders": "KOL", "kolkata kings": "KOL",
    "delhi capitals": "DEL", "delhi daredevils": "DEL",
    "punjab kings": "PUN", "punjab pulse": "PUN", "kings xi punjab": "PUN",
    "sunrisers hyderabad": "HYD", "hyderabad hawks": "HYD",
    "rajasthan royals": "RAJ",
    "lucknow super giants": "LSG",
    "gujarat titans": "GUJ",
}


def _team_code(name: str | None) -> str:
    if not name:
        return "???"
    key = name.strip().lower()
    if key in _TEAM_CODE_BY_NAME:
        return _TEAM_CODE_BY_NAME[key]
    # Fall back to: take initials of significant words (Mumbai Indians → MI,
    # but with a 3-letter pad for legibility).
    words = [w for w in re.findall(r"[A-Za-z]+", name) if w.lower() not in {"the", "of"}]
    if not words:
        return "???"
    if len(words) == 1:
        return words[0][:3].upper()
    return (words[0][:1] + words[1][:2]).upper()


class CricApiFeed:
    """Cricket data via CricAPI (cricketdata.org).

    Free tier is 100 hits/day; the M tier ($12.99/mo) is 10K/day. Calls are
    counted per HTTP request to /v1/* — `.live_match()` does at most 2.

    Defensive: this client tolerates response-shape variation. On any error
    (network, HTTP 4xx, missing key, malformed payload) it logs and returns
    None / empty list rather than blowing up the caller.
    """

    BASE_URL = "https://api.cricapi.com/v1"
    IPL_KEYWORDS = ("indian premier league", "ipl")

    def __init__(self, api_key: str, *, base_url: str | None = None,
                 http: requests.Session | None = None) -> None:
        if not api_key:
            log.warning("CricApiFeed instantiated without an API key — calls will fail")
        self.api_key = api_key
        self.base_url = (base_url or self.BASE_URL).rstrip("/")
        self.http = http or requests.Session()

    # ── HTTP plumbing ──────────────────────────────────────────────────

    def _get(self, endpoint: str, **params: Any) -> dict:
        params["apikey"] = self.api_key
        url = f"{self.base_url}/{endpoint}"
        try:
            r = self.http.get(url, params=params, timeout=10)
        except requests.RequestException as e:
            log.error("CricAPI request failed [%s]: %s", endpoint, e)
            return {}
        if not r.ok:
            log.warning("CricAPI %s returned %s: %s", endpoint, r.status_code, r.text[:200])
            return {}
        try:
            payload = r.json()
        except ValueError:
            log.warning("CricAPI %s: non-JSON response", endpoint)
            return {}
        if isinstance(payload, dict):
            status = payload.get("status", "")
            if status and status != "success":
                log.warning("CricAPI %s status=%s reason=%s",
                            endpoint, status, payload.get("reason", "(none)"))
            info = payload.get("info") or {}
            if info.get("hitsToday") is not None:
                log.debug("CricAPI quota: %s/%s today",
                          info.get("hitsToday"), info.get("hitsLimit"))
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _is_ipl(name: str | None) -> bool:
        if not name:
            return False
        n = name.lower()
        return any(k in n for k in CricApiFeed.IPL_KEYWORDS)

    # ── Public API (matches CricketFeed protocol) ──────────────────────

    def live_match(self) -> LiveScore | None:
        """First in-progress IPL match, if any."""
        resp = self._get("currentMatches", offset=0)
        for m in resp.get("data") or []:
            series = m.get("series") or m.get("name") or ""
            if not self._is_ipl(series):
                continue
            if not (m.get("matchStarted") and not m.get("matchEnded")):
                continue
            return self._to_live_score(m)
        return None

    def upcoming_fixtures(self) -> list[Fixture]:
        """Next IPL fixtures that haven't started yet."""
        resp = self._get("matches", offset=0)
        out: list[Fixture] = []
        for m in resp.get("data") or []:
            if not self._is_ipl(m.get("series") or m.get("name")):
                continue
            if m.get("matchStarted"):
                continue
            try:
                out.append(self._to_fixture(m))
            except Exception as e:  # noqa: BLE001 — single bad row shouldn't kill the list
                log.warning("CricAPI fixture parse failed for %s: %s", m.get("id"), e)
        return out

    def standings(self) -> list[StandingsRow]:
        """IPL points table.

        Implementation note: CricAPI exposes points-table data via the series
        endpoints, but the schema isn't stable across seasons. Returning an
        empty list when we can't find the IPL series is safer than guessing.
        """
        resp = self._get("series", offset=0)
        ipl_series_id = None
        for s in resp.get("data") or []:
            if self._is_ipl(s.get("name")):
                ipl_series_id = s.get("id")
                break
        if not ipl_series_id:
            return []
        info = self._get("series_info", id=ipl_series_id)
        rows: list[StandingsRow] = []
        # CricAPI returns points table under various keys depending on season —
        # try a few. If none match, return an empty list rather than raising.
        table = (info.get("data") or {}).get("pointsTable") \
                or info.get("pointsTable") \
                or []
        for r in table:
            try:
                rows.append(StandingsRow(
                    code=_team_code(r.get("teamname") or r.get("name")),
                    name=r.get("teamname") or r.get("name") or "?",
                    played=int(r.get("matches") or r.get("played") or 0),
                    wins=int(r.get("wins") or 0),
                    losses=int(r.get("losses") or r.get("loss") or 0),
                    points=int(r.get("points") or 0),
                    nrr=str(r.get("netrunrate") or r.get("nrr") or "0.000"),
                    last_5=[],   # CricAPI's free tier doesn't include form history
                    playoff_probability=0,
                ))
            except (ValueError, TypeError) as e:
                log.warning("CricAPI standings row parse failed: %s", e)
        return rows

    # ── Mappers ────────────────────────────────────────────────────────

    @staticmethod
    def _to_live_score(m: dict) -> LiveScore:
        """Map a CricAPI match record to our LiveScore dataclass."""
        teams = m.get("teams") or []
        team_a = teams[0] if len(teams) >= 1 else m.get("team1", "?")
        team_b = teams[1] if len(teams) >= 2 else m.get("team2", "?")

        # Score is a list of innings dicts: [{"r": runs, "w": wkts, "o": overs, "inning": ...}, ...]
        score = m.get("score") or []
        runs_a = wkts_a = 0
        overs_a = "0.0"
        runs_b = wkts_b = 0
        overs_b = "0.0"
        for innings in score:
            inn = (innings.get("inning") or "").lower()
            r = int(innings.get("r") or 0)
            w = int(innings.get("w") or 0)
            o = str(innings.get("o") or "0.0")
            if team_a.lower() in inn:
                runs_a, wkts_a, overs_a = r, w, o
            elif team_b.lower() in inn:
                runs_b, wkts_b, overs_b = r, w, o

        # Status text (e.g. "Mumbai Indians need 36 runs in 28 balls")
        status_text = m.get("status") or m.get("statusText") or ""
        target = None
        rrr = None
        if score and len(score) >= 2:
            # Best-effort target = first innings runs + 1
            first = score[0]
            target = int(first.get("r") or 0) + 1

        return LiveScore(
            match_id=str(m.get("id") or ""),
            team_a=_team_code(team_a),
            team_b=_team_code(team_b),
            runs_a=runs_a, wickets_a=wkts_a, overs_a=overs_a,
            runs_b=runs_b, wickets_b=wkts_b, overs_b=overs_b,
            batting="team_a" if runs_a < (target or 0) else "team_b",
            target=target,
            required_run_rate=rrr,
            on_strike_batter=None,    # CricAPI free tier doesn't expose this
            non_strike_batter=None,
            bowler=None,
            last_balls=[],
            win_probability_a=None,
            status_text=status_text,
        )

    @staticmethod
    def _to_fixture(m: dict) -> Fixture:
        teams = m.get("teams") or []
        team_a = teams[0] if len(teams) >= 1 else m.get("team1", "?")
        team_b = teams[1] if len(teams) >= 2 else m.get("team2", "?")
        return Fixture(
            match_id=str(m.get("id") or ""),
            team_a=_team_code(team_a),
            team_b=_team_code(team_b),
            venue=m.get("venue") or "",
            start_time_iso=m.get("dateTimeGMT") or m.get("date") or "",
            head_to_head="",
            weather="",
            expected_yes_a=50,
            is_hot=False,
        )


# ── Factory ─────────────────────────────────────────────────────────


def get_feed() -> CricketFeed:
    """Factory — picks an implementation based on CRICKET_FEED_PROVIDER."""
    provider = settings.cricket_feed_provider.lower()
    if provider == "stub":
        return StubCricketFeed()
    if provider == "cricapi":
        if not settings.cricket_feed_api_key:
            log.warning("CRICKET_FEED_PROVIDER=cricapi but CRICKET_FEED_API_KEY is empty — falling back to stub")
            return StubCricketFeed()
        return CricApiFeed(api_key=settings.cricket_feed_api_key)
    # TODO: SportMonks, etc.
    raise NotImplementedError(f"Cricket feed provider '{provider}' not implemented")
