"""Organisations: one isolated database per organisation (multi-org mode).

Control database (`orgplus_control`): just the list of organisations, where each
one's database is, and each one's data key (encrypted with CREDENTIAL_ENC_KEY).

Per organisation: database `orgplus_org_<id>` owned by a passwordless role of the
same name. CONNECT on it is revoked from PUBLIC and granted only to that role, so
Postgres itself refuses any other organisation's role. Migrations run as the org's
own role. pg_hba additionally limits each role to its same-name database
(`sameuser`) and only from this machine (localhost).

Self sign-up: `register_org` records a new organisation as "provisioning" (no database
yet); the worker, which alone holds the provisioning role, creates its database within
seconds (`provision_pending`). The internet-facing API never creates databases.

CLI:  python -m orgpulse.orgs setup              create the control database and role
      python -m orgpulse.orgs add <domain>       provision a new organisation
      python -m orgpulse.orgs list
      python -m orgpulse.orgs migrate            upgrade every organisation's database
      python -m orgpulse.orgs sync-allowed       provision every ALLOWED_DOMAINS entry
      python -m orgpulse.orgs adopt <domain> --from-db <db>   move an existing
                                                 single-org database into its own org database
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
import time
import uuid
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from cryptography.fernet import Fernet
from sqlalchemy import DateTime, MetaData, Text, create_engine, func, select, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.engine import Connection, Engine, make_url
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from orgpulse import crypto
from orgpulse.config import get_settings, psycopg_url
from orgpulse.db import (
    OrgRef,
    control_engine,
    control_session,
    multi_org,
    org_database_url,
    use_org,
)

log = logging.getLogger(__name__)

CONTROL_DB = "orgplus_control"  # default name
_NAME = re.compile(r"^[a-z][a-z0-9_]{2,62}$")


class ControlBase(DeclarativeBase):
    metadata = MetaData()


class Org(ControlBase):
    __tablename__ = "orgs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    domain: Mapped[str] = mapped_column(Text, unique=True)
    name: Mapped[str] = mapped_column(Text)
    db_name: Mapped[str] = mapped_column(Text, unique=True)
    # This org's own Fernet key, encrypted with the master key (CREDENTIAL_ENC_KEY).
    data_key_enc: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default="active")  # provisioning / active
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    def ref(self) -> OrgRef:
        return OrgRef(self.id, self.domain, self.db_name, self.status)


def _ident(name: str) -> str:
    """Validated identifier for DDL (names are generated, but never trust interpolation)."""
    if not _NAME.match(name):
        raise ValueError(f"unsafe database/role name: {name!r}")
    return f'"{name}"'


def db_name_for(org_id: uuid.UUID) -> str:
    return f"orgplus_org_{org_id.hex[:20]}"


def _admin_engine() -> Engine:
    url = get_settings().admin_database_url
    if not url:
        raise RuntimeError("ADMIN_DATABASE_URL is required to create organisation databases")
    return create_engine(psycopg_url(url), isolation_level="AUTOCOMMIT", pool_pre_ping=True)


def _lock_database(conn: Connection, name: str) -> None:
    """Only the same-name role may connect; nobody may create temp tables. Runs as the
    database's owner: the provisioning role isn't a superuser and may only SET ROLE to the
    roles it created (Postgres 16), not use their privileges directly."""
    role = _ident(name)
    conn.execute(text(f"SET ROLE {role}"))
    try:
        conn.execute(text(f"REVOKE CONNECT, TEMPORARY ON DATABASE {role} FROM PUBLIC"))
        conn.execute(text(f"GRANT CONNECT ON DATABASE {role} TO {role}"))
    finally:
        conn.execute(text("RESET ROLE"))


# --- Control database -----------------------------------------------------------------


def control_db_name() -> str:
    """The control database (and its role): named by CONTROL_DATABASE_URL."""
    return make_url(get_settings().control_database_url).database or CONTROL_DB


def setup_control() -> None:
    """Create the control role/database (if missing), lock it down, create its table."""
    control = control_db_name()
    admin = _admin_engine()
    with admin.connect() as conn:
        if not conn.execute(
            text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": control}
        ).first():
            conn.execute(
                text(f"CREATE ROLE {_ident(control)} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE")
            )
        if not conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :d"), {"d": control}
        ).first():
            conn.execute(text(f"CREATE DATABASE {_ident(control)} OWNER {_ident(control)}"))
        _lock_database(conn, control)
    admin.dispose()
    ControlBase.metadata.create_all(control_engine())
    log.info("control database ready")


# --- Lookups (cached briefly: every request resolves its org by domain) --------------------

_cache: dict[str, tuple[float, OrgRef | None]] = {}
_CACHE_SECONDS = 30.0


def org_for_domain(domain: str) -> OrgRef | None:
    domain = domain.strip().lower()
    hit = _cache.get(domain)
    # Organisations still being set up are re-read every time, so "ready" shows at once.
    if hit and time.monotonic() - hit[0] < _CACHE_SECONDS and (hit[1] is None or hit[1].ready):
        return hit[1]
    with control_session() as s:
        org = s.scalar(
            select(Org).where(Org.domain == domain, Org.status.in_(("active", "provisioning")))
        )
        ref = org.ref() if org else None
    _cache[domain] = (time.monotonic(), ref)
    return ref


def active_orgs() -> list[OrgRef]:
    with control_session() as s:
        return [
            o.ref()
            for o in s.scalars(select(Org).where(Org.status == "active").order_by(Org.domain))
        ]


@lru_cache(maxsize=256)
def _org_fernet(org_id: uuid.UUID) -> Fernet:
    with control_session() as s:
        org = s.get(Org, org_id)
        if org is None:
            raise RuntimeError(f"unknown organisation {org_id}")
        return Fernet(crypto.decrypt(org.data_key_enc).encode())


def seal_for(org_id: uuid.UUID, plain: str) -> str:
    return _org_fernet(org_id).encrypt(plain.encode()).decode()


def unseal_for(org_id: uuid.UUID, token: str) -> str:
    return _org_fernet(org_id).decrypt(token.encode()).decode()


# --- Provisioning ------------------------------------------------------------------------


def _migrate(db_name: str) -> None:
    """Run Alembic on an org database, connected as that org's own role."""
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    cfg.set_main_option("script_location", str(Path(__file__).resolve().parents[1] / "alembic"))
    cfg.attributes["url"] = psycopg_url(org_database_url(db_name))
    command.upgrade(cfg, "head")


def _create_role_and_database(db_name: str, template: str | None = None) -> None:
    admin = _admin_engine()
    with admin.connect() as conn:
        if not conn.execute(
            text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": db_name}
        ).first():
            conn.execute(
                text(
                    f"CREATE ROLE {_ident(db_name)} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT"
                )
            )
        if not conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :d"), {"d": db_name}
        ).first():
            tmpl = f" TEMPLATE {_ident(template)}" if template else ""
            conn.execute(text(f"CREATE DATABASE {_ident(db_name)} OWNER {_ident(db_name)}{tmpl}"))
        # Only this org's role may connect (superusers aside); nobody may make temp tables.
        _lock_database(conn, db_name)
    admin.dispose()


def _seed(org: OrgRef, name: str) -> None:
    from orgpulse.tenancy import ensure_tenant

    with use_org(org):
        ensure_tenant(org.id, org.domain, name)


def register_org(domain: str, name: str | None = None) -> OrgRef:
    """Record a new organisation (status "provisioning"); its database comes from
    `provision`. Idempotent: an existing domain is returned as is. Control DB only."""
    domain = domain.strip().lower()
    existing = org_for_domain(domain)
    if existing:
        return existing
    org_id = uuid.uuid4()
    with control_session() as s:
        s.add(
            Org(
                id=org_id,
                domain=domain,
                name=name or domain,
                db_name=db_name_for(org_id),
                data_key_enc=crypto.encrypt(Fernet.generate_key().decode()),
                status="provisioning",
            )
        )
    _cache.pop(domain, None)
    log.info("organisation %s registered; waiting for its database", domain)
    return OrgRef(org_id, domain, db_name_for(org_id), "provisioning")


def provision(org: OrgRef) -> OrgRef:
    """Create the organisation's role and database, migrate and seed it, mark it active.
    Safe to re-run after a failure part-way (every step is idempotent)."""
    _create_role_and_database(org.db_name)
    _migrate(org.db_name)
    with control_session() as s:
        row = s.get(Org, org.id)
        name = row.name if row else org.domain
    ready = OrgRef(org.id, org.domain, org.db_name, "active")
    _seed(ready, name)
    with control_session() as s:
        s.execute(text("UPDATE orgs SET status = 'active' WHERE id = :i"), {"i": org.id})
    _cache.pop(org.domain, None)
    from orgpulse import realtime

    realtime.publish(org.id, "changed", what="org_ready")
    log.info("organisation %s provisioned in database %s", org.domain, org.db_name)
    return ready


def provision_pending() -> int:
    """Worker job: create databases for organisations that signed up. Returns how many."""
    with control_session() as s:
        pending = [o.ref() for o in s.scalars(select(Org).where(Org.status == "provisioning"))]
    for org in pending:
        try:
            provision(org)
        except Exception:
            log.exception("could not provision %s; will retry", org.domain)
    return len(pending)


def add_org(domain: str, name: str | None = None) -> OrgRef:
    """Register and provision an organisation right away (CLI)."""
    org = register_org(domain, name)
    return org if org.ready else provision(org)


def migrate_all() -> None:
    for org in active_orgs():
        _migrate(org.db_name)
        log.info("migrated %s (%s)", org.domain, org.db_name)


def sync_allowed() -> list[OrgRef]:
    return [add_org(d) for d in get_settings().domains]


def adopt(domain: str, from_db: str) -> OrgRef:
    """Move an existing single-org database into its own isolated org database.

    Copies `from_db` (which must have no open connections) as a template, hands every
    object to the new org role, re-encrypts the stored credential with the org's own
    key and removes personal fields Org+ doesn't need. Needs a superuser admin URL.
    The source database is left untouched as a backup.
    """
    domain = domain.strip().lower()
    if org_for_domain(domain):
        raise RuntimeError(f"{domain} already has an organisation database")
    src_url = make_url(psycopg_url(get_settings().admin_database_url)).set(database=from_db)
    src = create_engine(src_url)
    with src.connect() as conn:
        tenant_id = conn.execute(
            text("SELECT id FROM tenants WHERE domain = :d"), {"d": domain}
        ).scalar()
    src.dispose()
    if tenant_id is None:
        raise RuntimeError(f"{from_db} has no tenant for {domain}")
    org_id = uuid.UUID(str(tenant_id))  # keep the same id so every row's tenant_id stays valid
    db_name = db_name_for(org_id)
    _create_role_and_database(db_name, template=from_db)

    # Hand every object in the copy to the org's role (needs a superuser).
    copy = create_engine(
        make_url(psycopg_url(get_settings().admin_database_url)).set(database=db_name),
        isolation_level="AUTOCOMMIT",
    )
    with copy.connect() as conn:
        role = _ident(db_name)
        conn.execute(text(f"ALTER SCHEMA public OWNER TO {role}"))
        for kind, sql in (
            ("TABLE", "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"),
            ("SEQUENCE", "SELECT sequencename FROM pg_sequences WHERE schemaname = 'public'"),
        ):
            for (obj,) in conn.execute(text(sql)).all():
                conn.execute(text(f'ALTER {kind} public."{obj}" OWNER TO {role}'))
        # Other organisations in the copy (if any) don't belong here.
        conn.execute(text("DELETE FROM tenants WHERE id <> :t"), {"t": org_id})
    copy.dispose()

    data_key = Fernet.generate_key().decode()
    with control_session() as s:
        s.add(
            Org(
                id=org_id,
                domain=domain,
                name=domain,
                db_name=db_name,
                data_key_enc=crypto.encrypt(data_key),
            )
        )
    _cache.pop(domain, None)
    ref = OrgRef(org_id, domain, db_name)
    _migrate(db_name)
    with use_org(ref):
        _reseal_credentials(ref)
        _minimise_personal_data()
    log.info("adopted %s from %s into %s", domain, from_db, db_name)
    return ref


def _reseal_credentials(org: OrgRef) -> None:
    """Credential sealed with the master key -> sealed with this org's own key."""
    from orgpulse.db import session_scope
    from orgpulse.models import TenantCredential
    from orgpulse.tenancy import seal

    with session_scope() as s:
        for cred in s.query(TenantCredential).all():
            cred.sa_json_enc = seal(crypto.decrypt(cred.sa_json_enc))
            if not cred.admin_email.startswith("enc:"):
                cred.admin_email = seal(cred.admin_email)


def _minimise_personal_data() -> None:
    from orgpulse.db import session_scope
    from orgpulse.sync.mappers import SENSITIVE_DEVICE_FIELDS, SENSITIVE_USER_FIELDS

    with session_scope() as s:
        s.execute(
            text("UPDATE users SET raw = raw - CAST(:k AS text[])"),
            {"k": sorted(SENSITIVE_USER_FIELDS)},
        )
        s.execute(
            text("UPDATE devices SET raw = raw - CAST(:k AS text[])"),
            {"k": sorted(SENSITIVE_DEVICE_FIELDS)},
        )


def main(argv: list[str] | None = None) -> int:
    from orgpulse.logging_setup import setup_logging

    setup_logging()
    parser = argparse.ArgumentParser(prog="python -m orgpulse.orgs")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("setup")
    sub.add_parser("list")
    sub.add_parser("migrate")
    sub.add_parser("sync-allowed")
    p_add = sub.add_parser("add")
    p_add.add_argument("domain")
    p_add.add_argument("--name")
    p_adopt = sub.add_parser("adopt")
    p_adopt.add_argument("domain")
    p_adopt.add_argument("--from-db", required=True)
    args = parser.parse_args(argv)
    if not multi_org():
        print(
            "CONTROL_DATABASE_URL is not set: Org+ is in single-organisation mode.", file=sys.stderr
        )
        return 2
    if args.cmd == "setup":
        setup_control()
    elif args.cmd == "list":
        for o in active_orgs():
            print(f"{o.domain:30} {o.db_name}  {o.id}")
    elif args.cmd == "migrate":
        migrate_all()
    elif args.cmd == "sync-allowed":
        for o in sync_allowed():
            print(f"{o.domain:30} {o.db_name}")
    elif args.cmd == "add":
        o = add_org(args.domain, args.name)
        print(f"{o.domain} -> {o.db_name}")
    elif args.cmd == "adopt":
        o = adopt(args.domain, args.from_db)
        print(f"{o.domain} -> {o.db_name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
