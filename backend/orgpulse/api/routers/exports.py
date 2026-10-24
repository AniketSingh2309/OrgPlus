"""CSV export for every table in the dashboard: GET /api/export/{dataset}.csv"""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from orgpulse.alerts import compute_alerts
from orgpulse.api.deps import Viewer, get_db, get_viewer
from orgpulse.api.routers import insights, org, people

router = APIRouter(prefix="/api/export", tags=["export"])

Rows = list[dict[str, Any]]

# dataset -> (admin only?, producer)
DATASETS: dict[str, tuple[bool, Callable[[Viewer, Session], Rows]]] = {
    "people": (False, lambda v, db: people.list_people("", "", "", "score", v, db)["people"]),
    "alerts": (False, lambda v, db: compute_alerts(db, v.tenant_id, v.scope_list())),
    "teams": (
        False,
        lambda v, db: [_without(t, "members") for t in insights.teams(v, db)["teams"]],
    ),
    "meetings": (False, lambda v, db: insights.meetings(v, db)["people"]),
    "devices": (True, lambda v, db: org.devices(v, db)["devices"]),
    "apps": (True, lambda v, db: org.third_party_apps(db, v.tenant_id)),
    "signins": (True, lambda v, db: org.security("all", v, db)["signins"]),
    "admin-log": (True, lambda v, db: org.security("all", v, db)["admin_log"]),
    "external-shares": (True, lambda v, db: org.security("all", v, db)["external_shares"]),
    "2sv-gaps": (True, lambda v, db: org.security("all", v, db)["twosv"]["gaps"]),
    "licences": (True, lambda v, db: insights.licences(v, db)["inactive"]),
    "storage": (True, lambda v, db: insights.storage(v, db)["top"]),
    "groups": (
        True,
        lambda v, db: [_without(g, "member_list") for g in insights.groups(v, db)["groups"]],
    ),
    "shared-drives": (True, lambda v, db: insights.shared_drives(v, db)["drives"]),
    "admins": (True, lambda v, db: insights.admins(v, db)["admins"]),
    "onboarding": (True, lambda v, db: insights.onboarding(v, db)["joiners"]),
    "offboarding": (True, lambda v, db: insights.onboarding(v, db)["leavers"]),
}


def _without(row: dict[str, Any], key: str) -> dict[str, Any]:
    return {k: v for k, v in row.items() if k != key}


def _cell(value: Any) -> Any:
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    return value


def to_csv(rows: Rows) -> str:
    buf = io.StringIO()
    if not rows:
        return ""
    fields: list[str] = []
    for r in rows:
        fields += [k for k in r if k not in fields]
    writer = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for r in rows:
        writer.writerow({k: _cell(v) for k, v in r.items()})
    return buf.getvalue()


@router.get("")
def list_datasets(viewer: Viewer = Depends(get_viewer)) -> dict[str, list[str]]:
    return {"datasets": [k for k, (admin, _) in DATASETS.items() if viewer.is_admin or not admin]}


@router.get("/{dataset}.csv")
def export(
    dataset: str, viewer: Viewer = Depends(get_viewer), db: Session = Depends(get_db)
) -> StreamingResponse:
    if dataset not in DATASETS:
        raise HTTPException(404, "unknown dataset")
    admin_only, producer = DATASETS[dataset]
    if admin_only and not viewer.is_admin:
        raise HTTPException(403, "admins only")
    body = "﻿" + to_csv(producer(viewer, db))  # BOM so Excel reads UTF-8
    name = f"orgplus-{dataset}-{datetime.now(UTC):%Y%m%d}.csv"
    return StreamingResponse(
        iter([body]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )
