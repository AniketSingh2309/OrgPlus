from __future__ import annotations

from datetime import date, timedelta

import pytest

from orgpulse import scoring
from orgpulse.tenancy import DEFAULT_WEIGHTS

D = date(2026, 10, 7)  # a Wednesday


def test_daily_score_is_weighted_sum() -> None:
    rows = [
        (D, "dc", 2),
        (D, "de", 5),
        (D, "dv", 100),
        (D, "es", 4),
        (D, "mh", 1.5),
        (D, "st_used", 9999),
    ]
    # 2*3 + 5*1 + 100*0 + 4*0.5 + 1.5*2; storage is not a score metric
    assert scoring.daily_scores(rows, DEFAULT_WEIGHTS) == {D: pytest.approx(16.0)}


def test_app_scores_are_unweighted_per_app() -> None:
    rows = [(D, "dc", 2), (D, "dv", 10), (D, "es", 4)]
    assert scoring.app_scores(rows, "drive") == {D: 12}
    assert scoring.app_scores(rows, "gmail") == {D: 4}


def test_quartile_levels() -> None:
    values = [0, 1, 2, 3, 4, 5, 6, 7, 8]
    t = scoring.thresholds(values)  # zeros ignored -> quartiles of 1..8
    assert t == pytest.approx((2.75, 4.5, 6.25))
    assert [scoring.level(v, t) for v in values] == [0, 1, 1, 2, 2, 3, 3, 4, 4]


def test_levels_with_single_active_day() -> None:
    t = scoring.thresholds([0, 0, 5])
    assert scoring.level(5, t) == 1  # equals every quartile: lowest band, not "very high"
    assert scoring.level(0, t) == 0


def test_grid_shape_monday_start_and_pending() -> None:
    today = date(2026, 10, 21)  # Wednesday
    grid = scoring.build_grid({today - timedelta(days=5): 10.0}, today, weeks=26)
    assert len(grid) == 26
    assert all(
        date.fromisoformat(col[0].date.isoformat()).weekday() == 0 for col in grid
    )  # Mondays
    assert all(len(col) == 7 for col in grid[:-1])
    assert [c.date for c in grid[-1]] == [
        date(2026, 10, 19),
        date(2026, 10, 20),
        date(2026, 10, 21),
    ]  # no future days
    pending = [c.date for col in grid for c in col if c.pending]
    assert pending == [date(2026, 10, 19), date(2026, 10, 20), date(2026, 10, 21)]  # last 3 days
    active = [c for col in grid for c in col if c.score > 0]
    assert len(active) == 1 and active[0].level == 1


def test_pending_days_hide_scores() -> None:
    today = date(2026, 10, 21)
    grid = scoring.build_grid({today: 50.0}, today, weeks=1)
    cell = grid[-1][-1]
    assert cell.pending and cell.score == 0 and cell.level == 0


def test_streaks_skip_weekends() -> None:
    today = date(2026, 10, 21)  # last reported day = Sun 18 Oct
    # Active Mon 5 Oct .. Fri 16 Oct on weekdays only
    days = [date(2026, 10, 5) + timedelta(days=i) for i in range(12)]
    scores = {d: 1.0 for d in days if d.weekday() < 5}
    s = scoring.streaks(scores, today)
    assert s["current"] == 10  # weekend 17-18 Oct doesn't break it
    assert s["longest"] == 10
    assert s["active_days"] == 10


def test_streak_broken_by_weekday_gap() -> None:
    today = date(2026, 10, 21)
    scores = {
        date(2026, 10, 14): 1.0,
        date(2026, 10, 15): 1.0,
        date(2026, 10, 12): 1.0,
    }  # Tue 13 missing
    s = scoring.streaks(scores, today)
    assert s["current"] == 0  # Fri 16 Oct inactive
    assert s["longest"] == 2


def test_streaks_empty() -> None:
    assert scoring.streaks({}, date(2026, 10, 21)) == {"current": 0, "longest": 0, "active_days": 0}


@pytest.mark.parametrize(
    ("codes", "days_ago", "complete"),
    [
        (set(), 4, True),
        ({"PARTIAL_DATA_AVAILABLE"}, 3, False),  # recent: Google may still fill it in
        ({"PARTIAL_DATA_AVAILABLE"}, 30, True),  # old: Google never will (seen live)
        ({"DATA_NOT_AVAILABLE"}, 30, False),
    ],
)
def test_usage_day_completeness(codes: set[str], days_ago: int, complete: bool) -> None:
    from orgpulse.sync.usage import day_is_complete

    today = date(2026, 10, 23)
    assert day_is_complete(codes, today - timedelta(days=days_ago), today) is complete


def test_geoip_download_months() -> None:
    from orgpulse.geoip_update import _months_to_try

    assert _months_to_try(date(2026, 10, 23)) == ["2026-10", "2026-09"]
    assert _months_to_try(date(2027, 1, 2)) == ["2027-01", "2026-12"]  # year rollover
