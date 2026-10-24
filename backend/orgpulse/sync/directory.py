"""Daily Directory sync: users, org units, groups + members, admin roles, devices, tokens."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any

from googleapiclient.errors import HttpError
from sqlalchemy import func, select, update

from orgpulse import google_client as g
from orgpulse.db import session_scope
from orgpulse.models import AppToken, Device, Group, GroupMember, OrgUnit, User
from orgpulse.sync import mappers
from orgpulse.sync.upsert import delete_not_synced_since, upsert

log = logging.getLogger(__name__)


def _db_now() -> datetime:
    with session_scope() as s:
        now = s.scalar(select(func.now()))
        assert now is not None
        return now


def sync_users(tenant_id: uuid.UUID) -> int:
    auth = g.current_auth()
    started = _db_now()
    rows = [
        mappers.map_user(u, tenant_id)
        for u in g.paginate(
            g.directory().users().list,
            "users",
            what="users.list",
            customer=auth.customer_id,
            projection="full",
            maxResults=500,
        )
    ]
    with session_scope() as s:
        n = upsert(s, User, rows, ["id"])
        gone = delete_not_synced_since(s, User, tenant_id, started)
    log.info("users: %d synced, %d removed", n, gone)
    return n


def sync_org_units(tenant_id: uuid.UUID) -> int:
    auth = g.current_auth()
    started = _db_now()
    resp = g.execute(
        g.directory().orgunits().list(customerId=auth.customer_id, type="all"),
        what="orgunits.list",
    )
    rows = [mappers.map_org_unit(o, tenant_id) for o in resp.get("organizationUnits", [])]
    with session_scope() as s:
        n = upsert(s, OrgUnit, rows, ["id"])
        delete_not_synced_since(s, OrgUnit, tenant_id, started)
    log.info("org units: %d synced", n)
    return n


def sync_groups(tenant_id: uuid.UUID) -> int:
    auth = g.current_auth()
    started = _db_now()
    groups = [
        mappers.map_group(x, tenant_id)
        for x in g.paginate(
            g.directory().groups().list,
            "groups",
            what="groups.list",
            customer=auth.customer_id,
            maxResults=200,
        )
    ]
    members: list[dict[str, Any]] = []
    for grp in groups:
        for m in g.paginate(
            g.directory().members().list,
            "members",
            what="members.list",
            groupKey=grp["id"],
            maxResults=200,
        ):
            members.append(mappers.map_member(m, grp["id"], tenant_id))
    with session_scope() as s:
        upsert(s, Group, groups, ["id"])
        upsert(s, GroupMember, members, ["group_id", "member_id"])
        delete_not_synced_since(s, GroupMember, tenant_id, started)
        delete_not_synced_since(s, Group, tenant_id, started)
    log.info("groups: %d synced with %d memberships", len(groups), len(members))
    return len(groups)


def sync_admin_roles(tenant_id: uuid.UUID) -> int:
    auth = g.current_auth()
    roles = list(
        g.paginate(
            g.directory().roles().list, "items", what="roles.list", customer=auth.customer_id
        )
    )
    assignments = list(
        g.paginate(
            g.directory().roleAssignments().list,
            "items",
            what="roleAssignments.list",
            customer=auth.customer_id,
        )
    )
    by_user = mappers.admin_roles_by_user(assignments, roles)
    with session_scope() as s:
        s.execute(update(User).where(User.tenant_id == tenant_id).values(admin_role=None))
        for user_id, role in by_user.items():
            s.execute(
                update(User)
                .where(User.tenant_id == tenant_id, User.id == user_id)
                .values(admin_role=role)
            )
    log.info("admin roles: %d users hold a role", len(by_user))
    return len(by_user)


def sync_devices(tenant_id: uuid.UUID) -> int:
    auth = g.current_auth()
    started = _db_now()
    rows = [
        mappers.map_mobile_device(d, tenant_id)
        for d in g.paginate(
            g.directory().mobiledevices().list,
            "mobiledevices",
            what="mobiledevices.list",
            customerId=auth.customer_id,
            maxResults=100,
        )
    ]
    rows += [
        mappers.map_chromeos_device(d, tenant_id)
        for d in g.paginate(
            g.directory().chromeosdevices().list,
            "chromeosdevices",
            what="chromeosdevices.list",
            customerId=auth.customer_id,
            projection="BASIC",
            maxResults=200,
        )
    ]
    with session_scope() as s:
        n = upsert(s, Device, rows, ["kind", "id"])
        delete_not_synced_since(s, Device, tenant_id, started)
    log.info("devices: %d synced", n)
    return n


def sync_tokens(tenant_id: uuid.UUID) -> int:
    started = _db_now()
    with session_scope() as s:
        users = s.execute(
            select(User.id, User.primary_email).where(User.tenant_id == tenant_id)
        ).all()
    rows: list[dict[str, Any]] = []
    for user_id, email in users:
        try:
            resp = g.execute(g.directory().tokens().list(userKey=user_id), what="tokens.list")
        except HttpError as err:
            if err.resp.status in (404, 400):
                continue
            raise
        rows += [mappers.map_token(t, user_id, email, tenant_id) for t in resp.get("items", [])]
    with session_scope() as s:
        n = upsert(s, AppToken, rows, ["user_id", "client_id"])
        delete_not_synced_since(s, AppToken, tenant_id, started)
    log.info("app tokens: %d grants across %d users", n, len(users))
    return n


def sync_tokens_for(tenant_id: uuid.UUID, emails: set[str]) -> int:
    """Refresh third-party app grants for just these people (after an authorize/revoke)."""
    with session_scope() as s:
        users = s.execute(
            select(User.id, User.primary_email).where(
                User.tenant_id == tenant_id, User.primary_email.in_(sorted(emails))
            )
        ).all()
    n = 0
    for user_id, email in users:
        try:
            resp = g.execute(g.directory().tokens().list(userKey=user_id), what="tokens.list")
        except HttpError as err:
            if err.resp.status in (404, 400):
                continue
            raise
        rows = [mappers.map_token(t, user_id, email, tenant_id) for t in resp.get("items", [])]
        with session_scope() as s:
            # Replace this person's grants: revoked apps disappear, new ones appear.
            s.query(AppToken).filter(
                AppToken.tenant_id == tenant_id, AppToken.user_id == user_id
            ).delete()
            if rows:
                n += upsert(s, AppToken, rows, ["user_id", "client_id"])
    return n


def sync_all(tenant_id: uuid.UUID) -> dict[str, int]:
    return {
        "org_units": sync_org_units(tenant_id),
        "users": sync_users(tenant_id),
        "admin_roles": sync_admin_roles(tenant_id),
        "groups": sync_groups(tenant_id),
        "devices": sync_devices(tenant_id),
        "tokens": sync_tokens(tenant_id),
    }
