"""Request dependencies: who is viewing, what they may see, DB session.

The web app's /api proxy reads the NextAuth session and forwards a short-lived
HS256 JWT signed with NEXTAUTH_SECRET (`Authorization: Bearer ...`). We verify
it here and reject anyone outside ALLOWED_DOMAIN.

Roles:
  admin    ORG_ADMINS or Workspace super admins: everything
  manager  anyone with direct/indirect reports: their OU + their reports only
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterator
from dataclasses import dataclass

import jwt
from fastapi import Depends, Header, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from orgpulse.config import get_settings
from orgpulse.db import _session_factory, current_org, multi_org
from orgpulse.models import User
from orgpulse.tenancy import default_tenant_id

log = logging.getLogger(__name__)

JWT_AUDIENCE = "orgpulse-api"


@dataclass(frozen=True)
class Viewer:
    email: str
    name: str
    tenant_id: uuid.UUID
    role: str  # admin / manager
    # None = sees everyone; otherwise the emails this viewer may see.
    scope: frozenset[str] | None

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    def can_see(self, email: str | None) -> bool:
        return self.scope is None or (email or "").lower() in self.scope

    def scope_list(self) -> list[str] | None:
        return sorted(self.scope) if self.scope is not None else None


def get_db() -> Iterator[Session]:
    session = _session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def decode_session(token: str) -> dict[str, object]:
    """Verify the web app's short-lived session token (raises HTTPException 401/500)."""
    return _decode(token)


def _decode(token: str) -> dict[str, object]:
    secret = get_settings().nextauth_secret
    if not secret:
        raise HTTPException(500, "NEXTAUTH_SECRET is not configured on the API")
    try:
        return jwt.decode(token, secret, algorithms=["HS256"], audience=JWT_AUDIENCE)
    except jwt.PyJWTError as err:
        raise HTTPException(401, f"invalid session token: {err}") from err


def _manager_scope(db: Session, tenant_id: uuid.UUID, email: str) -> frozenset[str]:
    """The viewer's OU (unless it is the root) plus everyone below them in the reporting chain."""
    users = db.execute(
        select(User.primary_email, User.manager_email, User.org_unit_path).where(
            User.tenant_id == tenant_id
        )
    ).all()
    reports: dict[str, list[str]] = {}
    ou_of: dict[str, str | None] = {}
    for u_email, manager, ou in users:
        ou_of[u_email] = ou
        if manager:
            reports.setdefault(manager, []).append(u_email)

    seen: set[str] = set()
    stack = list(reports.get(email, []))
    while stack:
        e = stack.pop()
        if e not in seen:
            seen.add(e)
            stack.extend(reports.get(e, []))
    if not seen:
        return frozenset()

    own_ou = ou_of.get(email)
    if own_ou and own_ou != "/":
        seen |= {
            e for e, ou in ou_of.items() if ou and (ou == own_ou or ou.startswith(own_ou + "/"))
        }
    seen.add(email)
    return frozenset(seen)


def get_viewer(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> Viewer:
    settings = get_settings()
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "sign in required")
    claims = _decode(authorization.split(" ", 1)[1])
    email = str(claims.get("email", "")).lower()
    # Multi-org: the request middleware already chose the org from this email's domain;
    # the viewer must belong to exactly that org.
    org = current_org() if multi_org() else None
    domain = org.domain if org else settings.allowed_domain.lower()
    if not email or not domain or email.split("@")[-1] != domain:
        raise HTTPException(403, f"only {domain or 'the configured domain'} accounts may use Org+")

    return resolve_viewer(db, email, str(claims.get("name") or email))


def resolve_viewer(db: Session, email: str, name: str) -> Viewer:
    """What this person may see in the current organisation (raises 403 if nothing)."""
    settings = get_settings()
    tenant_id = default_tenant_id()
    if email in settings.org_admin_emails:
        return Viewer(email, name, tenant_id, "admin", None)

    me = db.scalar(select(User).where(User.tenant_id == tenant_id, User.primary_email == email))
    if me is not None and me.suspended:
        raise HTTPException(403, "this Workspace account is suspended")
    if me is not None and me.is_admin:
        return Viewer(email, name, tenant_id, "admin", None)

    synced_users = db.scalar(
        select(func.count()).select_from(User).where(User.tenant_id == tenant_id)
    )
    domain = email.split("@")[-1]
    domain_admins = [e for e in settings.org_admin_emails if e.endswith("@" + domain)]
    if not synced_users and not domain_admins:
        # Bootstrap: nothing synced yet and no ORG_ADMINS for this domain, so nobody could
        # connect the Workspace otherwise. Ends with the first directory sync.
        log.warning("bootstrap mode: treating %s as admin until the directory syncs", email)
        return Viewer(email, name, tenant_id, "admin", None)

    scope = _manager_scope(db, tenant_id, email)
    if not scope:
        raise HTTPException(403, "Org+ is available to org admins and managers")
    return Viewer(email, name, tenant_id, "manager", scope)


def require_admin(viewer: Viewer = Depends(get_viewer)) -> Viewer:
    if not viewer.is_admin:
        raise HTTPException(403, "admins only")
    return viewer
