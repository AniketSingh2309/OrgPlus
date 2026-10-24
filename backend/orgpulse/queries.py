"""SQL helpers shared by routers, alerts, digest and exports."""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from orgpulse.models import ScoreWeight, SyncState
from orgpulse.scoring import last_reported_day
from orgpulse.tenancy import DEFAULT_WEIGHTS


def today() -> date:
    return datetime.now(UTC).date()


def scope_sql(scope: list[str] | None, column: str) -> tuple[str, dict[str, Any]]:
    """SQL condition limiting `column` (an email) to the viewer's scope."""
    if scope is None:
        return "TRUE", {}
    return f"{column} = ANY(:scope)", {"scope": scope}


def weights(db: Session, tenant_id: uuid.UUID) -> dict[str, float]:
    rows = db.execute(
        select(ScoreWeight.metric, ScoreWeight.weight).where(ScoreWeight.tenant_id == tenant_id)
    ).all()
    return {**DEFAULT_WEIGHTS, **{m: w for m, w in rows}}


def scored_window(days: int = 30) -> tuple[date, date]:
    """The last `days` *reported* days (usage lags ~3 days)."""
    end = last_reported_day(today())
    return end - timedelta(days=days - 1), end


def score_totals(
    db: Session, tenant_id: uuid.UUID, start: date, end: date, scope: list[str] | None = None
) -> dict[str, dict[str, float]]:
    """user_id -> {"score", "active_days"} over [start, end]."""
    cond, params = scope_sql(scope, "d.user_email")
    rows = db.execute(
        text(
            f"""
            SELECT user_id, SUM(day_score) AS score, COUNT(*) FILTER (WHERE day_score > 0) AS active
            FROM (
              SELECT d.user_id, d.date, SUM(d.value * COALESCE(w.weight, 0)) AS day_score
              FROM daily_usage d
              LEFT JOIN score_weights w ON w.tenant_id = d.tenant_id AND w.metric = d.metric
              WHERE d.tenant_id = :t AND d.date BETWEEN :a AND :b AND {cond}
              GROUP BY d.user_id, d.date
            ) x GROUP BY user_id
            """
        ),
        {"t": tenant_id, "a": start, "b": end, **params},
    ).all()
    return {r.user_id: {"score": float(r.score or 0), "active_days": int(r.active)} for r in rows}


def daily_org_scores(
    db: Session, tenant_id: uuid.UUID, start: date, scope: list[str] | None = None
) -> dict[date, float]:
    cond, params = scope_sql(scope, "d.user_email")
    rows = db.execute(
        text(
            f"""
            SELECT d.date, SUM(d.value * COALESCE(w.weight, 0)) AS s
            FROM daily_usage d
            LEFT JOIN score_weights w ON w.tenant_id = d.tenant_id AND w.metric = d.metric
            WHERE d.tenant_id = :t AND d.date >= :a AND {cond}
            GROUP BY d.date
            """
        ),
        {"t": tenant_id, "a": start, **params},
    ).all()
    return {r.date: float(r.s or 0) for r in rows}


def weekly_user_scores(
    db: Session, tenant_id: uuid.UUID, weeks: int, scope: list[str] | None = None
) -> dict[str, list[float]]:
    """user_id -> score per week for the last `weeks` weeks (sparklines)."""
    end = last_reported_day(today())
    start = end - timedelta(weeks=weeks) + timedelta(days=1)
    cond, params = scope_sql(scope, "d.user_email")
    rows = db.execute(
        text(
            f"""
            SELECT d.user_id, FLOOR((d.date - CAST(:a AS date)) / 7) AS wk,
                   SUM(d.value * COALESCE(w.weight, 0)) AS s
            FROM daily_usage d
            LEFT JOIN score_weights w ON w.tenant_id = d.tenant_id AND w.metric = d.metric
            WHERE d.tenant_id = :t AND d.date BETWEEN :a AND :b AND {cond}
            GROUP BY d.user_id, wk
            """
        ),
        {"t": tenant_id, "a": start, "b": end, **params},
    ).all()
    out: dict[str, list[float]] = defaultdict(lambda: [0.0] * weeks)
    for r in rows:
        wk = int(r.wk)
        if 0 <= wk < weeks:
            out[r.user_id][wk] = round(float(r.s or 0), 1)
    return dict(out)


def last_synced(db: Session, tenant_id: uuid.UUID) -> dict[str, Any]:
    from orgpulse.sync.state import reconcile_stale

    reconcile_stale(tenant_id)
    db.expire_all()
    rows = db.scalars(select(SyncState).where(SyncState.tenant_id == tenant_id)).all()
    ok = [r.last_success_at for r in rows if r.last_success_at]
    running = [r.key for r in rows if r.status == "running"]
    errors = {r.key: r.error for r in rows if r.status == "error"}
    return {
        "last_synced": max(ok).isoformat() if ok else None,
        "running": running,
        "errors": errors,
    }


def iso(value: datetime | date | None) -> str | None:
    return value.isoformat() if value else None
