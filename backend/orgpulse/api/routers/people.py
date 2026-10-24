"""People list and person profile (all profile tabs)."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from orgpulse.api.deps import Viewer, get_db, get_viewer
from orgpulse.describe import APP_LABEL, describe
from orgpulse.models import AuditView, TenantSettings, User
from orgpulse.queries import (
    iso,
    scope_sql,
    score_totals,
    scored_window,
    today,
    weekly_user_scores,
    weights,
)
from orgpulse.roles import roles_for
from orgpulse.scoring import GRID_WEEKS, app_scores, build_grid, daily_scores, streaks, week_start
from orgpulse.sync.mappers import SCORE_METRICS
from orgpulse.teams import team_of, team_sql
from orgpulse.timeutil import utc_offset

router = APIRouter(prefix="/api/people", tags=["people"])

METRIC_LABELS = {
    "dc": "Drive files created",
    "de": "Drive files edited",
    "dv": "Drive files viewed",
    "es": "Emails sent",
    "er": "Emails received",
    "mt": "Meet calls",
    "mh": "Meet hours",
    "ch": "Chat messages",
    "cal": "Calendar events created",
}


def _user_or_404(db: Session, viewer: Viewer, user_id: str) -> User:
    user = db.scalar(select(User).where(User.tenant_id == viewer.tenant_id, User.id == user_id))
    if user is None or not viewer.can_see(user.primary_email):
        raise HTTPException(404, "person not found")
    return user


def _usage_rows(
    db: Session, tenant_id: Any, user_id: str, since: date
) -> list[tuple[date, str, float]]:
    return [
        (r.date, r.metric, float(r.value))
        for r in db.execute(
            text(
                "SELECT date, metric, value FROM daily_usage WHERE tenant_id = :t AND user_id = :u AND date >= :s"
            ),
            {"t": tenant_id, "u": user_id, "s": since},
        ).all()
    ]


def _status(u: Any, now: datetime) -> str:
    if u.suspended or u.archived:
        return "suspended"
    if not u.last_login_time or u.last_login_time < now - timedelta(days=30):
        return "inactive"
    return "active"


@router.get("")
def list_people(
    q: str = "",
    dept: str = "",
    status: Literal["", "active", "inactive", "suspended", "no2sv", "admin"] = "",
    sort: Literal["score", "name", "last_login", "department"] = "score",
    viewer: Viewer = Depends(get_viewer),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    cond, params = scope_sql(viewer.scope_list(), "primary_email")
    rows = db.execute(
        text(
            f"""SELECT id, primary_email, full_name, {team_sql("users")} AS department, title, org_unit_path, last_login_time,
                       suspended, archived, is_enrolled_in_2sv, is_admin, admin_role, thumbnail_photo_url,
                       manager_email, creation_time
                FROM users WHERE tenant_id = :t AND {cond}"""
        ),
        {"t": viewer.tenant_id, **params},
    ).all()
    start, end = scored_window(30)
    totals = score_totals(db, viewer.tenant_id, start, end, viewer.scope_list())
    spark = weekly_user_scores(db, viewer.tenant_id, 12, viewer.scope_list())
    now = datetime.now(UTC)

    people = []
    ql = q.strip().lower()
    for u in rows:
        st = _status(u, now)
        if (
            ql
            and ql not in (u.full_name or "").lower()
            and ql not in u.primary_email
            and ql not in (u.title or "").lower()
        ):
            continue
        if dept and u.department != dept:
            continue
        if status in ("active", "inactive", "suspended") and st != status:
            continue
        if status == "no2sv" and (u.is_enrolled_in_2sv or st == "suspended"):
            continue
        if status == "admin" and not (u.is_admin or u.admin_role):
            continue
        tot = totals.get(u.id, {"score": 0.0, "active_days": 0})
        people.append(
            {
                "id": u.id,
                "name": u.full_name or u.primary_email,
                "email": u.primary_email,
                "department": team_of(u.department, u.org_unit_path),
                "title": u.title,
                "org_unit": u.org_unit_path,
                "photo": u.thumbnail_photo_url,
                "last_login": iso(u.last_login_time),
                "status": st,
                "twosv": u.is_enrolled_in_2sv,
                # Readable names; joined copy kept for CSV exports.
                "roles": (roles := roles_for(u.admin_role, u.is_admin)),
                "admin_role": "; ".join(roles) or None,
                "score": round(tot["score"], 1),
                "active_days": tot["active_days"],
                "spark": spark.get(u.id, []),
            }
        )

    key = {
        "score": lambda p: (-p["score"], p["name"].lower()),
        "name": lambda p: p["name"].lower(),
        "last_login": lambda p: (
            p["last_login"] is None,
            -(datetime.fromisoformat(p["last_login"]).timestamp() if p["last_login"] else 0),
        ),
        "department": lambda p: ((p["department"] or "~").lower(), p["name"].lower()),
    }[sort]
    people.sort(key=key)
    departments = sorted({u.department for u in rows})
    return {"people": people, "departments": departments, "total": len(rows)}


@router.get("/photos")
def photos(viewer: Viewer = Depends(get_viewer), db: Session = Depends(get_db)) -> dict[str, str]:
    """email -> profile photo URL, for everyone visible who has one (avatars look up by email)."""
    cond, params = scope_sql(viewer.scope_list(), "primary_email")
    rows = db.execute(
        text(
            f"""SELECT primary_email, thumbnail_photo_url FROM users
                WHERE tenant_id = :t AND thumbnail_photo_url IS NOT NULL AND {cond}"""
        ),
        {"t": viewer.tenant_id, **params},
    ).all()
    return {r.primary_email: r.thumbnail_photo_url for r in rows}


@router.get("/{user_id}")
def profile(
    user_id: str, viewer: Viewer = Depends(get_viewer), db: Session = Depends(get_db)
) -> dict[str, Any]:
    u = _user_or_404(db, viewer, user_id)
    db.add(AuditView(tenant_id=viewer.tenant_id, viewer=viewer.email, viewed_user=u.primary_email))

    t = viewer.tenant_id
    rows = _usage_rows(db, t, u.id, today() - timedelta(days=400))
    scores = daily_scores(rows, weights(db, t))
    start, end = scored_window(30)
    score30 = sum(v for d, v in scores.items() if start <= d <= end)
    totals30: dict[str, float] = defaultdict(float)
    for d, m, v in rows:
        if start <= d <= end and m in SCORE_METRICS:
            totals30[m] += v

    org_totals = score_totals(db, t, start, end, viewer.scope_list())
    ranked = sorted((v["score"] for v in org_totals.values()), reverse=True)
    rank = next((i + 1 for i, s in enumerate(ranked) if s <= score30), len(ranked) or 1)

    storage = {m: v for d, m, v in sorted(rows) if m.startswith("st_")}
    storage_trend = [
        {"date": d.isoformat(), "used_mb": v}
        for d, m, v in sorted(rows)
        if m == "st_used" and d.weekday() == 0
    ][-26:]

    groups = db.execute(
        text(
            """SELECT g.id, g.email, g.name, m.role FROM group_members m JOIN groups g ON g.id = m.group_id
               WHERE m.tenant_id = :t AND m.email = :e ORDER BY g.name"""
        ),
        {"t": t, "e": u.primary_email},
    ).all()
    reports = db.execute(
        text(
            """SELECT id, primary_email, full_name, title FROM users
               WHERE tenant_id = :t AND manager_email = :e ORDER BY full_name"""
        ),
        {"t": t, "e": u.primary_email},
    ).all()
    manager = (
        db.execute(
            text(
                "SELECT id, primary_email, full_name FROM users WHERE tenant_id = :t AND primary_email = :e"
            ),
            {"t": t, "e": u.manager_email},
        ).first()
        if u.manager_email
        else None
    )
    licences = db.execute(
        text(
            "SELECT sku_name, sku_id FROM licence_assignments WHERE tenant_id = :t AND user_email = :e"
        ),
        {"t": t, "e": u.primary_email},
    ).all()

    return {
        "id": u.id,
        "name": u.full_name or u.primary_email,
        "email": u.primary_email,
        "photo": u.thumbnail_photo_url,
        "department": u.department,
        "title": u.title,
        "org_unit": u.org_unit_path,
        "status": _status(u, datetime.now(UTC)),
        "suspension_reason": u.suspension_reason,
        "created": iso(u.creation_time),
        "last_login": iso(u.last_login_time),
        "twosv": {"enrolled": u.is_enrolled_in_2sv, "enforced": u.is_enforced_in_2sv},
        "roles": roles_for(u.admin_role, u.is_admin),
        "aliases": u.aliases,
        "score30": round(score30, 1),
        "rank": rank,
        "ranked_of": len(ranked),
        "totals30": [
            {"metric": m, "label": METRIC_LABELS[m], "value": round(totals30.get(m, 0), 1)}
            for m in SCORE_METRICS
        ],
        "streaks": streaks(scores, today()),
        "manager": {"id": manager.id, "email": manager.primary_email, "name": manager.full_name}
        if manager
        else (
            {"id": None, "email": u.manager_email, "name": u.manager_email}
            if u.manager_email
            else None
        ),
        "reports": [
            {"id": r.id, "email": r.primary_email, "name": r.full_name, "title": r.title}
            for r in reports
        ],
        "groups": [{"id": g.id, "email": g.email, "name": g.name, "role": g.role} for g in groups],
        "storage": {
            "used_mb": storage.get("st_used"),
            "total_mb": storage.get("st_total"),
            "drive_mb": storage.get("st_drive"),
            "gmail_mb": storage.get("st_gmail"),
            "trend": storage_trend,
        },
        "licences": [{"sku": r.sku_name or r.sku_id} for r in licences],
    }


@router.get("/{user_id}/grid")
def grid(
    user_id: str,
    app: Literal["all", "drive", "gmail", "meet", "chat", "calendar"] = "all",
    viewer: Viewer = Depends(get_viewer),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    u = _user_or_404(db, viewer, user_id)
    start = week_start(today()) - timedelta(weeks=GRID_WEEKS - 1)
    rows = _usage_rows(db, viewer.tenant_id, u.id, start)
    scores = (
        daily_scores(rows, weights(db, viewer.tenant_id)) if app == "all" else app_scores(rows, app)
    )
    g = build_grid(scores, today())
    return {
        "app": app,
        "weeks": [[c.as_dict() for c in col] for col in g],
        "total": round(sum(c.score for col in g for c in col), 1),
        "active_days": sum(1 for col in g for c in col if c.score > 0),
    }


@router.get("/{user_id}/day/{day}")
def day_detail(
    user_id: str, day: date, viewer: Viewer = Depends(get_viewer), db: Session = Depends(get_db)
) -> dict[str, Any]:
    u = _user_or_404(db, viewer, user_id)
    t = viewer.tenant_id
    rows = [r for r in _usage_rows(db, t, u.id, day) if r[0] == day]
    w = weights(db, t)
    breakdown: list[dict[str, Any]] = [
        {
            "metric": m,
            "label": METRIC_LABELS.get(m, m),
            "value": v,
            "weight": w.get(m, 0),
            "points": round(v * w.get(m, 0), 2),
        }
        for _, m, v in rows
        if m in SCORE_METRICS
    ]
    signins = db.execute(
        text(
            """SELECT time, event_name, ip, country, city, params->>'login_type' AS login_type
               FROM events WHERE tenant_id = :t AND app = 'login' AND user_email = :e
                 AND time >= :a AND time < :b ORDER BY time"""
        ),
        {
            "t": t,
            "e": u.primary_email,
            "a": datetime.combine(day, datetime.min.time(), UTC),
            "b": datetime.combine(day + timedelta(days=1), datetime.min.time(), UTC),
        },
    ).all()
    return {
        "date": day.isoformat(),
        "pending": day > today() - timedelta(days=3),
        "score": round(sum(b["points"] for b in breakdown), 2),
        "breakdown": sorted(breakdown, key=lambda b: -b["points"]),
        "signins": [
            {
                "time": iso(s.time),
                "event": s.event_name,
                "ip": s.ip,
                "country": s.country,
                "city": s.city,
                "login_type": s.login_type,
            }
            for s in signins
        ],
    }


@router.get("/{user_id}/drive")
def drive(
    user_id: str, viewer: Viewer = Depends(get_viewer), db: Session = Depends(get_db)
) -> dict[str, Any]:
    u = _user_or_404(db, viewer, user_id)
    rows = db.execute(
        text(
            """SELECT time, event_name, doc_id, doc_title, doc_type, visibility, is_external,
                      params->>'owner' AS owner, params->>'target_user' AS target
               FROM events WHERE tenant_id = :t AND app = 'drive' AND user_email = :e AND time >= :s
               ORDER BY time DESC LIMIT 500"""
        ),
        {"t": viewer.tenant_id, "e": u.primary_email, "s": datetime.now(UTC) - timedelta(days=14)},
    ).all()
    by_event: dict[str, int] = defaultdict(int)
    by_type: dict[str, int] = defaultdict(int)
    for r in rows:
        by_event[r.event_name] += 1
        by_type[r.doc_type or "other"] += 1
    return {
        "events": [
            {
                "time": iso(r.time),
                "event": r.event_name,
                "doc_id": r.doc_id,
                "title": r.doc_title,
                "type": r.doc_type,
                "visibility": r.visibility,
                "external": r.is_external,
                "owner": r.owner,
                "target": r.target,
            }
            for r in rows
        ],
        "by_event": dict(sorted(by_event.items(), key=lambda kv: -kv[1])),
        "by_type": dict(sorted(by_type.items(), key=lambda kv: -kv[1])),
        "external_count": sum(1 for r in rows if r.is_external),
    }


@router.get("/{user_id}/meet")
def meet(
    user_id: str, viewer: Viewer = Depends(get_viewer), db: Session = Depends(get_db)
) -> dict[str, Any]:
    u = _user_or_404(db, viewer, user_id)
    rows = db.execute(
        text(
            """SELECT time, params FROM events WHERE tenant_id = :t AND app = 'meet' AND user_email = :e
                 AND event_name = 'call_ended' ORDER BY time DESC LIMIT 100"""
        ),
        {"t": viewer.tenant_id, "e": u.primary_email},
    ).all()
    calls = []
    for r in rows:
        p = r.params
        secs = int(p.get("duration_seconds") or 0)
        calls.append(
            {
                "time": iso(r.time),
                "minutes": round(secs / 60, 1),
                "meeting_code": p.get("meeting_code"),
                "organizer": p.get("organizer_email"),
                "is_organizer": (p.get("organizer_email") or "").lower() == u.primary_email,
                "device": p.get("device_type"),
                "external": bool(p.get("is_external")),
                "country": p.get("location_country"),
                "calendar_event": bool(p.get("calendar_event_id")),
            }
        )
    week: dict[str, float] = defaultdict(float)
    for c in calls:
        ws = week_start(datetime.fromisoformat(c["time"]).date()).isoformat()
        week[ws] += c["minutes"] / 60
    return {
        "calls": calls,
        "hours_by_week": [{"week": k, "hours": round(v, 1)} for k, v in sorted(week.items())],
        "total_hours": round(sum(c["minutes"] for c in calls) / 60, 1),
        "organized": sum(1 for c in calls if c["is_organizer"]),
    }


@router.get("/{user_id}/signins")
def signins(
    user_id: str, viewer: Viewer = Depends(get_viewer), db: Session = Depends(get_db)
) -> dict[str, Any]:
    u = _user_or_404(db, viewer, user_id)
    rows = db.execute(
        text(
            """SELECT time, event_name, ip, country, city, params FROM events
               WHERE tenant_id = :t AND app IN ('login', 'saml') AND user_email = :e AND time >= :s
               ORDER BY time DESC LIMIT 1000"""
        ),
        {"t": viewer.tenant_id, "e": u.primary_email, "s": datetime.now(UTC) - timedelta(days=30)},
    ).all()
    items = [
        {
            "time": iso(r.time),
            "event": r.event_name,
            "ip": r.ip,
            "country": r.country,
            "city": r.city,
            "login_type": r.params.get("login_type"),
            "challenge": r.params.get("login_challenge_method"),
            "suspicious": bool(r.params.get("is_suspicious"))
            or r.event_name.startswith("suspicious"),
            "app": r.params.get("application_name"),
        }
        for r in rows
    ]
    return {
        "signins": items,
        "success": sum(1 for i in items if i["event"] == "login_success"),
        "failure": sum(1 for i in items if i["event"] == "login_failure"),
        "countries": sorted({i["country"] for i in items if i["country"]}),
    }


@router.get("/{user_id}/apps")
def apps(
    user_id: str, viewer: Viewer = Depends(get_viewer), db: Session = Depends(get_db)
) -> dict[str, Any]:
    u = _user_or_404(db, viewer, user_id)
    t = viewer.tenant_id
    tokens = db.execute(
        text(
            """SELECT a.client_id, a.display_text, a.scopes, a.risk, a.anonymous, a.native_app,
                      (SELECT MAX(time) FROM events e WHERE e.tenant_id = a.tenant_id AND e.app = 'token'
                         AND e.user_email = a.user_email AND e.params->>'client_id' = a.client_id) AS last_used
               FROM app_tokens a WHERE a.tenant_id = :t AND a.user_id = :u
               ORDER BY CASE a.risk WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END, a.display_text"""
        ),
        {"t": t, "u": u.id},
    ).all()
    sso = db.execute(
        text(
            """SELECT params->>'application_name' AS app, COUNT(*) AS n, MAX(time) AS last
               FROM events WHERE tenant_id = :t AND app = 'saml' AND user_email = :e
               GROUP BY 1 ORDER BY last DESC"""
        ),
        {"t": t, "e": u.primary_email},
    ).all()
    devices = db.execute(
        text(
            """SELECT kind, id, model, os, os_version, status, device_type, last_sync
               FROM devices WHERE tenant_id = :t AND user_email = :e ORDER BY last_sync DESC NULLS LAST"""
        ),
        {"t": t, "e": u.primary_email},
    ).all()
    return {
        "tokens": [
            {
                "client_id": r.client_id,
                "name": r.display_text or r.client_id,
                "scopes": r.scopes,
                "risk": r.risk,
                "unverified": r.anonymous,
                "native": r.native_app,
                "last_used": iso(r.last_used),
            }
            for r in tokens
        ],
        "sso_apps": [{"app": r.app or "Unknown", "signins": r.n, "last": iso(r.last)} for r in sso],
        "devices": [
            {
                "kind": r.kind,
                "id": r.id,
                "model": r.model,
                "os": r.os,
                "os_version": r.os_version,
                "status": r.status,
                "type": r.device_type,
                "last_sync": iso(r.last_sync),
            }
            for r in devices
        ],
    }


@router.get("/{user_id}/timeline")
def timeline(
    user_id: str,
    months: int = Query(2, ge=1, le=6),
    app: str | None = None,
    viewer: Viewer = Depends(get_viewer),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Everything this person did, newest first, in plain English, grouped by local day.
    Repeats of the same action in a row (e.g. Gemini summaries) collapse into one line."""
    u = _user_or_404(db, viewer, user_id)
    since = datetime.now(UTC) - timedelta(days=30 * months)
    params = {"t": viewer.tenant_id, "e": u.primary_email, "s": since}
    counts = {
        r.app: r.n
        for r in db.execute(
            text(
                """SELECT app, COUNT(*) AS n FROM events
                   WHERE tenant_id = :t AND user_email = :e AND time >= :s GROUP BY app"""
            ),
            params,
        ).all()
    }
    rows = db.execute(
        text(
            f"""SELECT time, app, event_name, doc_title, country, params FROM events
                WHERE tenant_id = :t AND user_email = :e AND time >= :s
                  {"AND app = :app" if app else ""}
                ORDER BY time DESC LIMIT 3000"""
        ),
        {**params, **({"app": app} if app else {})},
    ).all()
    settings_row = db.get(TenantSettings, viewer.tenant_id)
    offset = utc_offset(settings_row.timezone if settings_row else "Asia/Kolkata")

    days: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        local_day = (r.time + offset).date().isoformat()
        line = describe(r.app, r.event_name, r.params, r.doc_title)
        items = days.setdefault(local_day, [])
        prev = items[-1] if items else None
        if prev and prev["app"] == r.app and prev["text"] == line:
            prev["count"] += 1
            prev["first"] = iso(r.time)  # rows are newest first
            continue
        items.append(
            {
                "time": iso(r.time),
                "first": iso(r.time),
                "count": 1,
                "app": r.app,
                "app_label": APP_LABEL.get(r.app, r.app.replace("_", " ").title()),
                "event": r.event_name,
                "text": line,
                "country": r.country,
            }
        )
    return {
        "days": [{"date": d, "items": items} for d, items in days.items()],
        "apps": [
            {"app": a, "label": APP_LABEL.get(a, a.replace("_", " ").title()), "count": n}
            for a, n in sorted(counts.items(), key=lambda kv: -kv[1])
        ],
        "truncated": len(rows) >= 3000,
    }
