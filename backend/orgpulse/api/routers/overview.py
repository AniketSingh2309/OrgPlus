"""GET /api/overview"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from orgpulse.alerts import compute_alerts
from orgpulse.api.deps import Viewer, get_db, get_viewer
from orgpulse.queries import (
    daily_org_scores,
    iso,
    last_synced,
    scope_sql,
    score_totals,
    scored_window,
    today,
    weekly_user_scores,
)
from orgpulse.scoring import GRID_WEEKS, build_grid, week_start
from orgpulse.sync.mappers import APP_METRICS
from orgpulse.teams import team_sql

router = APIRouter(prefix="/api", tags=["overview"])


ALL_APP_METRICS = [m for metrics in APP_METRICS.values() for m in metrics]


def app_users(db: Session, tenant_id: Any, scope: list[str] | None, metrics: list[str]) -> int:
    """People with any non-zero value for these metrics in the last 30 reported days."""
    start, end = scored_window(30)
    cond, params = scope_sql(scope, "user_email")
    return int(
        db.execute(
            text(
                f"""SELECT COUNT(DISTINCT user_id) FROM daily_usage
                    WHERE tenant_id = :t AND date BETWEEN :a AND :b AND metric = ANY(:m)
                      AND value > 0 AND {cond}"""
            ),
            {"t": tenant_id, "a": start, "b": end, "m": metrics, **params},
        ).scalar_one()
    )


def app_adoption(db: Session, tenant_id: Any, scope: list[str] | None) -> list[dict[str, Any]]:
    """Share of active people (anyone using any of the five apps) who used each app,
    last 30 reported days. Same denominator for every app, so no share exceeds 100%."""
    active_users = app_users(db, tenant_id, scope, ALL_APP_METRICS)
    start, end = scored_window(30)
    cond, params = scope_sql(scope, "user_email")
    out = []
    for app, metrics in APP_METRICS.items():
        n = db.execute(
            text(
                f"""SELECT COUNT(DISTINCT user_id) FROM daily_usage
                    WHERE tenant_id = :t AND date BETWEEN :a AND :b AND metric = ANY(:m)
                      AND value > 0 AND {cond}"""
            ),
            {"t": tenant_id, "a": start, "b": end, "m": list(metrics), **params},
        ).scalar_one()
        out.append(
            {
                "app": app,
                "users": int(n),
                "pct": round(100 * n / active_users, 1) if active_users else 0,
            }
        )
    return out


@router.get("/overview")
def overview(viewer: Viewer = Depends(get_viewer), db: Session = Depends(get_db)) -> dict[str, Any]:
    t = viewer.tenant_id
    scope = viewer.scope_list()
    cond_u, p_u = scope_sql(scope, "u.primary_email")
    now = datetime.now(UTC)

    users = db.execute(
        text(
            f"""SELECT u.id, u.primary_email, u.full_name, {team_sql("u")} AS department, u.title, u.thumbnail_photo_url,
                       u.suspended, u.archived, u.is_enrolled_in_2sv, u.last_login_time
                FROM users u WHERE u.tenant_id = :t AND {cond_u}"""
        ),
        {"t": t, **p_u},
    ).all()
    live = [u for u in users if not u.suspended and not u.archived]
    signed_in_7d = sum(
        1 for u in live if u.last_login_time and u.last_login_time >= now - timedelta(days=7)
    )
    with_2sv = sum(1 for u in live if u.is_enrolled_in_2sv)

    start, end = scored_window(30)
    totals = score_totals(db, t, start, end, scope)
    prev = score_totals(db, t, start - timedelta(days=30), start - timedelta(days=1), scope)
    # "Active" = any Drive, Gmail, Meet, Chat or Calendar use (receiving email counts),
    # the same people the app-adoption shares are measured against.
    active_30 = app_users(db, t, scope, ALL_APP_METRICS)
    avg_score = sum(v["score"] for v in totals.values()) / len(live) if live else 0
    prev_avg = sum(v["score"] for v in prev.values()) / len(live) if live else 0

    ext = db.execute(
        text(
            f"""SELECT COUNT(DISTINCT doc_id) FROM events e WHERE e.tenant_id = :t AND e.app = 'drive'
                AND e.is_external IS TRUE AND e.time >= :since AND {scope_sql(scope, "e.user_email")[0]}"""
        ),
        {"t": t, "since": now - timedelta(days=7), **p_u},
    ).scalar_one()

    # Org grid: total org score per day.
    grid_start = week_start(today()) - timedelta(weeks=GRID_WEEKS - 1)
    grid = build_grid(daily_org_scores(db, t, grid_start, scope), today())

    by_id = {u.id: u for u in users}
    spark = weekly_user_scores(db, t, 12, scope)
    top = sorted(
        ((uid, v) for uid, v in totals.items() if uid in by_id),
        key=lambda kv: kv[1]["score"],
        reverse=True,
    )[:10]
    top_people = [
        {
            "id": uid,
            "name": by_id[uid].full_name or by_id[uid].primary_email,
            "email": by_id[uid].primary_email,
            "department": by_id[uid].department,
            "title": by_id[uid].title,
            "photo": by_id[uid].thumbnail_photo_url,
            "score": round(v["score"], 1),
            "active_days": v["active_days"],
            "spark": spark.get(uid, []),
        }
        for uid, v in top
    ]

    dept_rows: dict[str, dict[str, Any]] = {}
    for u in live:
        d = dept_rows.setdefault(u.department, {"users": 0, "active": 0, "score": 0.0, "twosv": 0})
        d["users"] += 1
        v = totals.get(u.id)
        if v and v["active_days"]:
            d["active"] += 1
            d["score"] += v["score"]
        d["twosv"] += 1 if u.is_enrolled_in_2sv else 0
    departments = sorted(
        (
            {
                "department": name,
                "users": d["users"],
                "active_pct": round(100 * d["active"] / d["users"], 1),
                "avg_score": round(d["score"] / d["users"], 1),
                "twosv_pct": round(100 * d["twosv"] / d["users"], 1),
            }
            for name, d in dept_rows.items()
        ),
        key=lambda r: -r["avg_score"],
    )

    admin_actions: list[dict[str, Any]] = []
    if viewer.is_admin:
        admin_actions = [
            {
                "time": iso(r.time),
                "actor": r.user_email,
                "event": r.event_name,
                "type": r.event_type,
                "target": r.target,
            }
            for r in db.execute(
                text(
                    """SELECT time, user_email, event_name, event_type,
                              COALESCE(params->>'USER_EMAIL', params->>'GROUP_EMAIL',
                                       params->>'ORG_UNIT_NAME', params->>'SETTING_NAME') AS target
                       FROM events WHERE tenant_id = :t AND app = 'admin'
                       ORDER BY time DESC LIMIT 10"""
                ),
                {"t": t},
            ).all()
        ]

    return {
        "kpis": {
            "users": len(live),
            "suspended": len(users) - len(live),
            "signed_in_7d": signed_in_7d,
            "active_30d": active_30,
            "avg_score": round(avg_score, 1),
            "avg_score_change_pct": round(100 * (avg_score - prev_avg) / prev_avg, 1)
            if prev_avg
            else None,
            "twosv_pct": round(100 * with_2sv / len(live), 1) if live else 0,
            "external_shares_7d": int(ext),
        },
        "window": {"start": start.isoformat(), "end": end.isoformat()},
        "grid": [[c.as_dict() for c in col] for col in grid],
        "alerts": compute_alerts(db, t, scope),
        "top_people": top_people,
        "app_adoption": app_adoption(db, t, scope),
        "departments": departments,
        "recent_admin_actions": admin_actions,
        "sync": last_synced(db, t),
    }
