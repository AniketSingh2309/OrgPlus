"""Me, weights, sync, settings, capabilities and the /connect flow."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from orgpulse import crypto
from orgpulse import google_client as g
from orgpulse.api.deps import Viewer, get_db, get_viewer, require_admin
from orgpulse.features.gating import capabilities_payload
from orgpulse.models import (
    CapabilityChange,
    ScoreWeight,
    SyncState,
    Tenant,
    TenantCredential,
    TenantSettings,
)
from orgpulse.plan.connection import check_scopes
from orgpulse.queries import iso, last_synced, weights
from orgpulse.realtime import publish
from orgpulse.sync import runner
from orgpulse.tenancy import DEFAULT_WEIGHTS, google_auth_for, has_credentials, seal, unseal

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["admin"])


@router.get("/me")
def me(viewer: Viewer = Depends(get_viewer), db: Session = Depends(get_db)) -> dict[str, Any]:
    tenant = db.get(Tenant, viewer.tenant_id)
    settings = db.get(TenantSettings, viewer.tenant_id)
    caps = capabilities_payload(viewer.tenant_id)
    return {
        "email": viewer.email,
        "name": viewer.name,
        "role": viewer.role,
        "scope_size": len(viewer.scope) if viewer.scope is not None else None,
        "domain": tenant.domain if tenant else None,
        "connected": has_credentials(viewer.tenant_id),
        "plan_badge": caps["badge"],
        "hide_locked": bool(settings and settings.hide_locked),
        "sync": last_synced(db, viewer.tenant_id),
    }


# --- Weights ---------------------------------------------------------------------------


class WeightsBody(BaseModel):
    weights: dict[str, float]

    @field_validator("weights")
    @classmethod
    def known_metrics(cls, v: dict[str, float]) -> dict[str, float]:
        unknown = set(v) - set(DEFAULT_WEIGHTS)
        if unknown:
            raise ValueError(f"unknown metrics: {sorted(unknown)}")
        if any(w < 0 or w > 100 for w in v.values()):
            raise ValueError("weights must be between 0 and 100")
        return v


@router.get("/weights")
def get_weights(
    viewer: Viewer = Depends(get_viewer), db: Session = Depends(get_db)
) -> dict[str, Any]:
    return {"weights": weights(db, viewer.tenant_id), "defaults": DEFAULT_WEIGHTS}


@router.put("/weights")
def put_weights(
    body: WeightsBody, viewer: Viewer = Depends(require_admin), db: Session = Depends(get_db)
) -> dict[str, Any]:
    for metric, w in body.weights.items():
        stmt = insert(ScoreWeight).values(
            tenant_id=viewer.tenant_id, metric=metric, weight=w, updated_by=viewer.email
        )
        db.execute(
            stmt.on_conflict_do_update(
                index_elements=["tenant_id", "metric"],
                set_={"weight": w, "updated_by": viewer.email, "updated_at": datetime.now(UTC)},
            )
        )
    log.info("%s updated score weights: %s", viewer.email, body.weights)
    db.commit()
    publish(viewer.tenant_id, "changed", what="weights")
    return {"weights": weights(db, viewer.tenant_id)}


# --- Sync ------------------------------------------------------------------------------


class SyncBody(BaseModel):
    job: Literal[
        "all",
        "directory",
        "usage",
        "events_fast",
        "events_slow",
        "licences",
        "shared_drives",
        "plan",
        "modules",
    ] = "all"


@router.post("/sync/run", status_code=202)
def sync_run(body: SyncBody, viewer: Viewer = Depends(require_admin)) -> dict[str, str]:
    if not has_credentials(viewer.tenant_id):
        raise HTTPException(409, "connect Google Workspace first (/connect)")
    runner.run_in_background(body.job, viewer.tenant_id)
    return {"status": "started", "job": body.job}


@router.get("/sync/status")
def sync_status(
    viewer: Viewer = Depends(get_viewer), db: Session = Depends(get_db)
) -> dict[str, Any]:
    rows = db.scalars(
        select(SyncState).where(SyncState.tenant_id == viewer.tenant_id).order_by(SyncState.key)
    ).all()
    derived = next(
        (set((r.detail or {}).get("metrics", [])) for r in rows if r.key == "derived_metrics"),
        set(),
    )

    def still_missing(detail: dict[str, Any] | None) -> dict[str, Any] | None:
        """Usage metrics with no source at all (ones derived from events don't count)."""
        missing = (detail or {}).get("missing_metrics")
        if not missing or not viewer.is_admin:
            return None
        return {m: v for m, v in missing.items() if m not in derived} or None

    return {
        **last_synced(db, viewer.tenant_id),
        "derived_metrics": sorted(derived),
        "jobs": [
            {
                "key": r.key,
                "status": r.status,
                "cursor": iso(r.cursor_time),
                "last_run": iso(r.last_run_at),
                "last_success": iso(r.last_success_at),
                "error": r.error if viewer.is_admin else None,
                "progress": (r.detail or {}).get("progress"),
                "missing_metrics": still_missing(r.detail),
            }
            for r in rows
        ],
    }


# --- Settings --------------------------------------------------------------------------


class SettingsBody(BaseModel):
    licence_price_inr: float = Field(ge=0)
    licences_purchased: int | None = Field(default=None, ge=0)
    work_start: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    work_end: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    timezone: str
    hide_locked: bool
    digest_recipients: list[str] = []

    @field_validator("timezone")
    @classmethod
    def valid_tz(cls, v: str) -> str:
        from zoneinfo import ZoneInfo

        ZoneInfo(v)
        return v


def _settings_dict(s: TenantSettings) -> dict[str, Any]:
    return {
        "licence_price_inr": s.licence_price_inr,
        "licences_purchased": s.licences_purchased,
        "work_start": s.work_start,
        "work_end": s.work_end,
        "timezone": s.timezone,
        "hide_locked": s.hide_locked,
        "digest_recipients": s.digest_recipients,
    }


@router.get("/settings")
def get_settings_(
    viewer: Viewer = Depends(get_viewer), db: Session = Depends(get_db)
) -> dict[str, Any]:
    s = db.get(TenantSettings, viewer.tenant_id)
    if s is None:
        s = TenantSettings(tenant_id=viewer.tenant_id)
        db.add(s)
        db.flush()
        db.refresh(s)
    return _settings_dict(s)


@router.put("/settings")
def put_settings(
    body: SettingsBody, viewer: Viewer = Depends(require_admin), db: Session = Depends(get_db)
) -> dict[str, Any]:
    values = {**body.model_dump(), "updated_at": datetime.now(UTC)}
    stmt = insert(TenantSettings).values(tenant_id=viewer.tenant_id, **values)
    db.execute(stmt.on_conflict_do_update(index_elements=["tenant_id"], set_=values))
    db.flush()
    s = db.get(TenantSettings, viewer.tenant_id)
    assert s is not None
    db.refresh(s)
    db.commit()
    publish(viewer.tenant_id, "changed", what="settings")
    return _settings_dict(s)


# --- Capabilities ----------------------------------------------------------------------


@router.get("/capabilities")
def capabilities(
    viewer: Viewer = Depends(get_viewer), db: Session = Depends(get_db)
) -> dict[str, Any]:
    payload = capabilities_payload(viewer.tenant_id)
    changes = db.scalars(
        select(CapabilityChange)
        .where(
            CapabilityChange.tenant_id == viewer.tenant_id, CapabilityChange.acknowledged.is_(False)
        )
        .order_by(CapabilityChange.at.desc())
    ).all()
    payload["changes"] = [
        {"id": c.id, "key": c.key, "old": c.old_status, "new": c.new_status, "at": iso(c.at)}
        for c in changes
    ]
    return payload


@router.post("/capabilities/recheck")
def recheck(viewer: Viewer = Depends(require_admin)) -> dict[str, Any]:
    if not has_credentials(viewer.tenant_id):
        raise HTTPException(409, "connect Google Workspace first (/connect)")
    runner.run("plan", viewer.tenant_id)
    return capabilities_payload(viewer.tenant_id)


@router.post("/capabilities/changes/ack")
def ack_changes(
    viewer: Viewer = Depends(require_admin), db: Session = Depends(get_db)
) -> dict[str, str]:
    db.execute(
        text("UPDATE capability_changes SET acknowledged = TRUE WHERE tenant_id = :t"),
        {"t": viewer.tenant_id},
    )
    db.commit()
    publish(viewer.tenant_id, "changed", what="capabilities")
    return {"status": "ok"}


# --- Connect ---------------------------------------------------------------------------


def _connection(db: Session, viewer: Viewer) -> dict[str, Any]:
    cred = db.get(TenantCredential, viewer.tenant_id)
    if cred is None:
        try:
            auth = g.env_auth()
            return {
                "connected": True,
                "source": "env",
                "client_email": auth.client_email,
                "client_id": auth.client_id,
                "admin_email": auth.admin,
                "scope_check": None,
                "bigquery_project": None,
                "bigquery_dataset": None,
                "updated_at": None,
            }
        except Exception:
            return {"connected": False, "source": None}
    return {
        "connected": True,
        "source": "uploaded",
        "client_email": cred.client_email,
        "client_id": cred.client_id,
        "admin_email": unseal(cred.admin_email),
        "bigquery_project": cred.bigquery_project,
        "bigquery_dataset": cred.bigquery_dataset,
        "scope_check": cred.scope_check or None,
        "updated_at": iso(cred.updated_at),
    }


def _clear_demo_data(db: Session, viewer: Viewer) -> None:
    """Demo rows (python -m orgpulse.demo) must not mix with a real domain's data."""
    is_demo = db.execute(
        text("SELECT 1 FROM sync_state WHERE tenant_id = :t AND detail->>'demo' = 'true' LIMIT 1"),
        {"t": viewer.tenant_id},
    ).first()
    if not is_demo:
        return
    from orgpulse.demo import DEMO_TABLES

    for table in DEMO_TABLES:
        db.execute(text(f"DELETE FROM {table} WHERE tenant_id = :t"), {"t": viewer.tenant_id})
    log.info("%s connected a real Workspace: demo data removed", viewer.email)


@router.get("/connect")
def connect_status(
    viewer: Viewer = Depends(require_admin), db: Session = Depends(get_db)
) -> dict[str, Any]:
    return _connection(db, viewer)


@router.post("/connect")
async def connect(
    file: UploadFile = File(...),
    admin_email: str = Form(...),
    bigquery_project: str = Form(""),
    bigquery_dataset: str = Form(""),
    viewer: Viewer = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    raw = (await file.read()).decode("utf-8", errors="replace")
    try:
        info = json.loads(raw)
    except ValueError as err:
        raise HTTPException(400, "that file is not JSON") from err
    if info.get("type") != "service_account" or "private_key" not in info:
        raise HTTPException(400, "that JSON is not a service account key")
    admin_email = admin_email.strip().lower()
    tenant = db.get(Tenant, viewer.tenant_id)
    if tenant and admin_email.split("@")[-1] != tenant.domain:
        raise HTTPException(400, f"the admin email must be in {tenant.domain}")
    try:
        encrypted = seal(raw)  # the org's own key in multi-org mode
    except crypto.CredentialKeyError as err:
        raise HTTPException(500, str(err)) from err

    auth = g.GoogleAuth(raw, admin_email, tenant.customer_id if tenant else "my_customer")
    check = check_scopes(auth)
    values = {
        "sa_json_enc": encrypted,
        "admin_email": seal(admin_email),
        "client_email": info.get("client_email"),
        "client_id": str(info.get("client_id")),
        "bigquery_project": bigquery_project.strip() or None,
        "bigquery_dataset": bigquery_dataset.strip() or None,
        "scope_check": check,
        "updated_at": datetime.now(UTC),
    }
    stmt = insert(TenantCredential).values(tenant_id=viewer.tenant_id, **values)
    db.execute(stmt.on_conflict_do_update(index_elements=["tenant_id"], set_=values))
    _clear_demo_data(db, viewer)
    log.info(
        "%s connected Workspace credential %s (core scopes ok: %s)",
        viewer.email,
        info.get("client_email"),
        check["core_ok"],
    )
    db.flush()
    db.commit()
    publish(viewer.tenant_id, "changed", what="connection")
    return _connection(db, viewer)


@router.post("/connect/check")
def connect_check(
    viewer: Viewer = Depends(require_admin), db: Session = Depends(get_db)
) -> dict[str, Any]:
    check = check_scopes(google_auth_for(viewer.tenant_id))
    cred = db.get(TenantCredential, viewer.tenant_id)
    if cred is not None:
        cred.scope_check = check
    return check


@router.post("/connect/detect")
def connect_detect(viewer: Viewer = Depends(require_admin)) -> dict[str, Any]:
    runner.run("plan", viewer.tenant_id)
    return capabilities_payload(viewer.tenant_id)


@router.post("/connect/backfill", status_code=202)
def connect_backfill(
    viewer: Viewer = Depends(require_admin), db: Session = Depends(get_db)
) -> dict[str, str]:
    cred = db.get(TenantCredential, viewer.tenant_id)
    if cred is not None and not (cred.scope_check or {}).get("core_ok"):
        raise HTTPException(
            409, "the core scopes aren't granted yet; fix domain-wide delegation and re-check first"
        )
    runner.run_in_background("all", viewer.tenant_id)
    return {"status": "started"}


# --- Weekly digest ---------------------------------------------------------------------


@router.get("/digest/preview", response_class=HTMLResponse)
def digest_preview(viewer: Viewer = Depends(require_admin)) -> str:
    from orgpulse import digest

    return digest.render_html(digest.build(viewer.tenant_id))


@router.post("/digest/send")
def digest_send(viewer: Viewer = Depends(require_admin)) -> dict[str, Any]:
    from orgpulse import digest

    token = (
        g.use_auth(google_auth_for(viewer.tenant_id)) if has_credentials(viewer.tenant_id) else None
    )
    try:
        return digest.send(viewer.tenant_id)
    finally:
        if token is not None:
            g.reset_auth(token)
