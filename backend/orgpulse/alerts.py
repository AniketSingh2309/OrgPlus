"""Computed "Needs attention" alerts."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from orgpulse.features.gating import is_enabled
from orgpulse.queries import scope_sql

SUSPICIOUS_LOGIN_EVENTS = (
    "suspicious_login",
    "suspicious_login_less_secure_app",
    "suspicious_programmatic_login",
    "gov_attack_warning",
)
SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}

Alert = dict[str, Any]


def _people(rows: Any) -> list[dict[str, Any]]:
    return [{"id": r.id, "email": r.email, "name": r.name} for r in rows]


def compute_alerts(
    db: Session, tenant_id: uuid.UUID, scope: list[str] | None = None
) -> list[Alert]:
    now = datetime.now(UTC)
    week_ago = now - timedelta(days=7)
    t = {"t": tenant_id}
    cond_e, p_e = scope_sql(scope, "e.user_email")
    cond_u, p_u = scope_sql(scope, "u.primary_email")
    alerts: list[Alert] = []

    # Suspicious sign-ins
    rows = db.execute(
        text(
            f"""
            SELECT DISTINCT ON (e.user_email) u.id, e.user_email AS email,
                   COALESCE(u.full_name, e.user_email) AS name, e.time, e.event_name, e.ip, e.country
            FROM events e LEFT JOIN users u ON u.tenant_id = e.tenant_id AND u.primary_email = e.user_email
            WHERE e.tenant_id = :t AND e.app = 'login' AND e.time >= :since AND {cond_e}
              AND (e.event_name = ANY(:names) OR (e.params->>'is_suspicious')::boolean IS TRUE)
            ORDER BY e.user_email, e.time DESC
            """
        ),
        {**t, **p_e, "since": week_ago, "names": list(SUSPICIOUS_LOGIN_EVENTS)},
    ).all()
    if rows:
        alerts.append(
            {
                "id": "suspicious-signin",
                "severity": "high",
                "kind": "signin",
                "title": f"{len(rows)} suspicious sign-in{'s' if len(rows) > 1 else ''} flagged by Google",
                "detail": "Last 7 days. Check whether these sign-ins were really them.",
                "users": _people(rows),
                "count": len(rows),
                "link": "/security?tab=signins&filter=suspicious",
            }
        )

    # Sign-in from a country new for that user
    rows = db.execute(
        text(
            f"""
            WITH recent AS (
              SELECT e.user_email, e.country, MIN(e.time) AS first_seen
              FROM events e
              WHERE e.tenant_id = :t AND e.app = 'login' AND e.event_name = 'login_success'
                AND e.time >= :since AND e.country IS NOT NULL AND {cond_e}
              GROUP BY e.user_email, e.country
            )
            SELECT u.id, r.user_email AS email, COALESCE(u.full_name, r.user_email) AS name, r.country
            FROM recent r
            LEFT JOIN users u ON u.tenant_id = :t AND u.primary_email = r.user_email
            WHERE EXISTS (SELECT 1 FROM events p WHERE p.tenant_id = :t AND p.app = 'login'
                          AND p.user_email = r.user_email AND p.time < :since AND p.country IS NOT NULL)
              AND NOT EXISTS (SELECT 1 FROM events p WHERE p.tenant_id = :t AND p.app = 'login'
                          AND p.user_email = r.user_email AND p.time < :since AND p.country = r.country)
            """
        ),
        {**t, **p_e, "since": week_ago},
    ).all()
    if rows:
        alerts.append(
            {
                "id": "new-country",
                "severity": "high",
                "kind": "signin",
                "title": f"{len(rows)} sign-in{'s' if len(rows) > 1 else ''} from a new country",
                "detail": ", ".join(
                    sorted({f"{r.email.split('@')[0]} ({r.country})" for r in rows})
                )[:300],
                "users": _people(rows),
                "count": len(rows),
                "link": "/security?tab=signins",
            }
        )

    # 3+ failed sign-ins in 7 days
    rows = db.execute(
        text(
            f"""
            SELECT u.id, e.user_email AS email, COALESCE(u.full_name, e.user_email) AS name, COUNT(*) AS n
            FROM events e LEFT JOIN users u ON u.tenant_id = e.tenant_id AND u.primary_email = e.user_email
            WHERE e.tenant_id = :t AND e.app = 'login' AND e.event_name = 'login_failure'
              AND e.time >= :since AND {cond_e}
            GROUP BY u.id, e.user_email, u.full_name HAVING COUNT(*) >= 3 ORDER BY n DESC
            """
        ),
        {**t, **p_e, "since": week_ago},
    ).all()
    if rows:
        alerts.append(
            {
                "id": "failed-signins",
                "severity": "medium",
                "kind": "signin",
                "title": f"{len(rows)} user{'s' if len(rows) > 1 else ''} with 3+ failed sign-ins this week",
                "detail": ", ".join(f"{r.email} ({r.n})" for r in rows[:5]),
                "users": _people(rows),
                "count": len(rows),
                "link": "/security?tab=signins&filter=failed",
            }
        )

    # No 2-Step Verification
    rows = db.execute(
        text(
            f"""
            SELECT u.id, u.primary_email AS email, COALESCE(u.full_name, u.primary_email) AS name, u.is_admin
            FROM users u WHERE u.tenant_id = :t AND NOT u.suspended AND NOT u.archived
              AND NOT u.is_enrolled_in_2sv AND {cond_u}
            ORDER BY u.is_admin DESC, u.primary_email
            """
        ),
        {**t, **p_u},
    ).all()
    if rows:
        admins = sum(1 for r in rows if r.is_admin)
        alerts.append(
            {
                "id": "no-2sv",
                "severity": "high" if admins else "medium",
                "kind": "security",
                "title": f"{len(rows)} user{'s' if len(rows) > 1 else ''} without 2-Step Verification",
                "detail": f"including {admins} admin{'s' if admins != 1 else ''}" if admins else "",
                "users": _people(rows),
                "count": len(rows),
                "link": "/security?tab=2sv",
            }
        )

    # High-risk third-party apps
    rows = db.execute(
        text(
            f"""
            SELECT a.client_id, MAX(a.display_text) AS name, COUNT(DISTINCT a.user_id) AS users
            FROM app_tokens a WHERE a.tenant_id = :t AND a.risk = 'high' AND {scope_sql(scope, "a.user_email")[0]}
            GROUP BY a.client_id ORDER BY users DESC
            """
        ),
        {**t, **p_u},
    ).all()
    if rows:
        alerts.append(
            {
                "id": "risky-apps",
                "severity": "high",
                "kind": "apps",
                "title": f"{len(rows)} high-risk third-party app{'s' if len(rows) > 1 else ''}",
                "detail": ", ".join(f"{r.name or r.client_id} ({r.users} users)" for r in rows[:5]),
                "users": [],
                "count": len(rows),
                "link": "/apps?risk=high",
            }
        )

    # Inactive 30+ days (licence to reclaim)
    rows = db.execute(
        text(
            f"""
            SELECT u.id, u.primary_email AS email, COALESCE(u.full_name, u.primary_email) AS name
            FROM users u WHERE u.tenant_id = :t AND NOT u.suspended AND NOT u.archived
              AND COALESCE(u.last_login_time, u.creation_time) < :cut AND {cond_u}
            ORDER BY u.last_login_time NULLS FIRST
            """
        ),
        {**t, **p_u, "cut": now - timedelta(days=30)},
    ).all()
    if rows:
        alerts.append(
            {
                "id": "inactive-30d",
                "severity": "medium",
                "kind": "licence",
                "title": f"{len(rows)} account{'s' if len(rows) > 1 else ''} with no sign-in for 30+ days",
                "detail": "Licences you could reclaim.",
                "users": _people(rows),
                "count": len(rows),
                "link": "/people?status=inactive",
            }
        )

    # Suspended but still licensed
    rows = db.execute(
        text(
            f"""
            SELECT DISTINCT u.id, u.primary_email AS email, COALESCE(u.full_name, u.primary_email) AS name
            FROM users u JOIN licence_assignments l ON l.tenant_id = u.tenant_id AND l.user_email = u.primary_email
            WHERE u.tenant_id = :t AND u.suspended AND {cond_u}
            """
        ),
        {**t, **p_u},
    ).all()
    if rows:
        alerts.append(
            {
                "id": "suspended-licensed",
                "severity": "medium",
                "kind": "licence",
                "title": f"{len(rows)} suspended user{'s' if len(rows) > 1 else ''} still holding a licence",
                "detail": "Remove the licence or transfer their data.",
                "users": _people(rows),
                "count": len(rows),
                "link": "/people?status=suspended",
            }
        )

    # Files shared outside the domain this week
    row = db.execute(
        text(
            f"""
            SELECT COUNT(DISTINCT e.doc_id) AS files, COUNT(DISTINCT e.user_email) AS people
            FROM events e WHERE e.tenant_id = :t AND e.app = 'drive' AND e.is_external IS TRUE
              AND e.time >= :since AND {cond_e}
            """
        ),
        {**t, **p_e, "since": week_ago},
    ).one()
    if row.files:
        alerts.append(
            {
                "id": "external-shares",
                "severity": "low",
                "kind": "sharing",
                "title": f"{row.files} file{'s' if row.files > 1 else ''} shared outside the domain this week",
                "detail": f"by {row.people} {'person' if row.people == 1 else 'people'}",
                "users": [],
                "count": int(row.files),
                "link": "/security?tab=external",
            }
        )

    # Paid: Google Alert Center alerts (admins only)
    if scope is None and is_enabled(tenant_id, "alert_center"):
        rows = db.execute(
            text(
                """
                SELECT data FROM module_data WHERE tenant_id = :t AND module = 'alert_center'
                  AND (data->>'createTime')::timestamptz >= :since
                """
            ),
            {**t, "since": now - timedelta(days=14)},
        ).all()
        by_type: dict[str, int] = {}
        for r in rows:
            by_type[r.data.get("type", "Alert")] = by_type.get(r.data.get("type", "Alert"), 0) + 1
        for kind, n in by_type.items():
            alerts.append(
                {
                    "id": f"gac-{kind}",
                    "severity": "high",
                    "kind": "google",
                    "title": f"Google alert: {kind} ({n})",
                    "detail": "From the Alert Center, last 14 days.",
                    "users": [],
                    "count": n,
                    "link": "/m/alert_center",
                }
            )

    alerts.sort(key=lambda a: (SEVERITY_ORDER[a["severity"]], -a["count"]))
    return alerts
