"""Daily syncs for free extras: licence assignments and shared drives."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from googleapiclient.errors import HttpError
from sqlalchemy import func, select

from orgpulse import google_client as g
from orgpulse.db import session_scope
from orgpulse.models import LicenceAssignment, SharedDrive, Tenant
from orgpulse.sync import mappers
from orgpulse.sync.upsert import delete_not_synced_since, upsert
from orgpulse.tenancy import tenant_domains

log = logging.getLogger(__name__)

# Products whose assignments we read (Workspace and Education Standard/Plus).
LICENCE_PRODUCTS = ("Google-Apps", "101031")


def fetch_licences(customer: str) -> list[dict[str, Any]]:
    """All licence assignments for our products. Raises HttpError if not permitted."""
    items: list[dict[str, Any]] = []
    for product in LICENCE_PRODUCTS:
        try:
            items += list(
                g.paginate(
                    g.licensing().licenseAssignments().listForProduct,
                    "items",
                    what=f"licenseAssignments({product})",
                    productId=product,
                    customerId=customer,
                    maxResults=1000,
                )
            )
        except HttpError as err:
            # A product the customer never bought returns 400/404; that's not an error.
            if err.resp.status in (400, 404) and product != "Google-Apps":
                continue
            raise
    return items


def licensing_customer(tenant_id: uuid.UUID) -> str:
    """The Licensing API wants the primary domain (or customer id), not 'my_customer'."""
    with session_scope() as s:
        tenant = s.get(Tenant, tenant_id)
        assert tenant is not None
        return tenant.customer_id if tenant.customer_id != "my_customer" else tenant.domain


def sync_licences(tenant_id: uuid.UUID) -> int:
    with session_scope() as s:
        started = s.scalar(select(func.now()))
    items = fetch_licences(licensing_customer(tenant_id))
    rows = [mappers.map_licence(i, tenant_id) for i in items]
    with session_scope() as s:
        n = upsert(s, LicenceAssignment, rows, ["tenant_id", "user_email", "sku_id"])
        delete_not_synced_since(s, LicenceAssignment, tenant_id, started)
    log.info("licences: %d assignments", n)
    return n


def is_external_member(perm: dict[str, Any], domains: set[str]) -> bool:
    """A Drive permission that reaches outside our domains."""
    kind = perm.get("type")
    if kind == "anyone":
        return True
    if kind == "domain":
        return str(perm.get("domain", "")).lower() not in domains
    if kind in ("user", "group"):
        return str(perm.get("emailAddress", "")).split("@")[-1].lower() not in domains
    return False


def sync_shared_drives(tenant_id: uuid.UUID) -> int:
    """Shared drives and their members (metadata only, never file content)."""
    domains = tenant_domains(tenant_id)
    with session_scope() as s:
        started = s.scalar(select(func.now()))
    rows: list[dict[str, Any]] = []
    for d in g.paginate(
        g.drive().drives().list,
        "drives",
        what="drives.list",
        useDomainAdminAccess=True,
        pageSize=100,
        fields="nextPageToken,drives(id,name,createdTime,hidden,restrictions)",
    ):
        members = list(
            g.paginate(
                g.drive().permissions().list,
                "permissions",
                what="permissions.list",
                fileId=d["id"],
                supportsAllDrives=True,
                useDomainAdminAccess=True,
                pageSize=100,
                fields="nextPageToken,permissions(id,type,role,emailAddress,domain,displayName)",
            )
        )
        external = [m for m in members if is_external_member(m, domains)]
        rows.append(
            {
                "id": d["id"],
                "tenant_id": tenant_id,
                "name": d.get("name", ""),
                "created_time": mappers.parse_time(d.get("createdTime")),
                "hidden": bool(d.get("hidden")),
                "member_count": len(members),
                "external_member_count": len(external),
                "members": {"items": members},
                "restrictions": d.get("restrictions") or {},
            }
        )
    with session_scope() as s:
        n = upsert(s, SharedDrive, rows, ["id"])
        delete_not_synced_since(s, SharedDrive, tenant_id, started)
    log.info("shared drives: %d", n)
    return n
