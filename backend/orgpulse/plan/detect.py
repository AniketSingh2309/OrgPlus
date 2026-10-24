"""Plan detection: edition from the License Manager API, then capability probes.

Re-run daily and on "Re-check plan". Capability flips are logged to
capability_changes so the dashboard can show a banner.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from orgpulse.db import session_scope
from orgpulse.models import (
    CapabilityChange,
    Tenant,
    TenantCapability,
    TenantCredential,
    TenantPlan,
    TenantSettings,
)
from orgpulse.plan import skus
from orgpulse.plan.probes import PROBES, ProbeContext, ProbeResult, classify_error
from orgpulse.sync.extras import fetch_licences, licensing_customer

log = logging.getLogger(__name__)


def detect_plan(tenant_id: uuid.UUID) -> dict[str, Any]:
    """Layer 1. Falls back to edition "Unknown" if the licensing call fails."""
    error: str | None = None
    try:
        result = skus.detect_edition(fetch_licences(licensing_customer(tenant_id)))
    except Exception as err:
        probe = classify_error(err, "https://www.googleapis.com/auth/apps.licensing")
        error = probe.detail
        log.warning("licensing call failed (%s); edition unknown", error)
        result = skus.PlanResult("Unknown", "unknown", {}, 0)

    with session_scope() as s:
        purchased = s.scalar(
            select(TenantSettings.licences_purchased).where(TenantSettings.tenant_id == tenant_id)
        )
        detected_at = datetime.now(UTC)
        values: dict[str, Any] = {
            "edition": result.edition,
            "tier": result.tier,
            "sku_breakdown": result.breakdown,
            "licences_total": purchased or (result.licences_assigned or None),
            "licences_assigned": result.licences_assigned if error is None else None,
            "licensing_error": error,
            "detected_at": detected_at,
        }
        stmt = insert(TenantPlan).values(tenant_id=tenant_id, **values)
        s.execute(stmt.on_conflict_do_update(index_elements=["tenant_id"], set_=values))
    return {**values, "detected_at": detected_at.isoformat()}


def probe_capabilities(tenant_id: uuid.UUID) -> dict[str, ProbeResult]:
    """Layer 2 (source of truth). Records flips as CapabilityChange rows."""
    with session_scope() as s:
        tenant = s.get(Tenant, tenant_id)
        cred = s.get(TenantCredential, tenant_id)
        plan = s.get(TenantPlan, tenant_id)
        ctx = ProbeContext(
            customer_id=tenant.customer_id if tenant else "my_customer",
            bigquery_project=cred.bigquery_project if cred else None,
            bigquery_dataset=cred.bigquery_dataset if cred else None,
            edition=plan.edition if plan else None,
            tier=plan.tier if plan and plan.tier != "unknown" else None,
        )
        before = {
            c.key: c.status
            for c in s.scalars(
                select(TenantCapability).where(TenantCapability.tenant_id == tenant_id)
            )
        }

    results: dict[str, ProbeResult] = {}
    for key, probe in PROBES.items():
        results[key] = probe(ctx)
        log.info("capability %-22s %s %s", key, results[key].status, results[key].detail)

    now = datetime.now(UTC)
    with session_scope() as s:
        for key, r in results.items():
            stmt = insert(TenantCapability).values(
                tenant_id=tenant_id, key=key, status=r.status, detail=r.detail, detected_at=now
            )
            s.execute(
                stmt.on_conflict_do_update(
                    index_elements=["tenant_id", "key"],
                    set_={"status": r.status, "detail": r.detail, "detected_at": now},
                )
            )
            old = before.get(key)
            # Only a real Google-side flip (on <-> locked) means the plan changed. "error" is
            # transient, and "not_configured" changes come from Org+ settings or setup.
            if old is not None and old != r.status and {old, r.status} == {"on", "locked"}:
                log.warning("capability %s changed: %s -> %s", key, old, r.status)
                s.add(
                    CapabilityChange(
                        tenant_id=tenant_id, key=key, old_status=old, new_status=r.status
                    )
                )
    return results


def run_detection(tenant_id: uuid.UUID) -> dict[str, Any]:
    plan = detect_plan(tenant_id)
    caps = probe_capabilities(tenant_id)
    return {
        "plan": plan,
        "capabilities": {k: {"status": v.status, "detail": v.detail} for k, v in caps.items()},
    }
