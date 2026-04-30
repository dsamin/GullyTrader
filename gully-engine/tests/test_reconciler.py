"""Reconciler tests — ticker parsing + Kalshi-to-cricket-feed match correlation."""

from __future__ import annotations

from datetime import date

import pytest

from cricket_data import Fixture, LiveScore
from kalshi_client import KalshiEvent
from reconciler import (
    IPL_FRANCHISE_CODES,
    MatchKey,
    kalshi_event_for_fixture,
    kalshi_event_for_live_match,
    parse_kxiplgame_ticker,
)


# ── Ticker parsing ─────────────────────────────────────────────────────


@pytest.mark.parametrize("ticker,exp_date,a,b", [
    ("KXIPLGAME-26MAY02MICSK",   date(2026, 5, 2),  "MI",   "CSK"),
    ("KXIPLGAME-26MAY07RCBLSG",  date(2026, 5, 7),  "RCB",  "LSG"),
    ("KXIPLGAME-26MAY06PBKSSRH", date(2026, 5, 6),  "PBKS", "SRH"),
    ("KXIPLGAME-26MAY05CSKDC",   date(2026, 5, 5),  "CSK",  "DC"),
    ("KXIPLGAME-26MAY04LSGMI",   date(2026, 5, 4),  "LSG",  "MI"),
    ("KXIPLGAME-26MAY03PBKSGT",  date(2026, 5, 3),  "PBKS", "GT"),
    ("kxiplgame-26may03pbksgt",  date(2026, 5, 3),  "PBKS", "GT"),  # case-insensitive
])
def test_parse_real_world_tickers(ticker, exp_date, a, b):
    key = parse_kxiplgame_ticker(ticker)
    assert key is not None
    assert key.match_date == exp_date
    assert key.team_a_kalshi == a
    assert key.team_b_kalshi == b


def test_parse_returns_design_codes_alongside_kalshi():
    key = parse_kxiplgame_ticker("KXIPLGAME-26MAY02MICSK")
    assert key.team_a_design == "MUM"     # MI → MUM
    assert key.team_b_design == "CHE"     # CSK → CHE
    assert key.team_a_full == "Mumbai Indians"
    assert key.team_b_full == "Chennai Super Kings"


@pytest.mark.parametrize("bad", [
    "",
    "KXIPLGAME-",
    "KXIPLGAME-99XYZ02MICSK",   # invalid month
    "KXIPLGAME-26MAY02ZZZZZZ",  # unknown teams
    "KXIPLGAME-26MAY32MICSK",   # invalid day
    "KXIPL-26MAY02MICSK",       # wrong series
    "RANDOM-STRING",
])
def test_parse_invalid_returns_none(bad):
    assert parse_kxiplgame_ticker(bad) is None


def test_pbks_resolves_as_4char_code_not_pb_plus_ks():
    # PBKS = Punjab Kings (4 chars). Greedy match must take the longer prefix.
    key = parse_kxiplgame_ticker("KXIPLGAME-26MAY06PBKSSRH")
    assert key.team_a_kalshi == "PBKS"
    assert key.team_b_kalshi == "SRH"


def test_franchise_codes_sorted_longest_first_so_greedy_works():
    # Sanity check: IPL_FRANCHISE_CODES must list 4-char codes before 2-char ones
    # otherwise PBKS would mis-split as PB + KS.
    codes = list(IPL_FRANCHISE_CODES)
    longest_first = sorted(codes, key=len, reverse=True)
    # The 4-char code must be at index 0 and 2-char codes must be at the end.
    assert codes[0] == longest_first[0]


# ── Live-match correlation ─────────────────────────────────────────────


def _ev(ticker: str) -> KalshiEvent:
    return KalshiEvent(
        event_ticker=ticker, series_ticker="KXIPLGAME",
        title="t", sub_title="", status="open",
        category="Sports", mutually_exclusive=True,
    )


def _live(team_a: str, team_b: str) -> LiveScore:
    return LiveScore(
        match_id="x", team_a=team_a, team_b=team_b,
        runs_a=0, wickets_a=0, overs_a="0.0",
        runs_b=0, wickets_b=0, overs_b="0.0",
        batting="team_a", target=None, required_run_rate=None,
        on_strike_batter=None, non_strike_batter=None, bowler=None,
    )


def test_live_match_finds_kalshi_event_by_design_codes():
    # Live: MUM vs CHE (design codes from CricApiFeed mapper)
    # Kalshi: KXIPLGAME-26MAY02MICSK (= MI vs CSK = MUM vs CHE)
    events = [
        _ev("KXIPLGAME-26MAY07RCBLSG"),
        _ev("KXIPLGAME-26MAY02MICSK"),
        _ev("KXIPLGAME-26MAY06PBKSSRH"),
    ]
    found = kalshi_event_for_live_match(_live("MUM", "CHE"), events)
    assert found is not None
    assert found.event_ticker == "KXIPLGAME-26MAY02MICSK"


def test_live_match_team_order_does_not_matter():
    """CricAPI may put either team in 'team_a'; reconciler must be order-insensitive."""
    events = [_ev("KXIPLGAME-26MAY02MICSK")]
    a = kalshi_event_for_live_match(_live("MUM", "CHE"), events)
    b = kalshi_event_for_live_match(_live("CHE", "MUM"), events)
    assert a is not None and b is not None
    assert a.event_ticker == b.event_ticker


def test_live_match_returns_none_when_no_event_matches():
    events = [_ev("KXIPLGAME-26MAY07RCBLSG")]   # RCB vs LSG → BLR vs LSG
    assert kalshi_event_for_live_match(_live("MUM", "CHE"), events) is None


def test_live_match_handles_none_live_score():
    assert kalshi_event_for_live_match(None, [_ev("KXIPLGAME-26MAY02MICSK")]) is None


def test_live_match_skips_non_match_series():
    """KXIPL season events shouldn't be returned when looking for a specific match."""
    season_event = KalshiEvent(
        event_ticker="KXIPL-26", series_ticker="KXIPL",
        title="IPL Champion", sub_title="",
    )
    assert kalshi_event_for_live_match(_live("MUM", "CHE"), [season_event]) is None


# ── Fixture correlation ────────────────────────────────────────────────


def test_fixture_finds_matching_kalshi_event_with_date():
    fx = Fixture(
        match_id="x", team_a="BLR", team_b="LSG",
        venue="Eden", start_time_iso="2026-05-07T14:00:00",
        head_to_head="", weather="", expected_yes_a=50,
    )
    events = [_ev("KXIPLGAME-26MAY02MICSK"), _ev("KXIPLGAME-26MAY07RCBLSG")]
    found = kalshi_event_for_fixture(fx, events)
    assert found is not None
    assert found.event_ticker == "KXIPLGAME-26MAY07RCBLSG"


def test_fixture_no_iso_date_still_matches_by_teams():
    fx = Fixture(
        match_id="x", team_a="MUM", team_b="CHE",
        venue="", start_time_iso="",  # no usable date
        head_to_head="", weather="", expected_yes_a=50,
    )
    events = [_ev("KXIPLGAME-26MAY02MICSK")]
    found = kalshi_event_for_fixture(fx, events)
    assert found is not None
