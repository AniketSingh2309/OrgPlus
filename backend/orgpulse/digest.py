"""Weekly digest email to the head of org: top changes, alerts, licence waste."""

from __future__ import annotations

import base64
import html
import logging
import smtplib
import uuid
from email.message import EmailMessage
from typing import Any

from orgpulse import google_client as g
from orgpulse.api.deps import Viewer
from orgpulse.config import get_settings
from orgpulse.db import session_scope
from orgpulse.models import TenantSettings

log = logging.getLogger(__name__)


def build(tenant_id: uuid.UUID) -> dict[str, Any]:
    from orgpulse.api.routers.insights import licences, onboarding
    from orgpulse.api.routers.overview import overview

    viewer = Viewer("digest@orgpulse", "Org+ digest", tenant_id, "admin", None)
    with session_scope() as db:
        ov = overview(viewer, db)
        lic = licences(viewer, db)
        onb = onboarding(viewer, db)
    return {
        "kpis": ov["kpis"],
        "alerts": ov["alerts"][:6],
        "top_people": ov["top_people"][:5],
        "licences": {k: lic[k] for k in ("purchased", "active_30d", "idle", "monthly_waste_inr")},
        "new_joiners": [j for j in onb["joiners"] if j["this_month"]],
    }


def render_html(d: dict[str, Any], app_url: str = "") -> str:
    k = d["kpis"]
    change = k.get("avg_score_change_pct")
    change_txt = f"{change:+.1f}% vs previous 30 days" if change is not None else "no previous data"
    e = html.escape
    alerts = (
        "".join(
            f"<li><b>{e(a['title'])}</b>{(' &middot; ' + e(a['detail'])) if a['detail'] else ''}</li>"
            for a in d["alerts"]
        )
        or "<li>Nothing needs attention.</li>"
    )
    top = "".join(f"<li>{e(p['name'])} ({p['score']})</li>" for p in d["top_people"])
    lic = d["licences"]
    joiners = (
        "".join(
            f"<li>{e(j['name'] or j['email'])} &middot; first week score {j['first_week_score']}</li>"
            for j in d["new_joiners"]
        )
        or "<li>None</li>"
    )
    return f"""<div style="font-family:Arial,sans-serif;color:#0f172a;max-width:640px">
<h2 style="color:#0f766e;margin-bottom:4px">Org+ weekly digest</h2>
<p style="color:#475569;margin-top:0">{k["users"]} people &middot; {k["active_30d"]} active in 30 days &middot;
2-Step coverage {k["twosv_pct"]}% &middot; average activity score {k["avg_score"]} ({change_txt})</p>
<h3>Needs attention</h3><ul>{alerts}</ul>
<h3>Licences</h3><p>{lic["active_30d"]} of {lic["purchased"]} licences active in the last 30 days.
<b>{lic["idle"]} idle</b>, about <b>&#8377;{lic["monthly_waste_inr"]:,.0f}</b> per month.</p>
<h3>New joiners this month</h3><ul>{joiners}</ul>
<h3>Most active</h3><ol>{top}</ol>
{f'<p><a href="{e(app_url)}" style="color:#0f766e">Open Org+</a></p>' if app_url else ""}
</div>"""


def send(tenant_id: uuid.UUID, recipients: list[str] | None = None) -> dict[str, Any]:
    settings = get_settings()
    with session_scope() as s:
        ts = s.get(TenantSettings, tenant_id)
        to = recipients or (ts.digest_recipients if ts else [])
    if not to:
        return {"sent": False, "reason": "no digest recipients set in Settings"}
    body = render_html(build(tenant_id))
    msg = EmailMessage()
    msg["Subject"] = "Org+ weekly digest"
    msg["To"] = ", ".join(to)
    msg["From"] = settings.smtp_from or g.current_auth().admin
    msg.set_content("Your Org+ weekly digest. Open in an HTML-capable mail client.")
    msg.add_alternative(body, subtype="html")

    if settings.digest_via_gmail:
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        svc = g.service("gmail", "v1", [g.GMAIL_SEND_SCOPE])
        g.execute(svc.users().messages().send(userId="me", body={"raw": raw}), allow_send=True)
    elif settings.smtp_host:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as smtp:
            smtp.starttls()
            if settings.smtp_user:
                smtp.login(settings.smtp_user, settings.smtp_password)
            smtp.send_message(msg)
    else:
        return {"sent": False, "reason": "configure SMTP_HOST or DIGEST_VIA_GMAIL"}
    log.info("digest sent to %s", to)
    return {"sent": True, "to": to}
