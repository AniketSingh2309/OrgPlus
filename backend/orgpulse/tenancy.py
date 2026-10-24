"""Tenant bootstrap, per-tenant lookups and sealing of an org's secrets.

Single-org mode: one tenant for ALLOWED_DOMAIN in DATABASE_URL.
Multi-org mode: the tenant is the organisation selected for this request/job
(orgpulse.db.use_org); its row lives in that organisation's own database.
"""

from __future__ import annotations

import logging
import uuid
from functools import lru_cache

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from orgpulse import crypto
from orgpulse.config import get_settings
from orgpulse.db import NoOrgSelected, current_org, multi_org, session_scope
from orgpulse.google_client import GoogleAuth, env_auth
from orgpulse.models import ScoreWeight, Tenant, TenantCredential, TenantSettings

log = logging.getLogger(__name__)

# Activity score weights per metric (editable on the overview page).
# mh = meeting hours (derived from meet:total_call_minutes / 60).
DEFAULT_WEIGHTS: dict[str, float] = {
    "dc": 3, "de": 1, "dv": 0, "es": 0.5, "er": 0, "mt": 1, "mh": 2, "ch": 0.1, "cal": 1,
}  # fmt: skip


def ensure_tenant(tenant_id: uuid.UUID | None, domain: str, name: str | None = None) -> uuid.UUID:
    """Create the tenant row (with this id, if given) and seed weights/settings. Idempotent."""
    settings = get_settings()
    with session_scope() as s:
        tenant = s.scalar(select(Tenant).where(Tenant.domain == domain))
        if tenant is None:
            tenant = Tenant(
                name=name or domain, domain=domain, customer_id=settings.google_customer_id
            )
            if tenant_id is not None:
                tenant.id = tenant_id
            s.add(tenant)
            s.flush()
            log.info("created tenant %s (%s)", domain, tenant.id)
        s.execute(
            insert(ScoreWeight)
            .values(
                [
                    {"tenant_id": tenant.id, "metric": m, "weight": w}
                    for m, w in DEFAULT_WEIGHTS.items()
                ]
            )
            .on_conflict_do_nothing()
        )
        s.execute(insert(TenantSettings).values(tenant_id=tenant.id).on_conflict_do_nothing())
        return tenant.id


def ensure_default_tenant() -> uuid.UUID | None:
    """Single-org mode: the tenant for ALLOWED_DOMAIN. (Multi-org: created at provisioning.)"""
    if multi_org():
        org = current_org()
        return org.id if org else None
    domain = get_settings().allowed_domain.strip().lower()
    if not domain:
        log.warning("ALLOWED_DOMAIN is not set; skipping tenant bootstrap")
        return None
    return ensure_tenant(None, domain)


@lru_cache(maxsize=1)
def _single_tenant_id() -> uuid.UUID:
    tid = ensure_default_tenant()
    if tid is None:
        raise RuntimeError("ALLOWED_DOMAIN must be set")
    return tid


def default_tenant_id() -> uuid.UUID:
    """The tenant this request/job works on: the selected organisation in multi-org mode."""
    if multi_org():
        org = current_org()
        if org is None:
            raise NoOrgSelected("no organisation selected for this request or job")
        return org.id
    return _single_tenant_id()


default_tenant_id.cache_clear = _single_tenant_id.cache_clear  # type: ignore[attr-defined]


def seal(plain: str) -> str:
    """Encrypt an org secret: with the org's own key (multi-org) or the master key."""
    org = current_org() if multi_org() else None
    if org is not None:
        from orgpulse.orgs import seal_for

        return "enc:" + seal_for(org.id, plain)
    return "enc:" + crypto.encrypt(plain)


def unseal(value: str) -> str:
    """Decrypt a sealed secret. Values without the "enc:" marker are legacy master-key
    ciphertext (service-account keys) or plaintext (old admin emails)."""
    org = current_org() if multi_org() else None
    if value.startswith("enc:"):
        token = value[4:]
        if org is not None:
            from orgpulse.orgs import unseal_for

            return unseal_for(org.id, token)
        return crypto.decrypt(token)
    return value


def tenant_domains(tenant_id: uuid.UUID) -> set[str]:
    """Domains treated as internal (primary domain; aliases can be added later)."""
    with session_scope() as s:
        domain = s.scalar(select(Tenant.domain).where(Tenant.id == tenant_id))
    return {domain} if domain else set()


def google_auth_for(tenant_id: uuid.UUID) -> GoogleAuth:
    """The tenant's stored (encrypted) credential, else the env-configured key file."""
    with session_scope() as s:
        cred = s.get(TenantCredential, tenant_id)
        customer = s.scalar(select(Tenant.customer_id).where(Tenant.id == tenant_id))
        if cred is not None:
            sa_json = (
                unseal(cred.sa_json_enc)
                if cred.sa_json_enc.startswith("enc:")
                else crypto.decrypt(cred.sa_json_enc)
            )
            return GoogleAuth(sa_json, unseal(cred.admin_email), customer or "my_customer")
    return env_auth()


def has_credentials(tenant_id: uuid.UUID) -> bool:
    with session_scope() as s:
        if s.get(TenantCredential, tenant_id) is not None:
            return True
    s_ = get_settings()
    return bool(s_.google_admin_impersonate) and s_.google_service_account_json.is_file()
