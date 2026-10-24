"""Paid modules backed by Reports API applications: DLP, context-aware access, Gemini."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from orgpulse.api.deps import Viewer, get_db, get_viewer
from orgpulse.features.registry import FeatureModule, UiCard, register
from orgpulse.modules._common import events_sync, gated_router
from orgpulse.queries import iso

# --- Data loss prevention --------------------------------------------------------------

dlp = gated_router("dlp_events")


@dlp.get("")
def dlp_summary(
    viewer: Viewer = Depends(get_viewer), db: Session = Depends(get_db)
) -> dict[str, Any]:
    p = {"t": viewer.tenant_id, "s": datetime.now(UTC) - timedelta(days=30)}
    base = "FROM events WHERE tenant_id = :t AND app = 'rules' AND time >= :s"

    def group(expr: str) -> list[dict[str, Any]]:
        return [
            {"key": r.k or "Unknown", "hits": r.n}
            for r in db.execute(
                text(
                    f"SELECT {expr} AS k, COUNT(*) AS n {base} GROUP BY 1 ORDER BY n DESC LIMIT 25"
                ),
                p,
            ).all()
        ]

    recent = db.execute(
        text(f"""SELECT time, user_email, event_name, params->>'rule_name' AS rule, params->>'resource_title' AS title,
                        params->>'actions' AS actions {base} ORDER BY time DESC LIMIT 200"""),
        p,
    ).all()
    return {
        "by_person": group("user_email"),
        "by_rule": group("params->>'rule_name'"),
        "by_file": group("COALESCE(params->>'resource_title', doc_title)"),
        "recent": [
            {
                "time": iso(r.time),
                "user": r.user_email,
                "event": r.event_name,
                "rule": r.rule,
                "title": r.title,
                "actions": r.actions,
            }
            for r in recent
        ],
    }


register(
    FeatureModule(
        key="dlp_events",
        title="Data loss prevention",
        requires="Enterprise Standard or above",
        description="DLP rule hits by person, file and rule.",
        how_to_enable="https://support.google.com/a/answer/9646351",
        page="/m/dlp_events",
        router=dlp,
        sync=events_sync("rules"),
        cards=[
            UiCard(
                "dlp-hits", "DLP rule hits", "Which rules fire most, on which files and for whom."
            )
        ],
    )
)

# --- Context-aware access --------------------------------------------------------------

caa = gated_router("context_aware_access")


@caa.get("")
def caa_summary(
    viewer: Viewer = Depends(get_viewer), db: Session = Depends(get_db)
) -> dict[str, Any]:
    p = {"t": viewer.tenant_id, "s": datetime.now(UTC) - timedelta(days=30)}
    base = "FROM events WHERE tenant_id = :t AND app = 'context_aware_access' AND time >= :s"
    rows = db.execute(
        text(
            f"""SELECT time, user_email, event_name, ip, country, params {base} ORDER BY time DESC LIMIT 300"""
        ),
        p,
    ).all()
    by_user: dict[str, int] = {}
    by_reason: dict[str, int] = {}
    by_app: dict[str, int] = {}
    for r in rows:
        by_user[r.user_email or "Unknown"] = by_user.get(r.user_email or "Unknown", 0) + 1
        reason = str(
            r.params.get("CAA_ACCESS_LEVEL_UNSATISFIED")
            or r.params.get("access_level_unsatisfied")
            or r.event_name
        )
        by_reason[reason] = by_reason.get(reason, 0) + 1
        app = str(r.params.get("CAA_APPLICATION") or r.params.get("application") or "Unknown")
        by_app[app] = by_app.get(app, 0) + 1

    def top(d: dict[str, int]) -> list[dict[str, Any]]:
        return [{"key": k, "blocks": v} for k, v in sorted(d.items(), key=lambda kv: -kv[1])[:20]]

    return {
        "total": len(rows),
        "by_user": top(by_user),
        "by_reason": top(by_reason),
        "by_app": top(by_app),
        "recent": [
            {
                "time": iso(r.time),
                "user": r.user_email,
                "event": r.event_name,
                "ip": r.ip,
                "country": r.country,
            }
            for r in rows[:100]
        ],
    }


register(
    FeatureModule(
        key="context_aware_access",
        title="Access policy blocks",
        requires="Enterprise Standard or above",
        description="Sign-ins blocked by device or location rules.",
        how_to_enable="https://support.google.com/a/answer/9275380",
        page="/m/context_aware_access",
        router=caa,
        sync=events_sync("context_aware_access"),
        cards=[
            UiCard(
                "caa-blocks",
                "Blocked access attempts",
                "Who was blocked, from which app, and which rule did it.",
            )
        ],
    )
)

# --- Gemini adoption -------------------------------------------------------------------

gemini = gated_router("gemini_usage")


@gemini.get("")
def gemini_summary(
    viewer: Viewer = Depends(get_viewer), db: Session = Depends(get_db)
) -> dict[str, Any]:
    p = {"t": viewer.tenant_id, "s": datetime.now(UTC) - timedelta(days=90)}
    base = "FROM events WHERE tenant_id = :t AND app = 'gemini_in_workspace_apps' AND time >= :s"
    people = db.execute(
        text(
            f"SELECT user_email, COUNT(*) AS n, MAX(time) AS last {base} GROUP BY 1 ORDER BY n DESC LIMIT 100"
        ),
        p,
    ).all()
    apps = db.execute(
        text(
            f"SELECT COALESCE(params->>'app_name', params->>'application', event_name) AS app, COUNT(*) AS n {base} GROUP BY 1 ORDER BY n DESC"
        ),
        p,
    ).all()
    trend = db.execute(
        text(
            f"SELECT date_trunc('week', time)::date AS wk, COUNT(DISTINCT user_email) AS users, COUNT(*) AS n {base} GROUP BY 1 ORDER BY 1"
        ),
        p,
    ).all()
    total_users = db.execute(
        text("SELECT COUNT(*) FROM users WHERE tenant_id = :t AND NOT suspended AND NOT archived"),
        {"t": viewer.tenant_id},
    ).scalar_one()
    return {
        "adopters": len(people),
        "adoption_pct": round(100 * len(people) / total_users, 1) if total_users else 0,
        "people": [{"user": r.user_email, "uses": r.n, "last": iso(r.last)} for r in people],
        "by_app": [{"app": r.app, "uses": r.n} for r in apps],
        "trend": [{"week": r.wk.isoformat(), "users": r.users, "uses": r.n} for r in trend],
    }


register(
    FeatureModule(
        key="gemini_usage",
        title="AI adoption",
        requires="Gemini for Workspace",
        description="Gemini use per person, per app, and the adoption trend.",
        how_to_enable="https://support.google.com/a/answer/13623623",
        page="/m/gemini_usage",
        router=gemini,
        sync=events_sync("gemini_in_workspace_apps"),
        cards=[
            UiCard(
                "gemini-trend",
                "Gemini adoption",
                "Weekly Gemini users and which apps they use it in.",
            )
        ],
    )
)
