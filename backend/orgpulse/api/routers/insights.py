"""Free extras: licences, onboarding, storage, meetings, after-hours, external sharing,
shared drives, groups hygiene, admin audit, sign-in map, risky apps, team comparison."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from orgpulse import geo
from orgpulse.api.deps import Viewer, get_db, get_viewer, require_admin
from orgpulse.api.routers.org import third_party_apps
from orgpulse.models import Tenant, TenantPlan, TenantSettings
from orgpulse.queries import iso, scope_sql, score_totals, scored_window, today, weights
from orgpulse.roles import roles_for
from orgpulse.scoring import daily_scores, week_start
from orgpulse.sync.mappers import APP_METRICS
from orgpulse.teams import team_sql
from orgpulse.timeutil import utc_offset

router = APIRouter(prefix="/api/insights", tags=["insights"])

ACTIVITY_APPS = ("login", "drive", "meet", "calendar", "chat", "gmail")


def _settings(db: Session, tenant_id: Any) -> TenantSettings:
    s = db.get(TenantSettings, tenant_id)
    return s or TenantSettings(
        tenant_id=tenant_id,
        licence_price_inr=0,
        work_start="09:00",
        work_end="19:00",
        timezone="Asia/Kolkata",
    )


@router.get("/licences")
def licences(
    viewer: Viewer = Depends(require_admin), db: Session = Depends(get_db)
) -> dict[str, Any]:
    t = viewer.tenant_id
    st = _settings(db, t)
    plan = db.get(TenantPlan, t)
    now = datetime.now(UTC)
    has_licence_data = bool(
        db.execute(
            text("SELECT 1 FROM licence_assignments WHERE tenant_id = :t LIMIT 1"), {"t": t}
        ).first()
    )
    holders_sql = (
        "SELECT DISTINCT user_email FROM licence_assignments WHERE tenant_id = :t"
        if has_licence_data
        else "SELECT primary_email FROM users WHERE tenant_id = :t AND NOT suspended AND NOT archived"
    )
    rows = db.execute(
        text(
            f"""SELECT h.user_email AS email, u.id, u.full_name, {team_sql("u")} AS department, u.suspended, u.last_login_time,
                       u.creation_time,
                       EXISTS (SELECT 1 FROM daily_usage d WHERE d.tenant_id = :t AND d.user_email = h.user_email
                               AND d.date >= :a AND d.metric IN ('dc','de','dv','es','mt','ch','cal') AND d.value > 0) AS used
                FROM ({holders_sql}) h(user_email)
                LEFT JOIN users u ON u.tenant_id = :t AND u.primary_email = h.user_email"""
        ),
        {"t": t, "a": today() - timedelta(days=33)},
    ).all()
    cut = now - timedelta(days=30)
    active = [
        r
        for r in rows
        if not r.suspended and ((r.last_login_time and r.last_login_time >= cut) or r.used)
    ]
    inactive = [r for r in rows if r not in active]
    assigned = len(rows)
    purchased = st.licences_purchased or (plan.licences_total if plan else None) or assigned
    idle = max(purchased - len(active), 0)
    by_sku = db.execute(
        text(
            "SELECT COALESCE(sku_name, sku_id) AS sku, COUNT(*) AS n FROM licence_assignments WHERE tenant_id = :t GROUP BY 1 ORDER BY n DESC"
        ),
        {"t": t},
    ).all()
    return {
        "source": "licensing" if has_licence_data else "directory (licensing scope not granted)",
        "purchased": purchased,
        "assigned": assigned,
        "active_30d": len(active),
        "unassigned": max(purchased - assigned, 0),
        "idle": idle,
        "price_inr": st.licence_price_inr,
        "monthly_waste_inr": round(idle * st.licence_price_inr, 2),
        "by_sku": [{"sku": r.sku, "count": r.n} for r in by_sku],
        "inactive": [
            {
                "id": r.id,
                "email": r.email,
                "name": r.full_name,
                "department": r.department,
                "suspended": bool(r.suspended),
                "last_login": iso(r.last_login_time),
            }
            for r in sorted(
                inactive, key=lambda r: r.last_login_time or datetime.min.replace(tzinfo=UTC)
            )
        ],
    }


@router.get("/onboarding")
def onboarding(
    viewer: Viewer = Depends(require_admin), db: Session = Depends(get_db)
) -> dict[str, Any]:
    t = viewer.tenant_id
    month_start = today().replace(day=1)
    joiners = db.execute(
        text(
            f"""SELECT id, primary_email, full_name, {team_sql("users")} AS department, title, creation_time,
                      last_login_time, manager_email
               FROM users WHERE tenant_id = :t AND creation_time >= :m ORDER BY creation_time DESC"""
        ),
        {"t": t, "m": datetime.combine(month_start - timedelta(days=31), datetime.min.time(), UTC)},
    ).all()
    w = weights(db, t)
    out_joiners = []
    for j in joiners:
        start = j.creation_time.date()
        rows = db.execute(
            text(
                "SELECT date, metric, value FROM daily_usage WHERE tenant_id = :t AND user_id = :u AND date BETWEEN :a AND :b"
            ),
            {"t": t, "u": j.id, "a": start, "b": start + timedelta(days=6)},
        ).all()
        scores = daily_scores([(r.date, r.metric, float(r.value)) for r in rows], w)
        first_login = db.execute(
            text(
                "SELECT MIN(time) FROM events WHERE tenant_id = :t AND app = 'login' AND user_email = :e AND event_name = 'login_success'"
            ),
            {"t": t, "e": j.primary_email},
        ).scalar()
        out_joiners.append(
            {
                "id": j.id,
                "email": j.primary_email,
                "name": j.full_name,
                "department": j.department,
                "title": j.title,
                "created": iso(j.creation_time),
                "first_login": iso(first_login),
                "last_login": iso(j.last_login_time),
                "manager": j.manager_email,
                "first_week_score": round(sum(scores.values()), 1),
                "first_week_active_days": sum(1 for v in scores.values() if v > 0),
                "this_month": j.creation_time.date() >= month_start,
            }
        )
    leavers = db.execute(
        text(
            f"""SELECT u.id, u.primary_email, u.full_name, {team_sql("u")} AS department, u.suspension_reason, u.last_login_time,
                      EXISTS (SELECT 1 FROM licence_assignments l WHERE l.tenant_id = u.tenant_id AND l.user_email = u.primary_email) AS licensed,
                      (SELECT value FROM daily_usage d WHERE d.tenant_id = u.tenant_id AND d.user_id = u.id
                         AND d.metric = 'st_drive' ORDER BY date DESC LIMIT 1) AS drive_mb
               FROM users u WHERE u.tenant_id = :t AND u.suspended ORDER BY u.last_login_time DESC NULLS LAST"""
        ),
        {"t": t},
    ).all()
    return {
        "joiners": out_joiners,
        "leavers": [
            {
                "id": r.id,
                "email": r.primary_email,
                "name": r.full_name,
                "department": r.department,
                "reason": r.suspension_reason,
                "last_login": iso(r.last_login_time),
                "licensed": bool(r.licensed),
                "drive_mb": float(r.drive_mb) if r.drive_mb is not None else None,
                "owns_files": bool(r.drive_mb and r.drive_mb > 0),
            }
            for r in leavers
        ],
    }


@router.get("/storage")
def storage(
    viewer: Viewer = Depends(require_admin), db: Session = Depends(get_db)
) -> dict[str, Any]:
    t = viewer.tenant_id
    latest = db.execute(
        text(
            f"""WITH last AS (SELECT MAX(date) AS d FROM daily_usage WHERE tenant_id = :t AND metric = 'st_used')
               SELECT u.id, u.primary_email, u.full_name, {team_sql("u")} AS department,
                      MAX(d.value) FILTER (WHERE d.metric = 'st_used') AS used,
                      MAX(d.value) FILTER (WHERE d.metric = 'st_total') AS total,
                      MAX(d.value) FILTER (WHERE d.metric = 'st_drive') AS drive,
                      MAX(d.value) FILTER (WHERE d.metric = 'st_gmail') AS gmail
               FROM daily_usage d JOIN last ON d.date = last.d
               JOIN users u ON u.tenant_id = d.tenant_id AND u.id = d.user_id
               WHERE d.tenant_id = :t AND d.metric LIKE 'st_%'
               GROUP BY u.id, u.primary_email, u.full_name, 4"""
        ),
        {"t": t},
    ).all()
    items = [
        {
            "id": r.id,
            "email": r.primary_email,
            "name": r.full_name,
            "department": r.department,
            "used_mb": float(r.used or 0),
            "total_mb": float(r.total) if r.total and r.total > 0 else None,
            "drive_mb": float(r.drive or 0),
            "gmail_mb": float(r.gmail or 0),
            "pct": round(100 * float(r.used or 0) / float(r.total), 1)
            if r.total and r.total > 0
            else None,
        }
        for r in latest
    ]
    trend = db.execute(
        text(
            """SELECT date, SUM(value) AS mb FROM daily_usage WHERE tenant_id = :t AND metric = 'st_used'
               AND EXTRACT(isodow FROM date) = 1 GROUP BY date ORDER BY date"""
        ),
        {"t": t},
    ).all()
    return {
        "total_used_mb": round(sum(i["used_mb"] for i in items), 1),
        "top": sorted(items, key=lambda i: -i["used_mb"])[:25],
        "near_quota": sorted(
            (i for i in items if i["pct"] is not None and i["pct"] >= 90),
            key=lambda i: -(i["pct"] or 0),
        ),
        "trend": [
            {"date": r.date.isoformat(), "used_gb": round(float(r.mb) / 1024, 2)} for r in trend
        ],
    }


@router.get("/meetings")
def meetings(viewer: Viewer = Depends(get_viewer), db: Session = Depends(get_db)) -> dict[str, Any]:
    t = viewer.tenant_id
    cond, params = scope_sql(viewer.scope_list(), "e.user_email")
    st = _settings(db, t)
    rows = db.execute(
        text(
            f"""SELECT e.user_email, u.id, u.full_name, {team_sql("u")} AS dept,
                       e.time, (e.params->>'duration_seconds')::numeric AS secs
                FROM events e LEFT JOIN users u ON u.tenant_id = e.tenant_id AND u.primary_email = e.user_email
                WHERE e.tenant_id = :t AND e.app = 'meet' AND e.event_name = 'call_ended'
                  AND e.user_email IS NOT NULL  -- external/anonymous joiners aren't anyone's load
                  AND e.time >= :s AND {cond}"""
        ),
        {"t": t, "s": datetime.now(UTC) - timedelta(weeks=8), **params},
    ).all()
    per_person: dict[str, dict[str, Any]] = {}
    weekday_hours: dict[int, float] = defaultdict(float)
    day_totals: dict[tuple[str, str], float] = defaultdict(float)
    weeks = 8
    tz = ZoneInfo(st.timezone)
    for r in rows:
        local = r.time.astimezone(tz)
        hours = float(r.secs or 0) / 3600
        p = per_person.setdefault(
            r.user_email,
            {
                "id": r.id,
                "email": r.user_email,
                "name": r.full_name,
                "department": r.dept,
                "hours": 0.0,
                "calls": 0,
                "weeks": defaultdict(float),
            },
        )
        p["hours"] += hours
        p["calls"] += 1
        p["weeks"][week_start(local.date()).isoformat()] += hours
        weekday_hours[local.weekday()] += hours
        day_totals[(r.user_email, local.date().isoformat())] += hours

    people = []
    for p in per_person.values():
        people.append(
            {
                "id": p["id"],
                "email": p["email"],
                "name": p["name"],
                "department": p["department"],
                "hours_per_week": round(p["hours"] / weeks, 1),
                "calls": p["calls"],
                "heavy_days": sum(
                    1 for (e, _), h in day_totals.items() if e == p["email"] and h >= 4
                ),
                "weeks": [{"week": k, "hours": round(v, 1)} for k, v in sorted(p["weeks"].items())],
            }
        )
    teams: dict[str, list[float]] = defaultdict(list)
    for p in people:
        teams[p["department"]].append(p["hours_per_week"])
    names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    return {
        "people": sorted(people, key=lambda p: -p["hours_per_week"]),
        "teams": sorted(
            (
                {"department": k, "avg_hours_per_week": round(sum(v) / len(v), 1), "people": len(v)}
                for k, v in teams.items()
            ),
            key=lambda x: -x["avg_hours_per_week"],
        ),
        "by_weekday": [
            {"day": names[i], "hours": round(weekday_hours.get(i, 0) / weeks, 1)} for i in range(7)
        ],
        "heavy_day_threshold_hours": 4,
    }


MIN_TEAM_SIZE = 3  # smaller teams are hidden so no individual can be singled out


def _pct(part: float, whole: float) -> float:
    return round(100 * part / whole, 1) if whole else 0.0


@router.get("/after-hours")
def after_hours(
    days: int = Query(30, ge=7, le=90),
    viewer: Viewer = Depends(get_viewer),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Burnout signal per team (never a ranking of individuals).

    outside = weekday events outside working hours + all weekend events
    late night = 22:00-06:00 local, any day; early = weekday before working hours start.
    """
    t = viewer.tenant_id
    st = _settings(db, t)
    cond, params = scope_sql(viewer.scope_list(), "e.user_email")
    now = datetime.now(UTC)
    offset = utc_offset(st.timezone)
    # Trend covers whole Monday-Sunday weeks only: a partial first week skews the share.
    local_today = (now + offset).date()
    trend_start = local_today - timedelta(days=local_today.weekday(), weeks=11)
    trend_since = datetime.combine(trend_start, datetime.min.time(), UTC) - offset
    local = "((e.time AT TIME ZONE 'UTC') + :offset)"
    rows = db.execute(
        text(
            f"""SELECT {team_sql("u")} AS team, e.user_email, e.app,
                       (e.time >= :cur) AS current,
                       (e.time >= :prev AND e.time < :cur) AS previous,
                       date_trunc('week', {local})::date AS wk,
                       EXTRACT(isodow FROM {local})::int AS dow,
                       EXTRACT(hour FROM {local})::int AS hr,
                       (EXTRACT(isodow FROM {local}) < 6 AND {local}::time < CAST(:ws AS time)) AS early,
                       (EXTRACT(isodow FROM {local}) < 6 AND {local}::time >= CAST(:we AS time)) AS late_eve,
                       (EXTRACT(hour FROM {local}) >= 22 OR EXTRACT(hour FROM {local}) < 6) AS night,
                       COUNT(*) AS n
                FROM events e JOIN users u ON u.tenant_id = e.tenant_id AND u.primary_email = e.user_email
                WHERE e.tenant_id = :t AND e.app = ANY(:apps) AND e.time >= :since AND {cond}
                GROUP BY 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11"""
        ),
        {
            "t": t,
            "apps": list(ACTIVITY_APPS),
            "offset": offset,
            "ws": st.work_start,
            "we": st.work_end,
            **params,
            "cur": now - timedelta(days=days),
            "prev": now - timedelta(days=2 * days),
            # the previous period (for the comparison) and the 12 whole weeks of the trend
            "since": min(now - timedelta(days=2 * days), trend_since),
        },
    ).all()

    def blank() -> dict[str, Any]:
        return {
            "total": 0, "after": 0, "weekend": 0, "night": 0, "early": 0,
            "people": set(), "people_outside": set(),
            "prev_total": 0, "prev_outside": 0,
            "heat": defaultdict(int), "apps": defaultdict(lambda: [0, 0]), "weeks": defaultdict(lambda: [0, 0]),
        }  # fmt: skip

    org = blank()
    teams: dict[str, dict[str, Any]] = defaultdict(blank)
    for r in rows:
        weekend = r.dow >= 6
        after = not weekend and (r.early or r.late_eve)
        outside = weekend or after
        for agg in (org, teams[r.team]):
            if r.wk >= trend_start:
                agg["weeks"][r.wk.isoformat()][0] += r.n
                agg["weeks"][r.wk.isoformat()][1] += r.n if outside else 0
            if r.previous:
                agg["prev_total"] += r.n
                agg["prev_outside"] += r.n if outside else 0
            if not r.current:
                continue
            agg["total"] += r.n
            agg["after"] += r.n if after else 0
            agg["weekend"] += r.n if weekend else 0
            agg["night"] += r.n if r.night else 0
            agg["early"] += r.n if r.early and not weekend else 0
            agg["people"].add(r.user_email)
            if outside:
                agg["people_outside"].add(r.user_email)
            agg["heat"][(r.dow, r.hr)] += r.n
            agg["apps"][r.app][0] += r.n
            agg["apps"][r.app][1] += r.n if outside else 0

    def summary(agg: dict[str, Any], detail: bool) -> dict[str, Any]:
        total = agg["total"]
        outside = agg["after"] + agg["weekend"]
        peak = max(agg["heat"].items(), key=lambda kv: kv[1])[0] if agg["heat"] else None
        out: dict[str, Any] = {
            "people": len(agg["people"]),
            "events": total,
            "outside_pct": _pct(outside, total),
            "after_hours_pct": _pct(agg["after"], total),
            "weekend_pct": _pct(agg["weekend"], total),
            "late_night_pct": _pct(agg["night"], total),
            "early_pct": _pct(agg["early"], total),
            "people_outside": len(agg["people_outside"]),
            "people_outside_pct": _pct(len(agg["people_outside"]), len(agg["people"])),
            "prev_outside_pct": _pct(agg["prev_outside"], agg["prev_total"])
            if agg["prev_total"]
            else None,
            "peak": {"dow": peak[0], "hour": peak[1]} if peak else None,
            "trend": [
                {"week": wk, "outside_pct": _pct(v[1], v[0]), "events": v[0]}
                for wk, v in sorted(agg["weeks"].items())
            ],
        }
        if out["prev_outside_pct"] is not None:
            out["change_pts"] = round(out["outside_pct"] - out["prev_outside_pct"], 1)
        else:
            out["change_pts"] = None
        if detail:
            out["heatmap"] = [
                {"dow": d, "hour": h, "count": n} for (d, h), n in agg["heat"].items()
            ]
            out["by_app"] = sorted(
                (
                    {"app": app, "events": v[0], "outside": v[1], "outside_pct": _pct(v[1], v[0])}
                    for app, v in agg["apps"].items()
                ),
                key=lambda x: -x["outside"],
            )
        return out

    visible, hidden = [], []
    for name, agg in teams.items():
        if len(agg["people"]) >= MIN_TEAM_SIZE or viewer.scope is not None:
            visible.append({"team": name, **summary(agg, detail=True)})
        else:
            hidden.append({"team": name, "people": len(agg["people"])})
    org_summary = summary(org, detail=True)
    return {
        "window_days": days,
        "work_hours": {"start": st.work_start, "end": st.work_end, "timezone": st.timezone},
        "org": org_summary,
        "teams": sorted(visible, key=lambda x: -x["outside_pct"]),
        "hidden_teams": sorted(hidden, key=lambda x: x["team"]),
        "min_team_size": MIN_TEAM_SIZE,
        "heatmap": org_summary["heatmap"],
    }


@router.get("/external")
def external(
    viewer: Viewer = Depends(require_admin), db: Session = Depends(get_db)
) -> dict[str, Any]:
    t = viewer.tenant_id
    tenant = db.get(Tenant, t)
    own = tenant.domain if tenant else ""
    s = datetime.now(UTC) - timedelta(days=30)
    summary = db.execute(
        text(
            """SELECT COUNT(DISTINCT doc_id) AS files, COUNT(DISTINCT user_email) AS people,
                      COUNT(DISTINCT doc_id) FILTER (WHERE visibility IN ('public_on_the_web', 'people_with_link')) AS public
               FROM events WHERE tenant_id = :t AND app = 'drive' AND is_external IS TRUE AND time >= :s"""
        ),
        {"t": t, "s": s},
    ).one()
    domains = db.execute(
        text(
            """SELECT lower(split_part(params->>'target_user', '@', 2)) AS domain, COUNT(DISTINCT doc_id) AS files,
                      COUNT(DISTINCT user_email) AS people
               FROM events WHERE tenant_id = :t AND app = 'drive' AND time >= :s
                 AND params->>'target_user' LIKE '%@%' AND lower(split_part(params->>'target_user', '@', 2)) <> :own
               GROUP BY 1 ORDER BY files DESC LIMIT 20"""
        ),
        {"t": t, "s": s, "own": own},
    ).all()
    public = db.execute(
        text(
            """SELECT DISTINCT ON (doc_id) doc_id, doc_title, doc_type, visibility, user_email, time
               FROM events WHERE tenant_id = :t AND app = 'drive' AND time >= :s
                 AND visibility IN ('public_on_the_web', 'people_with_link')
               ORDER BY doc_id, time DESC"""
        ),
        {"t": t, "s": s},
    ).all()
    sharers = db.execute(
        text(
            """SELECT user_email, COUNT(DISTINCT doc_id) AS files FROM events
               WHERE tenant_id = :t AND app = 'drive' AND is_external IS TRUE AND time >= :s
                 AND user_email IS NOT NULL
               GROUP BY 1 ORDER BY files DESC LIMIT 15"""
        ),
        {"t": t, "s": s},
    ).all()
    return {
        "files": summary.files,
        "people": summary.people,
        "public_links": summary.public,
        "top_domains": [
            {"domain": r.domain, "files": r.files, "people": r.people} for r in domains
        ],
        "public": [
            {
                "doc_id": r.doc_id,
                "title": r.doc_title,
                "type": r.doc_type,
                "visibility": r.visibility,
                "user": r.user_email,
                "time": iso(r.time),
            }
            for r in sorted(public, key=lambda r: r.time, reverse=True)
        ],
        "top_sharers": [{"user": r.user_email, "files": r.files} for r in sharers],
    }


@router.get("/shared-drives")
def shared_drives(
    viewer: Viewer = Depends(require_admin), db: Session = Depends(get_db)
) -> dict[str, Any]:
    rows = db.execute(
        text(
            """SELECT id, name, created_time, hidden, member_count, external_member_count, members
               FROM shared_drives WHERE tenant_id = :t ORDER BY external_member_count DESC, name"""
        ),
        {"t": viewer.tenant_id},
    ).all()
    return {
        "drives": [
            {
                "id": r.id,
                "name": r.name,
                "created": iso(r.created_time),
                "hidden": r.hidden,
                "members": r.member_count,
                "external_members": r.external_member_count,
                "organizers": [
                    m.get("emailAddress")
                    for m in (r.members or {}).get("items", [])
                    if m.get("role") == "organizer"
                ][:10],
            }
            for r in rows
        ]
    }


@router.get("/groups")
def groups(
    viewer: Viewer = Depends(require_admin), db: Session = Depends(get_db)
) -> dict[str, Any]:
    """Every group with its members and hygiene flags (empty, no owner, outsiders, ...)."""
    t = viewer.tenant_id
    tenant = db.get(Tenant, t)
    own = (tenant.domain if tenant else "").lower()
    rows = db.execute(
        text(
            """SELECT id, email, name, description, direct_members_count, admin_created,
                      raw->>'aliases' AS aliases
               FROM groups WHERE tenant_id = :t ORDER BY email"""
        ),
        {"t": t},
    ).all()
    members_by_group: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for m in db.execute(
        text(
            """SELECT m.group_id, m.email, m.role, m.type, m.status, u.id AS user_id, u.full_name,
                      u.suspended
               FROM group_members m
               LEFT JOIN users u ON u.tenant_id = m.tenant_id AND u.primary_email = m.email
               WHERE m.tenant_id = :t"""
        ),
        {"t": t},
    ).all():
        domain = (m.email or "").split("@")[-1].lower()
        members_by_group[m.group_id].append(
            {
                "email": m.email,
                "name": m.full_name,
                "user_id": m.user_id,
                "role": m.role or "MEMBER",
                "type": m.type or "USER",
                "status": m.status,
                "external": bool(m.email) and m.type != "CUSTOMER" and domain != own,
                "suspended": bool(m.suspended),
            }
        )

    items = []
    for r in rows:
        mem = sorted(
            members_by_group.get(r.id, []),
            key=lambda x: ({"OWNER": 0, "MANAGER": 1}.get(x["role"], 2), x["email"] or ""),
        )
        owners = [x for x in mem if x["role"] == "OWNER"]
        issues = []
        if not mem:
            issues.append("empty")
        elif not owners:
            issues.append("no_owner")
        if any(x["external"] for x in mem):
            issues.append("external")
        if any(x["suspended"] for x in mem):
            issues.append("suspended_members")
        if owners and all(x["suspended"] for x in owners):
            issues.append("owner_suspended")
        items.append(
            {
                "id": r.id,
                "email": r.email,
                "name": r.name,
                "description": r.description,
                "created_by": "admin" if r.admin_created else "user",
                "members": len(mem),
                "owners": len(owners),
                "managers": sum(1 for x in mem if x["role"] == "MANAGER"),
                "nested_groups": sum(1 for x in mem if x["type"] == "GROUP"),
                "external": sum(1 for x in mem if x["external"]),
                "external_emails": [x["email"] for x in mem if x["external"]][:20],
                "suspended_members": sum(1 for x in mem if x["suspended"]),
                "issues": issues,
                "member_list": mem[:200],
            }
        )

    def having(issue: str) -> list[dict[str, Any]]:
        return [i for i in items if issue in i["issues"]]

    return {
        "total": len(items),
        "groups": items,
        "members_total": sum(i["members"] for i in items),
        "healthy": sum(1 for i in items if not i["issues"]),
        "empty": having("empty"),
        "external": having("external"),
        "no_owner": having("no_owner"),
        "suspended_members": having("suspended_members"),
        "owner_suspended": having("owner_suspended"),
    }


@router.get("/admins")
def admins(
    viewer: Viewer = Depends(require_admin), db: Session = Depends(get_db)
) -> dict[str, Any]:
    rows = db.execute(
        text(
            """SELECT id, primary_email, full_name, is_admin, admin_role, last_login_time, is_enrolled_in_2sv,
                      is_enforced_in_2sv, suspended
               FROM users WHERE tenant_id = :t AND (is_admin OR is_delegated_admin OR admin_role IS NOT NULL)
               ORDER BY is_admin DESC, primary_email"""
        ),
        {"t": viewer.tenant_id},
    ).all()
    now = datetime.now(UTC)
    items = [
        {
            "id": r.id,
            "email": r.primary_email,
            "name": r.full_name,
            "roles": (roles := roles_for(r.admin_role, r.is_admin) or ["Delegated admin"]),
            "role": "; ".join(roles),  # for CSV exports
            "super_admin": r.is_admin,
            "last_login": iso(r.last_login_time),
            "days_since_login": (now - r.last_login_time).days if r.last_login_time else None,
            "twosv": r.is_enrolled_in_2sv,
            "twosv_enforced": r.is_enforced_in_2sv,
            "suspended": r.suspended,
        }
        for r in rows
    ]
    return {"admins": items, "without_2sv": sum(1 for i in items if not i["twosv"])}


@router.get("/signin-map")
def signin_map(
    viewer: Viewer = Depends(require_admin), db: Session = Depends(get_db)
) -> dict[str, Any]:
    t = viewer.tenant_id
    s = datetime.now(UTC) - timedelta(days=30)
    points = db.execute(
        text(
            """SELECT ROUND(lat::numeric, 1) AS lat, ROUND(lon::numeric, 1) AS lon, MAX(city) AS city,
                      MAX(country) AS country, COUNT(*) AS n, COUNT(DISTINCT user_email) AS users,
                      COUNT(*) FILTER (WHERE event_name = 'login_failure') AS failures
               FROM events WHERE tenant_id = :t AND app = 'login' AND time >= :s AND lat IS NOT NULL
               GROUP BY 1, 2 ORDER BY n DESC LIMIT 500"""
        ),
        {"t": t, "s": s},
    ).all()
    countries = db.execute(
        text(
            """SELECT country, COUNT(*) AS n, COUNT(DISTINCT user_email) AS users,
                      COUNT(*) FILTER (WHERE event_name = 'login_failure') AS failures
               FROM events WHERE tenant_id = :t AND app = 'login' AND time >= :s AND country IS NOT NULL
               GROUP BY 1 ORDER BY n DESC"""
        ),
        {"t": t, "s": s},
    ).all()
    new_locations = db.execute(
        text(
            """SELECT e.user_email, e.country, MIN(e.time) AS first_seen FROM events e
               WHERE e.tenant_id = :t AND e.app = 'login' AND e.event_name = 'login_success'
                 AND e.time >= :w AND e.country IS NOT NULL
                 AND NOT EXISTS (SELECT 1 FROM events p WHERE p.tenant_id = :t AND p.app = 'login'
                                 AND p.user_email = e.user_email AND p.country = e.country AND p.time < :w)
                 AND EXISTS (SELECT 1 FROM events p WHERE p.tenant_id = :t AND p.app = 'login'
                                 AND p.user_email = e.user_email AND p.time < :w)
               GROUP BY 1, 2 ORDER BY first_seen DESC"""
        ),
        {"t": t, "w": datetime.now(UTC) - timedelta(days=7)},
    ).all()
    return {
        "points": [
            {
                "lat": float(r.lat),
                "lon": float(r.lon),
                "city": r.city,
                "country": r.country,
                "signins": r.n,
                "users": r.users,
                "failures": r.failures,
            }
            for r in points
        ],
        "countries": [
            {"country": r.country, "signins": r.n, "users": r.users, "failures": r.failures}
            for r in countries
        ],
        "new_locations": [
            {"user": r.user_email, "country": r.country, "first_seen": iso(r.first_seen)}
            for r in new_locations
        ],
        "geoip": geo.available(),
    }


@router.get("/risky-apps")
def risky_apps(
    viewer: Viewer = Depends(require_admin), db: Session = Depends(get_db)
) -> dict[str, Any]:
    apps = third_party_apps(db, viewer.tenant_id)
    return {"apps": apps, "unused_90d": [a for a in apps if a["unused_90d"]]}


@router.get("/teams")
def teams(viewer: Viewer = Depends(get_viewer), db: Session = Depends(get_db)) -> dict[str, Any]:
    """Team-by-team comparison (team = department, else org unit) with each team's members."""
    t = viewer.tenant_id
    scope = viewer.scope_list()
    cond, params = scope_sql(scope, "u.primary_email")
    now = datetime.now(UTC)
    users = db.execute(
        text(
            f"""SELECT u.id, u.primary_email, u.full_name, u.title, u.org_unit_path, u.is_admin,
                       u.admin_role IS NOT NULL AS has_role, u.is_enrolled_in_2sv, u.last_login_time,
                       {team_sql("u")} AS dept
                FROM users u WHERE u.tenant_id = :t AND NOT u.suspended AND NOT u.archived AND {cond}"""
        ),
        {"t": t, **params},
    ).all()
    start, end = scored_window(30)
    totals = score_totals(db, t, start, end, scope)

    def per_user(sql: str, **extra: Any) -> dict[str, float]:
        return {
            r.k: float(r.v or 0)
            for r in db.execute(text(sql), {"t": t, "a": start, "b": end, **extra}).all()
        }

    app_users: dict[str, set[str]] = {
        app: {
            r.user_id
            for r in db.execute(
                text(
                    """SELECT DISTINCT user_id FROM daily_usage WHERE tenant_id = :t
                       AND date BETWEEN :a AND :b AND metric = ANY(:m) AND value > 0"""
                ),
                {"t": t, "a": start, "b": end, "m": list(metrics)},
            ).all()
        }
        for app, metrics in APP_METRICS.items()
    }
    active_ids = set().union(*app_users.values()) if app_users else set()
    meet_hours = per_user(  # hours in Meet over the last 4 weeks, by email
        """SELECT user_email AS k, SUM((params->>'duration_seconds')::numeric) / 3600.0 AS v
           FROM events WHERE tenant_id = :t AND app = 'meet' AND event_name = 'call_ended'
             AND user_email IS NOT NULL AND time >= :since GROUP BY 1""",
        since=now - timedelta(weeks=4),
    )
    ext_shares = per_user(
        """SELECT user_email AS k, COUNT(DISTINCT doc_id) AS v FROM events
           WHERE tenant_id = :t AND app = 'drive' AND is_external IS TRUE AND time >= :since
             AND user_email IS NOT NULL GROUP BY 1""",
        since=now - timedelta(days=30),
    )
    storage_mb = per_user(
        """SELECT d.user_id AS k, d.value AS v FROM daily_usage d
           WHERE d.tenant_id = :t AND d.metric = 'st_used'
             AND d.date = (SELECT MAX(date) FROM daily_usage WHERE tenant_id = :t AND metric = 'st_used')"""
    )
    st = _settings(db, t)
    local = "((e.time AT TIME ZONE 'UTC') + :offset)"
    rhythm = {
        r.dept: r
        for r in db.execute(
            text(
                f"""SELECT {team_sql("u")} AS dept, COUNT(*) AS total,
                       COUNT(*) FILTER (WHERE EXTRACT(isodow FROM {local}) >= 6) AS weekend,
                       COUNT(*) FILTER (WHERE EXTRACT(isodow FROM {local}) < 6 AND
                           ({local}::time < CAST(:ws AS time) OR {local}::time >= CAST(:we AS time))) AS after
                    FROM events e JOIN users u ON u.tenant_id = e.tenant_id AND u.primary_email = e.user_email
                    WHERE e.tenant_id = :t AND e.app = ANY(:apps) AND e.time >= :s AND {cond}
                    GROUP BY 1"""
            ),
            {
                "t": t,
                "apps": list(ACTIVITY_APPS),
                "s": now - timedelta(days=30),
                "offset": utc_offset(st.timezone),
                "ws": st.work_start,
                "we": st.work_end,
                **params,
            },
        ).all()
    }

    groups: dict[str, list[Any]] = defaultdict(list)
    for u in users:
        groups[u.dept].append(u)
    out = []
    for name, members in groups.items():
        n = len(members)
        ids = [m.id for m in members]
        emails = [m.primary_email for m in members]
        r = rhythm.get(name)
        after_pct = weekend_pct = None
        # Teams under 3 people stay hidden so no individual can be singled out.
        if r is not None and r.total and (n >= 3 or viewer.scope is not None):
            after_pct = round(100 * r.after / r.total, 1)
            weekend_pct = round(100 * r.weekend / r.total, 1)
        out.append(
            {
                "department": name,
                "users": n,
                "avg_score": round(sum(totals.get(i, {}).get("score", 0) for i in ids) / n, 1),
                "active_pct": round(100 * sum(1 for i in ids if i in active_ids) / n, 1),
                "twosv_pct": round(100 * sum(1 for m in members if m.is_enrolled_in_2sv) / n, 1),
                "adoption": {
                    app: round(100 * len(set(ids) & us) / n, 1) for app, us in app_users.items()
                },
                "meet_hours_per_week": round(sum(meet_hours.get(e, 0) for e in emails) / 4 / n, 1),
                "after_hours_pct": after_pct,
                "weekend_pct": weekend_pct,
                "external_shares_30d": int(sum(ext_shares.get(e, 0) for e in emails)),
                "storage_gb": round(sum(storage_mb.get(i, 0) for i in ids) / 1024, 1),
                "inactive_30d": sum(
                    1
                    for m in members
                    if not m.last_login_time or m.last_login_time < now - timedelta(days=30)
                ),
                "admins": sum(1 for m in members if m.is_admin or m.has_role),
                "no_2sv": sum(1 for m in members if not m.is_enrolled_in_2sv),
                "members": sorted(
                    (
                        {
                            "id": m.id,
                            "name": m.full_name or m.primary_email,
                            "email": m.primary_email,
                            "title": m.title,
                            "score": round(totals.get(m.id, {}).get("score", 0), 1),
                            "active_days": totals.get(m.id, {}).get("active_days", 0),
                            "meet_hours_per_week": round(meet_hours.get(m.primary_email, 0) / 4, 1),
                            "twosv": m.is_enrolled_in_2sv,
                            "admin": bool(m.is_admin or m.has_role),
                            "last_login": iso(m.last_login_time),
                        }
                        for m in members
                    ),
                    key=lambda x: -x["score"],
                ),
            }
        )
    return {
        "teams": sorted(out, key=lambda r: (-r["users"], r["department"])),
        "window": {"start": start.isoformat(), "end": end.isoformat()},
        "team_rule": "department when set in Google Directory, otherwise the org unit",
    }
