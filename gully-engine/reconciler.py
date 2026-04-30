"""Reconcile Kalshi events with cricket-feed live/upcoming matches.

Kalshi encodes match metadata directly in the event ticker:

    KXIPLGAME-26MAY02MICSK   → 2026-05-02, Mumbai Indians vs Chennai Super Kings
    KXIPLGAME-26MAY07RCBLSG  → 2026-05-07, Royal Challengers Bengaluru vs Lucknow Super Giants
    KXIPLGAME-26MAY06PBKSSRH → 2026-05-06, Punjab Kings vs Sunrisers Hyderabad

The franchise abbreviations are 2–4 chars and concatenated with no separator,
so we greedy-split against a known set of IPL franchise codes.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date, datetime

from cricket_data import LiveScore, Fixture
from kalshi_client import KalshiEvent


log = logging.getLogger(__name__)


# Kalshi-flavor franchise abbreviations (2–4 chars), longer first to greedy-match.
# Sorted longest-first so PBKS matches before any 2-letter substring of it.
IPL_FRANCHISE_CODES = (
    "PBKS",          # Punjab Kings
    "RCB", "KKR", "CSK", "SRH", "LSG",
    "MI", "RR", "GT", "DC",
)


# Map Kalshi franchise code → the 3-letter "design" code used by primitives.jsx.
# (The dashboard uses MUM/CHE/etc. for original-franchise neutrality.)
KALSHI_TO_DESIGN_CODE = {
    "MI":   "MUM",
    "CSK":  "CHE",
    "RCB":  "BLR",
    "KKR":  "KOL",
    "DC":   "DEL",
    "PBKS": "PUN",
    "SRH":  "HYD",
    "RR":   "RAJ",
    "LSG":  "LSG",
    "GT":   "GUJ",
}


# Map Kalshi franchise → full franchise name (canonical 2026 names).
KALSHI_TO_FRANCHISE = {
    "MI":   "Mumbai Indians",
    "CSK":  "Chennai Super Kings",
    "RCB":  "Royal Challengers Bengaluru",
    "KKR":  "Kolkata Knight Riders",
    "DC":   "Delhi Capitals",
    "PBKS": "Punjab Kings",
    "SRH":  "Sunrisers Hyderabad",
    "RR":   "Rajasthan Royals",
    "LSG":  "Lucknow Super Giants",
    "GT":   "Gujarat Titans",
}


_TICKER_RE = re.compile(
    r"^KXIPLGAME-(?P<yy>\d{2})(?P<mon>[A-Z]{3})(?P<dd>\d{2})(?P<teams>[A-Z]+)$"
)
_MONTHS = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}


@dataclass(frozen=True)
class MatchKey:
    """Normalized identity for a match — used to correlate across providers."""
    match_date: date
    team_a_kalshi: str         # "MI", "CSK", etc.
    team_b_kalshi: str
    team_a_design: str         # "MUM", "CHE", etc.
    team_b_design: str
    team_a_full: str           # "Mumbai Indians"
    team_b_full: str


def _split_team_codes(blob: str) -> tuple[str, str] | None:
    """Greedy split a concatenated team-code string like 'MICSK' → ('MI', 'CSK').

    Tries the longest known prefix first so 'PBKSSRH' resolves as PBKS+SRH
    rather than PB+KSSRH (and PB isn't a code anyway).
    """
    for code_a in IPL_FRANCHISE_CODES:
        if blob.startswith(code_a):
            rest = blob[len(code_a):]
            if rest in IPL_FRANCHISE_CODES:
                return code_a, rest
    return None


def parse_kxiplgame_ticker(event_ticker: str) -> MatchKey | None:
    """Parse `KXIPLGAME-{YY}{MMM}{DD}{TEAMS}` into a MatchKey, or None."""
    m = _TICKER_RE.match(event_ticker.strip().upper())
    if not m:
        return None
    try:
        year = 2000 + int(m.group("yy"))
        mon = _MONTHS[m.group("mon")]
        day = int(m.group("dd"))
        match_date = date(year, mon, day)
    except (KeyError, ValueError):
        log.debug("reconciler: invalid date in ticker %s", event_ticker)
        return None

    teams = _split_team_codes(m.group("teams"))
    if not teams:
        log.debug("reconciler: could not split team codes in %s", event_ticker)
        return None
    a, b = teams
    return MatchKey(
        match_date=match_date,
        team_a_kalshi=a, team_b_kalshi=b,
        team_a_design=KALSHI_TO_DESIGN_CODE.get(a, a[:3]),
        team_b_design=KALSHI_TO_DESIGN_CODE.get(b, b[:3]),
        team_a_full=KALSHI_TO_FRANCHISE.get(a, a),
        team_b_full=KALSHI_TO_FRANCHISE.get(b, b),
    )


def kalshi_event_for_live_match(
    live: LiveScore | None,
    events: list[KalshiEvent],
) -> KalshiEvent | None:
    """Find the KXIPLGAME event matching a live cricket-feed match by team codes.

    Match condition: same two design codes (order-insensitive) AND today's date
    OR the soonest future date if no match found today.
    """
    if not live:
        return None
    today = datetime.utcnow().date()
    matched_today: KalshiEvent | None = None
    matched_future: tuple[date, KalshiEvent] | None = None

    target = {live.team_a, live.team_b}
    for ev in events:
        if ev.series_ticker != "KXIPLGAME":
            continue
        key = parse_kxiplgame_ticker(ev.event_ticker)
        if not key:
            continue
        teams = {key.team_a_design, key.team_b_design}
        if teams != target:
            continue
        if key.match_date == today:
            return ev
        if key.match_date > today and (matched_future is None or key.match_date < matched_future[0]):
            matched_future = (key.match_date, ev)

    return matched_future[1] if matched_future else matched_today


def kalshi_event_for_fixture(
    fixture: Fixture,
    events: list[KalshiEvent],
) -> KalshiEvent | None:
    """Find the KXIPLGAME event matching an upcoming-fixture entry."""
    target = {fixture.team_a, fixture.team_b}
    fixture_date: date | None = None
    if fixture.start_time_iso:
        try:
            fixture_date = datetime.fromisoformat(
                fixture.start_time_iso.replace("Z", "+00:00")
            ).date()
        except ValueError:
            pass

    for ev in events:
        if ev.series_ticker != "KXIPLGAME":
            continue
        key = parse_kxiplgame_ticker(ev.event_ticker)
        if not key:
            continue
        teams = {key.team_a_design, key.team_b_design}
        if teams != target:
            continue
        if fixture_date is None or key.match_date == fixture_date:
            return ev
    return None
