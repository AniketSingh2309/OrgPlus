"""Engines and sessions, routed to the right organisation's database.

Two modes:
  single-org  DATABASE_URL only: one database (development, tests).
  multi-org   CONTROL_DATABASE_URL set: a small control database lists the
              organisations; each organisation's data lives in its own database,
              opened by its own passwordless role of the same name. Every request
              and job runs inside `use_org(org)`, and `get_engine()` then returns
              that organisation's engine, so code can't reach another org's data.
"""

from __future__ import annotations

import contextvars
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from orgpulse.config import get_settings, psycopg_url


class NoOrgSelected(RuntimeError):
    """Multi-org mode, but no organisation was chosen for this request/job."""


@dataclass(frozen=True)
class OrgRef:
    id: uuid.UUID
    domain: str
    db_name: str  # also the name of its only role
    # "provisioning": signed up, its database is being created by the worker; "active".
    status: str = "active"

    @property
    def ready(self) -> bool:
        return self.status == "active"


_current_org: contextvars.ContextVar[OrgRef | None] = contextvars.ContextVar("org", default=None)


def multi_org() -> bool:
    return bool(get_settings().control_database_url)


def current_org() -> OrgRef | None:
    return _current_org.get()


@contextmanager
def use_org(org: OrgRef) -> Iterator[OrgRef]:
    """Run the enclosed code against this organisation's database only."""
    token = _current_org.set(org)
    try:
        yield org
    finally:
        _current_org.reset(token)


def org_database_url(db_name: str) -> str:
    """Connection URL for an org database: role and database share the name, no password."""
    return get_settings().org_database_url_template.format(role=db_name, db=db_name)


@lru_cache(maxsize=1)
def _single_engine() -> Engine:
    return create_engine(get_settings().sqlalchemy_url, pool_pre_ping=True)


@lru_cache(maxsize=256)
def _org_engine(db_name: str) -> Engine:
    return create_engine(
        psycopg_url(org_database_url(db_name)), pool_pre_ping=True, pool_size=3, max_overflow=5
    )


@lru_cache(maxsize=1)
def control_engine() -> Engine:
    return create_engine(psycopg_url(get_settings().control_database_url), pool_pre_ping=True)


def get_engine() -> Engine:
    if not multi_org():
        return _single_engine()
    org = current_org()
    if org is None:
        raise NoOrgSelected("no organisation selected for this request or job")
    return _org_engine(org.db_name)


def _clear_engines() -> None:
    for cached in (_single_engine, _org_engine, control_engine, _factories):
        cached.cache_clear()


get_engine.cache_clear = _clear_engines  # type: ignore[attr-defined]


@lru_cache(maxsize=256)
def _factories(engine_id: int, engine: Any) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


def _session_factory() -> sessionmaker[Session]:
    engine = get_engine()
    return _factories(id(engine), engine)


_session_factory.cache_clear = _clear_engines  # type: ignore[attr-defined]


@contextmanager
def session_scope() -> Iterator[Session]:
    """A session on the current org's database that commits on success."""
    session = _session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@contextmanager
def control_session() -> Iterator[Session]:
    session = sessionmaker(bind=control_engine(), expire_on_commit=False)()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def ping() -> None:
    engine = control_engine() if multi_org() else get_engine()
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
