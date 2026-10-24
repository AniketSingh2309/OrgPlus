"""Org-wide pages: Apps, Security, Devices (admins only)."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from orgpulse.api.deps import Viewer, get_db, require_admin
from orgpulse.api.routers.overview import app_adoption
from orgpulse.queries import iso, scored_window
from orgpulse.risk import RISK_ORDER, risk_score

router = APIRouter(prefix="/api", tags=["org"])


def third_party_apps(db: Session, tenant_id: Any) -> list[dict[str, Any]]:
    """Token grants grouped per OAuth client, with risk and last use (token audit events)."""
    grants = db.execute(
        text(
            """SELECT client_id, display_text, anonymous, native_app, user_id, user_email, scopes, risk
               FROM app_tokens WHERE tenant_id = :t"""
        ),
        {"t": tenant_id},
    ).all()
    last_used = {
        r.client_id: r.last
        for r in db.execute(
            text(
                """SELECT params->>'client_id' AS client_id, MAX(time) AS last FROM events
                   WHERE tenant_id = :t AND app = 'token' GROUP BY 1"""
            ),
            {"t": tenant_id},
        ).all()
    }
    grouped: dict[str, dict[str, Any]] = {}
    for g in grants:
        a = grouped.setdefault(
            g.client_id,
            {
                "name": None,
                "users": set(),
                "emails": set(),
                "scopes": set(),
                "risk": "low",
                "unverified": False,
                "native": False,
            },
        )
        a["name"] = a["name"] or g.display_text
        a["users"].add(g.user_id)
        if g.user_email:
            a["emails"].add(g.user_email)
        a["scopes"].update(g.scopes or [])
        a["unverified"] |= bool(g.anonymous)
        a["native"] |= bool(g.native_app)
        if RISK_ORDER.get(g.risk or "low", 0) > RISK_ORDER[a["risk"]]:
            a["risk"] = g.risk

    cutoff = datetime.now(UTC) - timedelta(days=90)
    apps = []
    for client_id, a in grouped.items():
        scopes = sorted(a["scopes"])
        last = last_used.get(client_id)
        apps.append(
            {
                "client_id": client_id,
                "name": a["name"] or client_id,
                "users": len(a["users"]),
                "emails": sorted(a["emails"])[:50],
                "scopes": scopes,
                "risk": a["risk"],
                "risk_score": risk_score(scopes, unverified=a["unverified"], users=len(a["users"])),
                "unverified": a["unverified"],
                "native": a["native"],
                "last_used": iso(last),
                "unused_90d": last is None or last < cutoff,
            }
        )
    apps.sort(key=lambda a: (-RISK_ORDER[a["risk"]], -a["risk_score"], -a["users"]))
    return apps


@router.get("/apps")
def apps_page(
    viewer: Viewer = Depends(require_admin), db: Session = Depends(get_db)
) -> dict[str, Any]:
    t = viewer.tenant_id
    weekly = db.execute(
        text(
            """SELECT date_trunc('week', date)::date AS wk,
                      CASE WHEN metric IN ('dc','de','dv') THEN 'drive' WHEN metric IN ('es','er') THEN 'gmail'
                           WHEN metric IN ('mt','mh') THEN 'meet' WHEN metric = 'ch' THEN 'chat'
                           WHEN metric = 'cal' THEN 'calendar' END AS app,
                      COUNT(DISTINCT user_id) AS users
               FROM daily_usage WHERE tenant_id = :t AND date >= :s AND value > 0
                 AND metric IN ('dc','de','dv','es','er','mt','mh','ch','cal')
               GROUP BY 1, 2 ORDER BY 1"""
        ),
        {"t": t, "s": scored_window(26 * 7)[0]},
    ).all()
    trend: dict[str, dict[str, Any]] = defaultdict(dict)
    for r in weekly:
        trend[r.wk.isoformat()][r.app] = r.users
    sso = db.execute(
        text(
            """SELECT COALESCE(params->>'application_name', 'Unknown') AS app,
                      COUNT(DISTINCT user_email) AS users, COUNT(*) FILTER (WHERE event_name = 'login_success') AS ok,
                      COUNT(*) FILTER (WHERE event_name = 'login_failure') AS failed, MAX(time) AS last
               FROM events WHERE tenant_id = :t AND app = 'saml' AND time >= :s GROUP BY 1 ORDER BY users DESC"""
        ),
        {"t": t, "s": datetime.now(UTC) - timedelta(days=30)},
    ).all()
    third = third_party_apps(db, t)
    return {
        "google_apps": app_adoption(db, t, None),
        "adoption_trend": [{"week": k, **v} for k, v in sorted(trend.items())],
        "sso_apps": [
            {
                "app": r.app,
                "users": r.users,
                "signins": r.ok,
                "failures": r.failed,
                "last": iso(r.last),
            }
            for r in sso
        ],
        "third_party": third,
        "risk_counts": {
            k: sum(1 for a in third if a["risk"] == k) for k in ("high", "medium", "low")
        },
    }


@router.get("/security")
def security(
    signin_filter: Literal["all", "failed", "suspicious"] = "all",
    viewer: Viewer = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    t = viewer.tenant_id
    now = datetime.now(UTC)
    gaps = db.execute(
        text(
            """SELECT id, primary_email, full_name, department, is_admin, admin_role, last_login_time
               FROM users WHERE tenant_id = :t AND NOT suspended AND NOT archived AND NOT is_enrolled_in_2sv
               ORDER BY (is_admin OR admin_role IS NOT NULL) DESC, last_login_time DESC NULLS LAST"""
        ),
        {"t": t},
    ).all()
    totals = db.execute(
        text(
            """SELECT COUNT(*) FILTER (WHERE NOT suspended AND NOT archived) AS live,
                      COUNT(*) FILTER (WHERE NOT suspended AND NOT archived AND is_enrolled_in_2sv) AS enrolled,
                      COUNT(*) FILTER (WHERE NOT suspended AND NOT archived AND is_enforced_in_2sv) AS enforced
               FROM users WHERE tenant_id = :t"""
        ),
        {"t": t},
    ).one()
    external = db.execute(
        text(
            """SELECT time, user_email, event_name, doc_id, doc_title, doc_type, visibility,
                      params->>'target_user' AS target
               FROM events WHERE tenant_id = :t AND app = 'drive' AND is_external IS TRUE AND time >= :s
               ORDER BY time DESC LIMIT 300"""
        ),
        {"t": t, "s": now - timedelta(days=30)},
    ).all()
    extra = {
        "failed": "AND event_name = 'login_failure'",
        "suspicious": "AND (event_name LIKE 'suspicious%' OR (params->>'is_suspicious')::boolean IS TRUE)",
        "all": "",
    }[signin_filter]
    signin_rows = db.execute(
        text(
            f"""SELECT time, user_email, event_name, ip, country, city, params->>'login_type' AS login_type,
                       (params->>'is_suspicious')::boolean AS suspicious
                FROM events WHERE tenant_id = :t AND app = 'login' AND time >= :s {extra}
                ORDER BY time DESC LIMIT 500"""
        ),
        {"t": t, "s": now - timedelta(days=7)},
    ).all()
    admin_rows = db.execute(
        text(
            """SELECT time, user_email, event_name, event_type, ip, params FROM events
               WHERE tenant_id = :t AND app = 'admin' AND time >= :s ORDER BY time DESC LIMIT 300"""
        ),
        {"t": t, "s": now - timedelta(days=30)},
    ).all()
    return {
        "twosv": {
            "users": totals.live,
            "enrolled": totals.enrolled,
            "enforced": totals.enforced,
            "gaps": [
                {
                    "id": r.id,
                    "email": r.primary_email,
                    "name": r.full_name,
                    "department": r.department,
                    "admin": bool(r.is_admin or r.admin_role),
                    "last_login": iso(r.last_login_time),
                }
                for r in gaps
            ],
        },
        "external_shares": [
            {
                "time": iso(r.time),
                "user": r.user_email,
                "event": r.event_name,
                "doc_id": r.doc_id,
                "title": r.doc_title,
                "type": r.doc_type,
                "visibility": r.visibility,
                "target": r.target,
            }
            for r in external
        ],
        "signins": [
            {
                "time": iso(r.time),
                "user": r.user_email,
                "event": r.event_name,
                "ip": r.ip,
                "country": r.country,
                "city": r.city,
                "login_type": r.login_type,
                "suspicious": bool(r.suspicious),
            }
            for r in signin_rows
        ],
        "admin_log": [
            {
                "time": iso(r.time),
                "actor": r.user_email,
                "event": r.event_name,
                "type": r.event_type,
                "ip": r.ip,
                "target": r.params.get("USER_EMAIL")
                or r.params.get("GROUP_EMAIL")
                or r.params.get("ORG_UNIT_NAME"),
                "setting": r.params.get("SETTING_NAME"),
                "new_value": r.params.get("NEW_VALUE"),
            }
            for r in admin_rows
        ],
    }


@router.get("/devices")
def devices(
    viewer: Viewer = Depends(require_admin), db: Session = Depends(get_db)
) -> dict[str, Any]:
    rows = db.execute(
        text(
            """SELECT d.kind, d.id, d.user_email, u.id AS user_id, u.full_name, d.model, d.os, d.os_version,
                      d.status, d.device_type, d.serial_number, d.first_sync, d.last_sync,
                      d.raw->>'deviceCompromisedStatus' AS compromised, d.raw->>'encryptionStatus' AS encryption
               FROM devices d LEFT JOIN users u ON u.tenant_id = d.tenant_id AND u.primary_email = d.user_email
               WHERE d.tenant_id = :t ORDER BY d.last_sync DESC NULLS LAST"""
        ),
        {"t": viewer.tenant_id},
    ).all()
    stale_cut = datetime.now(UTC) - timedelta(days=30)
    items = [
        {
            "kind": r.kind,
            "id": r.id,
            "user_email": r.user_email,
            "user_id": r.user_id,
            "user_name": r.full_name,
            "model": r.model,
            "os": r.os,
            "os_version": r.os_version,
            "status": r.status,
            "type": r.device_type,
            "serial": r.serial_number,
            "first_sync": iso(r.first_sync),
            "last_sync": iso(r.last_sync),
            "stale": r.last_sync is None or r.last_sync < stale_cut,
            "compromised": r.compromised not in (None, "", "No compromise detected", "Undetected"),
            "encryption": r.encryption,
        }
        for r in rows
    ]

    def count_by(key: str) -> dict[str, int]:
        out: dict[str, int] = defaultdict(int)
        for i in items:
            out[str(i[key] or "Unknown")] += 1
        return dict(sorted(out.items(), key=lambda kv: -kv[1]))

    return {
        "devices": items,
        "by_type": count_by("type"),
        "by_status": count_by("status"),
        "by_os": count_by("os"),
        "stale": sum(1 for i in items if i["stale"]),
        "compromised": sum(1 for i in items if i["compromised"]),
    }
