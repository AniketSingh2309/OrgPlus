"""Daily usage counts from reports.userUsageReport.

Google publishes usage with a 2-3 day lag and sometimes partially. Each run
re-pulls the last few days and walks forward from the last *complete* day, so
the first run is the 180-day backfill and later runs are cheap.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

from googleapiclient.errors import HttpError

from orgpulse import google_client as g
from orgpulse.config import get_settings
from orgpulse.db import session_scope
from orgpulse.models import DailyUsage
from orgpulse.sync import state
from orgpulse.sync.mappers import UsageMapper
from orgpulse.sync.upsert import upsert

log = logging.getLogger(__name__)

KEY = "usage"
REFETCH_DAYS = 3  # always re-pull the most recent days; they may have been partial
# Google marks some old days PARTIAL forever (e.g. "accounts" data never arrives), so a
# PARTIAL warning only holds the cursor back while the day is this recent.
PARTIAL_GRACE_DAYS = 6


def day_is_complete(warning_codes: set[str], day: date, today: date) -> bool:
    if "DATA_NOT_AVAILABLE" in warning_codes:
        return False
    return "PARTIAL_DATA_AVAILABLE" not in warning_codes or day < today - timedelta(
        days=PARTIAL_GRACE_DAYS
    )


def _fetch_day(
    day: date, mapper: UsageMapper, tenant_id: uuid.UUID
) -> tuple[list[dict[str, Any]], bool]:
    """Rows for one day, and whether Google said the day is complete."""
    rows: list[dict[str, Any]] = []
    codes: set[str] = set()
    token: str | None = None
    while True:
        params: dict[str, Any] = {"userKey": "all", "date": day.isoformat(), "maxResults": 1000}
        if token:
            params["pageToken"] = token
        try:
            resp = g.execute(g.reports().userUsageReport().get(**params), what="userUsageReport")
        except HttpError as err:
            # 400 "Data for dates later than ... is not yet available"
            if err.resp.status == 400 and "not yet available" in str(err):
                return [], False
            raise
        codes |= {str(w.get("code")) for w in resp.get("warnings", [])}
        for report in resp.get("usageReports", []):
            rows += mapper.map_report(report, tenant_id)
        token = resp.get("nextPageToken")
        if not token:
            return rows, day_is_complete(codes, day, datetime.now(UTC).date())


def sync_usage(tenant_id: uuid.UUID, *, days: int | None = None) -> dict[str, Any]:
    today = datetime.now(UTC).date()
    prev = state.get_state(tenant_id, KEY)
    raw_last = prev.detail.get("last_complete") if prev else None
    last_complete = date.fromisoformat(raw_last) if raw_last else None
    backfill_days = days or get_settings().backfill_days

    if last_complete is None:
        start = today - timedelta(days=backfill_days)
    else:
        start = min(last_complete + timedelta(days=1), today - timedelta(days=REFETCH_DAYS))
    end = today - timedelta(days=1)

    mapper = UsageMapper()
    total = 0
    first_gap: date | None = None  # first day Google reported as incomplete
    day = start
    n_days = (end - start).days + 1
    while day <= end:
        rows, complete = _fetch_day(day, mapper, tenant_id)
        with session_scope() as s:
            total += upsert(
                s,
                DailyUsage,
                rows,
                ["tenant_id", "user_id", "date", "metric"],
                touch_synced_at=False,
            )
        if not complete and first_gap is None:
            first_gap = day
        done = (day - start).days + 1
        if done % 10 == 0 or day == end:
            log.info("usage: %d/%d days (%s), %d rows", done, n_days, day, total)
            state.update_detail(tenant_id, KEY, _detail(last_complete, done, n_days, mapper))
        day += timedelta(days=1)

    # The cursor advances only through an unbroken run of complete days.
    reached = (first_gap - timedelta(days=1)) if first_gap else end
    new_last_complete = max(reached, last_complete) if last_complete else reached
    missing = mapper.report_missing()
    detail = _detail(new_last_complete, n_days, n_days, mapper, missing)
    state.mark_ok(tenant_id, KEY, detail=detail)
    return {"rows": total, "days": n_days, "missing_metrics": missing}


def _detail(
    last_complete: date | None,
    done: int,
    total: int,
    mapper: UsageMapper,
    missing: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    return {
        "last_complete": last_complete.isoformat() if last_complete else None,
        "progress": {"done": done, "total": total},
        "missing_metrics": missing if missing is not None else mapper.missing_metrics(),
        "params_seen": sorted(mapper.params_seen)[:400],
    }
