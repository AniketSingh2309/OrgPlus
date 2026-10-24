"""Capability lookups and the require_feature() FastAPI dependency."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

from fastapi import Depends, HTTPException
from sqlalchemy import select

from orgpulse.db import session_scope
from orgpulse.features.registry import REGISTRY
from orgpulse.models import TenantCapability, TenantPlan


def capability_status(tenant_id: uuid.UUID) -> dict[str, TenantCapability]:
    with session_scope() as s:
        rows = s.scalars(select(TenantCapability).where(TenantCapability.tenant_id == tenant_id))
        return {c.key: c for c in rows}


def is_enabled(tenant_id: uuid.UUID, key: str) -> bool:
    cap = capability_status(tenant_id).get(key)
    return cap is not None and cap.status == "on"


def capabilities_payload(tenant_id: uuid.UUID) -> dict[str, Any]:
    """Body of GET /api/capabilities."""
    from orgpulse.plan.skus import TIER_LABEL

    with session_scope() as s:
        plan = s.get(TenantPlan, tenant_id)
    caps = capability_status(tenant_id)
    features: dict[str, Any] = {}
    for key, module in REGISTRY.items():
        cap = caps.get(key)
        status = cap.status if cap else "unknown"
        if status == "on":
            reason = "available"
        elif status == "unknown":
            reason = "not checked yet"
        else:
            reason = (cap.detail if cap else None) or status
        features[key] = {
            "enabled": status == "on",
            "status": status,
            "reason": reason,
            "requires": module.requires,
            "title": module.title,
            "description": module.description,
            "how_to_enable": module.how_to_enable,
            "page": module.page,
            "paid": module.paid,
            "cards": [c.__dict__ for c in module.cards],
            "checked_at": cap.detected_at.isoformat() if cap else None,
        }
    edition = plan.edition if plan else "Unknown"
    tier = plan.tier if plan else "unknown"
    return {
        "edition": edition,
        "tier": tier,
        "badge": f"{edition} · {TIER_LABEL.get(tier, tier)}",
        "detected_at": plan.detected_at.isoformat() if plan else None,
        "licensing_error": plan.licensing_error if plan else None,
        "sku_breakdown": plan.sku_breakdown if plan else {},
        "licences_total": plan.licences_total if plan else None,
        "licences_assigned": plan.licences_assigned if plan else None,
        "features": features,
    }


def require_feature(key: str) -> Callable[..., None]:
    """Dependency: 402 with {requires} unless the tenant's capability probe says "on"."""
    from orgpulse.api.deps import Viewer, get_viewer

    def dependency(viewer: Viewer = Depends(get_viewer)) -> None:
        if is_enabled(viewer.tenant_id, key):
            return
        module = REGISTRY.get(key)
        cap = capability_status(viewer.tenant_id).get(key)
        raise HTTPException(
            status_code=402,
            detail={
                "feature": key,
                "requires": module.requires if module else "a higher Workspace edition",
                "status": cap.status if cap else "unknown",
                "reason": (cap.detail if cap else None) or "feature is locked",
            },
        )

    return dependency
