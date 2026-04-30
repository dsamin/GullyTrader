"""Tests for CricApiFeed — mocks the HTTP layer with realistic CricAPI payloads."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
import requests

from cricket_data import CricApiFeed, _team_code


# ── Team-code normalization ────────────────────────────────────────────


@pytest.mark.parametrize("name,expected", [
    ("Mumbai Indians", "MUM"),
    ("MUMBAI INDIANS", "MUM"),
    ("  mumbai indians  ", "MUM"),
    ("Royal Challengers Bengaluru", "BLR"),
    ("Royal Challengers Bangalore", "BLR"),
    ("Lucknow Super Giants", "LSG"),
    ("Sunrisers Hyderabad", "HYD"),
    ("Punjab Kings", "PUN"),
    ("Kolkata Knight Riders", "KOL"),
])
def test_team_code_known_franchises(name, expected):
    assert _team_code(name) == expected


def test_team_code_unknown_falls_back_to_initials():
    # Unknown team → first-word initial + second-word two-letter prefix
    assert _team_code("Some New Team") == "SNE"
    assert _team_code("OneWord") == "ONE"
    assert _team_code(None) == "???"
    assert _team_code("") == "???"


# ── HTTP-mocked feed tests ─────────────────────────────────────────────


def _mock_session(responses_by_endpoint):
    """Build a fake requests.Session that returns canned JSON per endpoint."""
    sess = MagicMock(spec=requests.Session)

    def _get(url, params=None, timeout=None):
        endpoint = url.rstrip("/").rsplit("/", 1)[-1]
        body = responses_by_endpoint.get(endpoint, {"status": "success", "data": []})
        resp = MagicMock()
        resp.ok = True
        resp.status_code = 200
        resp.json.return_value = body
        resp.text = ""
        return resp

    sess.get.side_effect = _get
    return sess


def test_live_match_returns_in_progress_ipl_match():
    payload = {
        "status": "success",
        "info": {"hitsToday": 5, "hitsLimit": 100},
        "data": [
            {
                "id": "non-ipl-1",
                "name": "Some Test Match",
                "series": "Some Bilateral Series",
                "matchStarted": True,
                "matchEnded": False,
                "teams": ["A", "B"],
                "score": [{"inning": "A inn 1", "r": 50, "w": 1, "o": "5.0"}],
            },
            {
                "id": "ipl-match-42",
                "name": "MI vs CSK",
                "series": "Indian Premier League 2026",
                "matchStarted": True,
                "matchEnded": False,
                "teams": ["Mumbai Indians", "Chennai Super Kings"],
                "score": [
                    {"inning": "Chennai Super Kings inn 1", "r": 178, "w": 6, "o": "20.0"},
                    {"inning": "Mumbai Indians inn 1", "r": 142, "w": 4, "o": "15.2"},
                ],
                "status": "Mumbai Indians need 37 in 28 balls",
            },
        ],
    }
    feed = CricApiFeed(api_key="test", http=_mock_session({"currentMatches": payload}))
    live = feed.live_match()

    assert live is not None
    assert live.match_id == "ipl-match-42"
    assert live.team_a == "MUM"
    assert live.team_b == "CHE"
    assert live.runs_a == 142
    assert live.wickets_a == 4
    assert live.overs_a == "15.2"
    assert live.runs_b == 178
    assert live.wickets_b == 6
    assert live.target == 179   # first innings 178 + 1
    assert "need 37" in live.status_text


def test_live_match_returns_none_when_no_ipl_in_progress():
    payload = {"status": "success", "data": [
        {"name": "X", "series": "Some Other League", "matchStarted": True,
         "teams": ["A", "B"], "score": []},
    ]}
    feed = CricApiFeed(api_key="test", http=_mock_session({"currentMatches": payload}))
    assert feed.live_match() is None


def test_live_match_skips_finished_matches():
    payload = {"status": "success", "data": [
        {
            "name": "MI vs CSK", "series": "Indian Premier League 2026",
            "matchStarted": True, "matchEnded": True,    # already over
            "teams": ["Mumbai Indians", "Chennai Super Kings"],
            "score": [],
        }
    ]}
    feed = CricApiFeed(api_key="test", http=_mock_session({"currentMatches": payload}))
    assert feed.live_match() is None


def test_upcoming_fixtures_filters_to_unstarted_ipl():
    payload = {"status": "success", "data": [
        {"id": "1", "series": "Indian Premier League 2026",
         "matchStarted": False, "teams": ["Mumbai Indians", "Chennai Super Kings"],
         "venue": "Wankhede", "dateTimeGMT": "2026-05-01T14:00:00"},
        {"id": "2", "series": "BBL", "matchStarted": False,
         "teams": ["Sydney Sixers", "Hobart Hurricanes"]},
        {"id": "3", "series": "Indian Premier League 2026",
         "matchStarted": True, "teams": ["X", "Y"]},   # already started — drop
    ]}
    feed = CricApiFeed(api_key="test", http=_mock_session({"matches": payload}))
    fx = feed.upcoming_fixtures()

    assert len(fx) == 1
    assert fx[0].match_id == "1"
    assert fx[0].team_a == "MUM"
    assert fx[0].team_b == "CHE"
    assert fx[0].venue == "Wankhede"


def test_http_failure_is_handled_gracefully():
    sess = MagicMock(spec=requests.Session)
    sess.get.side_effect = requests.RequestException("network down")
    feed = CricApiFeed(api_key="test", http=sess)

    # Network error → logged, not raised
    assert feed.live_match() is None
    assert feed.upcoming_fixtures() == []
    assert feed.standings() == []


def test_non_2xx_response_is_handled_gracefully():
    sess = MagicMock(spec=requests.Session)
    bad = MagicMock()
    bad.ok = False
    bad.status_code = 429
    bad.text = "rate limit exceeded"
    sess.get.return_value = bad
    feed = CricApiFeed(api_key="test", http=sess)

    assert feed.live_match() is None
    assert feed.upcoming_fixtures() == []


def test_standings_returns_empty_when_no_ipl_series_found():
    feed = CricApiFeed(api_key="test", http=_mock_session({
        "series": {"status": "success", "data": [{"id": "x", "name": "Some Other League"}]},
    }))
    assert feed.standings() == []


def test_standings_parses_rows_when_payload_includes_points_table():
    feed = CricApiFeed(api_key="test", http=_mock_session({
        "series": {"status": "success", "data": [
            {"id": "ipl-2026", "name": "Indian Premier League 2026"}
        ]},
        "series_info": {"status": "success", "data": {
            "pointsTable": [
                {"teamname": "Mumbai Indians", "matches": 12, "wins": 9,
                 "losses": 3, "points": 18, "netrunrate": "+0.842"},
                {"teamname": "Chennai Super Kings", "matches": 12, "wins": 8,
                 "losses": 4, "points": 16, "netrunrate": "+0.621"},
            ],
        }},
    }))
    rows = feed.standings()
    assert len(rows) == 2
    assert rows[0].code == "MUM"
    assert rows[0].name == "Mumbai Indians"
    assert rows[0].played == 12
    assert rows[0].points == 18
    assert rows[0].nrr == "+0.842"
    assert rows[1].code == "CHE"
