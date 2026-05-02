"""Tests for CricApiFeed — mocks the HTTP layer with realistic CricAPI payloads."""

from __future__ import annotations

import logging as _logging
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


_IPL_SERIES_ID = "ipl-series-2026"


def _ipl_series_response():
    """A /series response that contains the IPL entry."""
    return {
        "status": "success",
        "info": {"hitsToday": 1, "hitsLimit": 100},
        "data": [
            {"id": "other-1", "name": "Some Other Tour 2026"},
            {"id": _IPL_SERIES_ID, "name": "Indian Premier League 2026"},
        ],
    }


def _series_info_response(match_list):
    return {
        "status": "success",
        "info": {"hitsToday": 2, "hitsLimit": 100},
        "data": {"info": {}, "matchList": match_list},
    }


def test_live_match_returns_in_progress_ipl_match():
    matches = [
        {
            "id": "ipl-match-42",
            "name": "MI vs CSK, Indian Premier League 2026",
            "matchStarted": True,
            "matchEnded": False,
            "teams": ["Mumbai Indians", "Chennai Super Kings"],
            "score": [
                {"inning": "Chennai Super Kings inn 1", "r": 178, "w": 6, "o": "20.0"},
                {"inning": "Mumbai Indians inn 1", "r": 142, "w": 4, "o": "15.2"},
            ],
            "status": "Mumbai Indians need 37 in 28 balls",
        },
    ]
    feed = CricApiFeed(api_key="test", http=_mock_session({
        "series": _ipl_series_response(),
        "series_info": _series_info_response(matches),
    }))
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


def test_live_match_returns_none_when_no_ipl_match_is_live():
    """All IPL matches in series_info are either finished or future."""
    matches = [
        {"matchStarted": True, "matchEnded": True,
         "teams": ["Mumbai Indians", "Chennai Super Kings"], "score": []},
        {"matchStarted": False, "matchEnded": False,
         "teams": ["Royal Challengers Bengaluru", "Lucknow Super Giants"]},
    ]
    feed = CricApiFeed(api_key="test", http=_mock_session({
        "series": _ipl_series_response(),
        "series_info": _series_info_response(matches),
    }))
    assert feed.live_match() is None


def test_live_match_skips_finished_matches():
    matches = [{
        "matchStarted": True, "matchEnded": True,    # already over
        "teams": ["Mumbai Indians", "Chennai Super Kings"], "score": [],
    }]
    feed = CricApiFeed(api_key="test", http=_mock_session({
        "series": _ipl_series_response(),
        "series_info": _series_info_response(matches),
    }))
    assert feed.live_match() is None


def test_upcoming_fixtures_filters_to_unstarted_and_sorts_by_date():
    matches = [
        # Out-of-order to verify sort
        {"id": "later", "matchStarted": False,
         "teams": ["Mumbai Indians", "Royal Challengers Bengaluru"],
         "venue": "Wankhede", "dateTimeGMT": "2026-05-10T14:00:00"},
        {"id": "soonest", "matchStarted": False,
         "teams": ["Mumbai Indians", "Chennai Super Kings"],
         "venue": "Wankhede", "dateTimeGMT": "2026-05-02T14:00:00"},
        {"id": "started", "matchStarted": True,
         "teams": ["X", "Y"], "venue": "?", "dateTimeGMT": "2026-05-01T14:00:00"},
    ]
    feed = CricApiFeed(api_key="test", http=_mock_session({
        "series": _ipl_series_response(),
        "series_info": _series_info_response(matches),
    }))
    fx = feed.upcoming_fixtures()

    assert [f.match_id for f in fx] == ["soonest", "later"]
    assert fx[0].team_a == "MUM"
    assert fx[0].team_b == "CHE"


def test_match_list_is_cached_within_ttl():
    """Two calls inside the TTL window should hit the API exactly once."""
    matches = [{"matchStarted": False, "teams": ["Mumbai Indians", "Chennai Super Kings"],
                "dateTimeGMT": "2026-05-02T14:00:00"}]
    sess = _mock_session({
        "series": _ipl_series_response(),
        "series_info": _series_info_response(matches),
    })
    feed = CricApiFeed(api_key="test", http=sess, cache_ttl_seconds=60)

    feed.upcoming_fixtures()
    feed.live_match()
    feed.upcoming_fixtures()

    # First call: /series + /series_info. Subsequent calls hit cache only.
    endpoints_hit = [c.args[0].rsplit("/", 1)[-1] for c in sess.get.call_args_list]
    assert endpoints_hit.count("series") == 1
    assert endpoints_hit.count("series_info") == 1


def test_ipl_series_id_pages_when_not_in_first_25():
    """If IPL isn't in the first /series page, the client should page deeper."""
    page0 = {"status": "success", "data": [{"id": "x", "name": "Some Other Tour"}]}
    page1 = {"status": "success", "data": [{"id": _IPL_SERIES_ID, "name": "Indian Premier League 2026"}]}

    sess = MagicMock(spec=requests.Session)
    call_count = {"n": 0}

    def _get(url, params=None, timeout=None):
        endpoint = url.rstrip("/").rsplit("/", 1)[-1]
        resp = MagicMock(); resp.ok = True; resp.status_code = 200; resp.text = ""
        if endpoint == "series":
            offset = params.get("offset", 0)
            resp.json.return_value = page0 if offset == 0 else page1
        elif endpoint == "series_info":
            resp.json.return_value = _series_info_response([])
        else:
            resp.json.return_value = {"status": "success", "data": []}
        call_count["n"] += 1
        return resp

    sess.get.side_effect = _get
    feed = CricApiFeed(api_key="test", http=sess)
    feed.upcoming_fixtures()
    # Should have hit /series at least twice (paged) + /series_info once
    series_calls = [c for c in sess.get.call_args_list if "series" in c.args[0] and "series_info" not in c.args[0]]
    assert len(series_calls) >= 2


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
        "series_points": {"status": "success", "data": []},
        "series_info": {"status": "success", "data": {}},
    }))
    assert feed.standings() == []


def test_standings_uses_series_points_endpoint_with_derived_points():
    """CricAPI /series_points returns wins/loss/ties/nr but no points column.
    We derive: points = 2*wins + ties + nr (T20 league rules)."""
    feed = CricApiFeed(api_key="test", http=_mock_session({
        "series": _ipl_series_response(),
        "series_points": {"status": "success", "data": [
            {"teamname": "Mumbai Indians", "shortname": "MI",
             "matches": 12, "wins": 9, "loss": 3, "ties": 0, "nr": 0},
            {"teamname": "Chennai Super Kings", "shortname": "CSK",
             "matches": 12, "wins": 8, "loss": 4, "ties": 0, "nr": 0},
            {"teamname": "Royal Challengers Bengaluru", "shortname": "RCB",
             "matches": 12, "wins": 7, "loss": 4, "ties": 0, "nr": 1},
        ]},
    }))
    rows = feed.standings()
    assert len(rows) == 3
    # Sorted by derived points desc
    assert rows[0].code == "MUM" and rows[0].points == 18    # 2*9 + 0 + 0
    assert rows[1].code == "CHE" and rows[1].points == 16    # 2*8
    assert rows[2].code == "BLR" and rows[2].points == 15    # 2*7 + 0 + 1 (nr)


def test_standings_falls_back_to_series_info_pointstable():
    """If /series_points returns empty, try /series_info.data.pointsTable."""
    feed = CricApiFeed(api_key="test", http=_mock_session({
        "series": _ipl_series_response(),
        "series_points": {"status": "success", "data": []},
        "series_info": {"status": "success", "data": {
            "pointsTable": [
                {"teamname": "Mumbai Indians", "matches": 12, "wins": 9,
                 "loss": 3, "ties": 0, "nr": 0, "points": 18},
            ],
        }},
    }))
    rows = feed.standings()
    assert len(rows) == 1
    assert rows[0].points == 18


# ── Strict-mode get_feed() ─────────────────────────────────────────────


def _set_cricket_settings(**overrides):
    """Same Settings-override helper as test_kalshi_client uses."""
    from settings import settings as _settings
    originals = {k: getattr(_settings, k) for k in overrides}
    for k, v in overrides.items():
        object.__setattr__(_settings, k, v)

    def _restore():
        for k, v in originals.items():
            object.__setattr__(_settings, k, v)
    return _restore


def test_get_feed_strict_cricapi_no_key_raises():
    """Strict mode + provider=cricapi + missing key → loud failure."""
    from cricket_data import get_feed
    restore = _set_cricket_settings(
        strict_external_services=True,
        cricket_feed_provider="cricapi",
        cricket_feed_api_key="",
    )
    try:
        with pytest.raises(RuntimeError, match="CRICKET_FEED_API_KEY"):
            get_feed()
    finally:
        restore()


def test_get_feed_strict_stub_logs_warning(caplog):
    """Strict mode + provider=stub → still works, but logs WARNING (so prod
    operators see we're running on stub data and not real cricket state)."""
    from cricket_data import get_feed, StubCricketFeed
    restore = _set_cricket_settings(
        strict_external_services=True,
        cricket_feed_provider="stub",
    )
    try:
        with caplog.at_level(_logging.WARNING, logger="cricket_data"):
            feed = get_feed()
        assert isinstance(feed, StubCricketFeed)
        # Must have logged a WARNING-level record mentioning stub.
        warns = [r for r in caplog.records if r.levelno >= _logging.WARNING]
        assert any("stub" in r.getMessage().lower() for r in warns), \
            f"expected a stub-related WARNING, got: {[r.getMessage() for r in warns]}"
    finally:
        restore()


def test_get_feed_non_strict_cricapi_no_key_falls_back_to_stub(caplog):
    """Existing behavior preserved in non-strict mode: missing key → stub +
    a warning. Catches the dev posture where you forgot to set the key."""
    from cricket_data import get_feed, StubCricketFeed
    restore = _set_cricket_settings(
        strict_external_services=False,
        cricket_feed_provider="cricapi",
        cricket_feed_api_key="",
    )
    try:
        with caplog.at_level(_logging.WARNING, logger="cricket_data"):
            feed = get_feed()
        assert isinstance(feed, StubCricketFeed)
        warns = [r for r in caplog.records if r.levelno >= _logging.WARNING]
        assert any("falling back to stub" in r.getMessage().lower() for r in warns)
    finally:
        restore()
