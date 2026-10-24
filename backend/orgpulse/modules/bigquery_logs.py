"""Unlimited history from the BigQuery Workspace log export.

Pulls user usage older than the Reports API keeps (and anything we missed)
into daily_usage, so the grid and reports reach back beyond 6 months.
"""

from __future__ import annotations

import logging
import uuid
from datetime import date, timedelta
from typing import Any

from fastapi import Depends, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from orgpulse import google_client as g
from orgpulse.api.deps import Viewer, get_db, get_viewer
from orgpulse.db import session_scope
from orgpulse.features.registry import FeatureModule, UiCard, register
from orgpulse.models import DailyUsage, TenantCredential, User
from orgpulse.modules._common import gated_router
from orgpulse.queries import today, weights
from orgpulse.scoring import build_grid, daily_scores, week_start
from orgpulse.sync.upsert import upsert

log = logging.getLogger(__name__)
router = gated_router("bigquery_logs")

# Our metric -> column in the export's `usage` table (nested STRUCT per app).
BQ_COLUMNS = {
    "dc": "drive.num_items_created",
    "de": "drive.num_items_edited",
    "dv": "drive.num_items_viewed",
    "es": "gmail.num_emails_sent",
    "er": "gmail.num_emails_received",
    "mt": "meet.num_calls",
    "mm": "meet.total_call_minutes",
    "st_used": "accounts.used_quota_in_mb",
}
HISTORY_YEARS = 3


def _query(project: str, sql: str) -> list[list[Any]]:
    resp = g.execute(
        g.bigquery()
        .jobs()
        .query(
            projectId=project,
            body={"query": sql, "useLegacySql": False, "timeoutMs": 60000, "maxResults": 100000},
        ),
        what="bigquery.query",
    )
    return [[c.get("v") for c in row["f"]] for row in resp.get("rows") or []]


def sync_bigquery(tenant_id: uuid.UUID) -> int:
    with session_scope() as s:
        cred = s.get(TenantCredential, tenant_id)
        ids = {u.primary_email: u.id for u in s.query(User).filter(User.tenant_id == tenant_id)}
        earliest = s.execute(
            text("SELECT MIN(date) FROM daily_usage WHERE tenant_id = :t"), {"t": tenant_id}
        ).scalar()
    if not cred or not cred.bigquery_project or not cred.bigquery_dataset:
        return 0
    end = (earliest or today()) - timedelta(days=1)
    start = end - timedelta(days=365 * HISTORY_YEARS)
    cols = ", ".join(f"{c} AS {m}" for m, c in BQ_COLUMNS.items())
    total = 0
    # One month per query keeps responses small.
    cursor = start
    while cursor <= end:
        stop = min(cursor + timedelta(days=30), end)
        sql = (
            f"SELECT date, user_email, {cols} FROM `{cred.bigquery_project}.{cred.bigquery_dataset}.usage` "
            f"WHERE record_type = 'user' AND date BETWEEN '{cursor}' AND '{stop}'"
        )
        try:
            rows = _query(cred.bigquery_project, sql)
        except Exception as err:
            log.warning("bigquery history query failed (%s); check column names in BQ_COLUMNS", err)
            break
        out = []
        for r in rows:
            email = (r[1] or "").lower()
            uid = ids.get(email)
            if not uid:
                continue
            day = date.fromisoformat(str(r[0])[:10])
            for i, metric in enumerate(BQ_COLUMNS, start=2):
                if r[i] is not None:
                    out.append(
                        {
                            "tenant_id": tenant_id,
                            "user_id": uid,
                            "date": day,
                            "metric": metric,
                            "user_email": email,
                            "value": float(r[i]),
                        }
                    )
                    if metric == "mm":
                        out.append(
                            {
                                "tenant_id": tenant_id,
                                "user_id": uid,
                                "date": day,
                                "metric": "mh",
                                "user_email": email,
                                "value": float(r[i]) / 60,
                            }
                        )
        with session_scope() as s:
            total += upsert(
                s,
                DailyUsage,
                out,
                ["tenant_id", "user_id", "date", "metric"],
                touch_synced_at=False,
            )
        cursor = stop + timedelta(days=1)
    log.info("bigquery history: %d usage rows", total)
    return total


@router.get("/yoy")
def year_on_year(
    viewer: Viewer = Depends(get_viewer), db: Session = Depends(get_db)
) -> dict[str, Any]:
    rows = db.execute(
        text(
            """SELECT EXTRACT(year FROM d.date)::int AS y, EXTRACT(month FROM d.date)::int AS m,
                      SUM(d.value * COALESCE(w.weight, 0)) AS score, COUNT(DISTINCT d.user_id) AS users
               FROM daily_usage d LEFT JOIN score_weights w ON w.tenant_id = d.tenant_id AND w.metric = d.metric
               WHERE d.tenant_id = :t AND d.date >= :s GROUP BY 1, 2 ORDER BY 1, 2"""
        ),
        {"t": viewer.tenant_id, "s": date(today().year - 2, 1, 1)},
    ).all()
    years: dict[int, list[float | None]] = {}
    for r in rows:
        years.setdefault(r.y, [None] * 12)[r.m - 1] = round(
            float(r.score or 0) / max(r.users, 1), 1
        )
    return {"years": [{"year": y, "monthly_score_per_user": v} for y, v in sorted(years.items())]}


@router.get("/people/{user_id}/grid")
def long_grid(
    user_id: str,
    weeks: int = Query(104, ge=26, le=260),
    viewer: Viewer = Depends(get_viewer),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    start = week_start(today()) - timedelta(weeks=weeks - 1)
    rows = db.execute(
        text(
            "SELECT date, metric, value FROM daily_usage WHERE tenant_id = :t AND user_id = :u AND date >= :s"
        ),
        {"t": viewer.tenant_id, "u": user_id, "s": start},
    ).all()
    scores = daily_scores(
        [(r.date, r.metric, float(r.value)) for r in rows], weights(db, viewer.tenant_id)
    )
    return {"weeks": [[c.as_dict() for c in col] for col in build_grid(scores, today(), weeks)]}


register(
    FeatureModule(
        key="bigquery_logs",
        title="Unlimited history and fast sync",
        requires="Enterprise + BigQuery export",
        description="Reads Workspace logs from BigQuery: grids and reports beyond 6 months, and year-on-year trends.",
        how_to_enable="https://support.google.com/a/answer/9079365",
        page="/m/bigquery_logs",
        router=router,
        sync=sync_bigquery,
        schedule={"trigger": "interval", "hours": 24},
        cards=[
            UiCard(
                "yoy",
                "Year on year",
                "Monthly activity per person, this year against previous years.",
            )
        ],
    )
)
