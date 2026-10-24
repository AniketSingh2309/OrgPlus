"""Email flow insights from Gmail log events (metadata only, never content)."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from orgpulse.api.deps import Viewer, get_db, get_viewer
from orgpulse.features.registry import FeatureModule, UiCard, register
from orgpulse.models import Tenant
from orgpulse.modules._common import events_sync, gated_router

router = gated_router("gmail_logs")


def _addresses(value: Any) -> list[str]:
    """Pull email addresses out of Gmail's nested message_info parameters."""
    out: list[str] = []
    if isinstance(value, dict):
        for k, v in value.items():
            if k in ("address", "rcpt_address", "from_header_address") and isinstance(v, str):
                out.append(v.lower())
            else:
                out += _addresses(v)
    elif isinstance(value, list):
        for v in value:
            out += _addresses(v)
    return out


def summarise(rows: Sequence[Any], own: str, tz_offset_hours: float = 5.5) -> dict[str, Any]:
    internal = external = bounces = 0
    domains: Counter[str] = Counter()
    by_person: dict[str, Counter[int]] = defaultdict(Counter)
    for r in rows:
        info = r.params.get("message_info") or {}
        dest = _addresses(info.get("destination") or info.get("flattened_destinations") or [])
        sender = (_addresses(info.get("source") or {}) or [r.user_email or ""])[0]
        if "bounce" in r.event_name.lower() or str(info.get("is_bounce", "")).lower() == "true":
            bounces += 1
        ext = [d for d in dest if d.split("@")[-1] != own]
        if ext:
            external += 1
            domains.update(d.split("@")[-1] for d in ext)
        elif dest:
            internal += 1
        if sender.endswith("@" + own):
            hour = int((r.time.hour + tz_offset_hours) % 24)
            by_person[sender][hour] += 1
    total = internal + external
    return {
        "messages": total,
        "internal": internal,
        "external": external,
        "bounces": bounces,
        "bounce_rate_pct": round(100 * bounces / total, 2) if total else 0,
        "top_external_domains": [{"domain": d, "messages": n} for d, n in domains.most_common(15)],
        "sent_by_hour": [
            {"user": u, "hours": [c.get(h, 0) for h in range(24)], "total": sum(c.values())}
            for u, c in sorted(by_person.items(), key=lambda kv: -sum(kv[1].values()))[:50]
        ],
    }


@router.get("")
def email_flow(
    viewer: Viewer = Depends(get_viewer), db: Session = Depends(get_db)
) -> dict[str, Any]:
    tenant = db.get(Tenant, viewer.tenant_id)
    rows = db.execute(
        text(
            """SELECT time, user_email, event_name, params FROM events
               WHERE tenant_id = :t AND app = 'gmail' AND time >= :s LIMIT 200000"""
        ),
        {"t": viewer.tenant_id, "s": datetime.now(UTC) - timedelta(days=7)},
    ).all()
    return {"window_days": 7, **summarise(rows, tenant.domain if tenant else "")}


register(
    FeatureModule(
        key="gmail_logs",
        title="Email flow insights",
        requires="Enterprise or Education Standard",
        description="Internal vs external email volume, top external domains, bounce rates and send times. Metadata only.",
        how_to_enable="https://support.google.com/a/answer/9481045",
        page="/m/gmail_logs",
        router=router,
        sync=events_sync("gmail"),
        schedule={"trigger": "interval", "hours": 3},
        cards=[
            UiCard(
                "email-flow",
                "Email flow",
                "Internal vs external volume, top external domains and bounces.",
            )
        ],
    )
)
