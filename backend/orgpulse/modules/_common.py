"""Shared helpers for feature modules."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends

from orgpulse.api.deps import require_admin
from orgpulse.db import session_scope
from orgpulse.features.gating import require_feature
from orgpulse.models import ModuleData
from orgpulse.sync.upsert import upsert


def gated_router(key: str) -> APIRouter:
    """Router at /api/m/{key}; every route needs an admin and the capability "on" (else 402)."""
    return APIRouter(
        prefix=f"/api/m/{key}",
        tags=[f"module:{key}"],
        dependencies=[Depends(require_admin), Depends(require_feature(key))],
    )


def events_sync(app: str) -> Callable[[uuid.UUID], Any]:
    """A module sync job that pulls one Reports application into the events table."""

    def sync(tenant_id: uuid.UUID) -> int:
        from orgpulse.sync.events import sync_app

        return sync_app(tenant_id, app)

    return sync


def save_snapshots(
    tenant_id: uuid.UUID,
    module: str,
    items: Iterable[tuple[str, dict[str, Any]]],
    *,
    replace: bool = True,
) -> int:
    rows = [
        {
            "tenant_id": tenant_id,
            "module": module,
            "key": k,
            "data": d,
            "synced_at": datetime.now(UTC),
        }
        for k, d in items
    ]
    with session_scope() as s:
        if replace:
            s.query(ModuleData).filter(
                ModuleData.tenant_id == tenant_id, ModuleData.module == module
            ).delete()
        return (
            upsert(s, ModuleData, rows, ["tenant_id", "module", "key"], touch_synced_at=False)
            if rows
            else 0
        )


def load_snapshot_map(tenant_id: uuid.UUID, module: str) -> dict[str, dict[str, Any]]:
    with session_scope() as s:
        return {
            m.key: m.data
            for m in s.query(ModuleData).filter(
                ModuleData.tenant_id == tenant_id, ModuleData.module == module
            )
        }


def load_snapshots(tenant_id: uuid.UUID, module: str) -> list[dict[str, Any]]:
    return list(load_snapshot_map(tenant_id, module).values())
