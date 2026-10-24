"""Activity score and the GitHub-style grid.

score(day)  = sum(metric value * weight)
level(day)  = 0 for no activity, else 1-4 by quartile of that user's non-zero days
Usage lags 2-3 days, so the last 3 days are "not reported yet". Weeks start Monday.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from orgpulse.sync.mappers import APP_METRICS, SCORE_METRICS

PENDING_DAYS = 3
GRID_WEEKS = 26  # ~6 months


def daily_scores(
    rows: Iterable[tuple[date, str, float]], weights: Mapping[str, float]
) -> dict[date, float]:
    """(date, metric, value) rows -> weighted score per day. Unknown metrics weigh 0."""
    out: dict[date, float] = defaultdict(float)
    for day, metric, value in rows:
        if metric in SCORE_METRICS:
            out[day] += value * weights.get(metric, 0.0)
    return dict(out)


def app_scores(rows: Iterable[tuple[date, str, float]], app: str) -> dict[date, float]:
    """Unweighted count of one app's metrics per day (for the per-app grid)."""
    metrics = set(APP_METRICS[app])
    out: dict[date, float] = defaultdict(float)
    for day, metric, value in rows:
        if metric in metrics:
            out[day] += value
    return dict(out)


def _quantile(sorted_vals: list[float], q: float) -> float:
    """Linear-interpolated quantile (same as numpy's default)."""
    if not sorted_vals:
        return 0.0
    pos = (len(sorted_vals) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(sorted_vals) - 1)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (pos - lo)


def thresholds(scores: Iterable[float]) -> tuple[float, float, float]:
    nonzero = sorted(v for v in scores if v > 0)
    return (_quantile(nonzero, 0.25), _quantile(nonzero, 0.5), _quantile(nonzero, 0.75))


def level(value: float, t: tuple[float, float, float]) -> int:
    if value <= 0:
        return 0
    if value <= t[0]:
        return 1
    if value <= t[1]:
        return 2
    if value <= t[2]:
        return 3
    return 4


def last_reported_day(today: date) -> date:
    return today - timedelta(days=PENDING_DAYS)


def week_start(day: date) -> date:
    return day - timedelta(days=day.weekday())  # Monday


@dataclass(frozen=True)
class Cell:
    date: date
    score: float
    level: int
    pending: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "date": self.date.isoformat(),
            "score": round(self.score, 2),
            "level": self.level,
            "pending": self.pending,
        }


def build_grid(
    scores: Mapping[date, float], today: date, weeks: int = GRID_WEEKS
) -> list[list[Cell]]:
    """Columns of Monday-first weeks ending with the current week; future days omitted."""
    start = week_start(today) - timedelta(weeks=weeks - 1)
    cutoff = last_reported_day(today)
    t = thresholds(v for d, v in scores.items() if start <= d <= cutoff)
    grid: list[list[Cell]] = []
    for w in range(weeks):
        col: list[Cell] = []
        for d in range(7):
            day = start + timedelta(weeks=w, days=d)
            if day > today:
                break
            pending = day > cutoff
            value = 0.0 if pending else scores.get(day, 0.0)
            col.append(Cell(day, value, 0 if pending else level(value, t), pending))
        grid.append(col)
    return grid


def streaks(scores: Mapping[date, float], today: date) -> dict[str, int]:
    """Current streak counts back from the last reported day; weekends don't break it."""
    end = last_reported_day(today)
    active = {d for d, v in scores.items() if v > 0 and d <= end}

    current = 0
    day = end
    while True:
        if day in active:
            current += 1
        elif day.weekday() < 5:
            break
        day -= timedelta(days=1)
        if not active or day < min(active):
            break

    longest = run = 0
    prev: date | None = None
    for d in sorted(active):
        gap_days = (d - prev).days if prev else None
        only_weekend_between = (
            prev is not None
            and gap_days is not None
            and gap_days > 1
            and all((prev + timedelta(days=i)).weekday() >= 5 for i in range(1, gap_days))
        )
        run = run + 1 if prev and (gap_days == 1 or only_weekend_between) else 1
        longest = max(longest, run)
        prev = d
    return {"current": current, "longest": longest, "active_days": len(active)}
