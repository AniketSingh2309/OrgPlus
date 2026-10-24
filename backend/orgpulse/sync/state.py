"""sync_state bookkeeping and per-job locking."""

from __future__ import annotations

import hashlib
import logging
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert

from orgpulse.db import get_engine, session_scope
from orgpulse.models import SyncState
from orgpulse.realtime import publish

log = logging.getLogger(__name__)


class JobAlreadyRunning(RuntimeError):
    pass


class JobSkipped(Exception):
    """Raised inside a job to record "skipped" (e.g. an optional scope isn't granted)."""


def friendly_error(err: BaseException) -> str:
    """Short, actionable text for the UI instead of Google's raw error tuple."""
    msg = str(err.args[0]) if err.args else str(err)
    if "unauthorized_client" in msg or "Requested client not authorized" in msg:
        return (
            "Google refused domain-wide delegation (unauthorized_client). Add the service account's "
            "client ID with these scopes in Admin console > Security > API controls > Domain-wide "
            "delegation, then re-check on the Connect page."
        )
    if "Not a valid email" in msg:
        return "The impersonated admin email is not a user in this Workspace."
    if "invalid_grant" in msg:
        return (
            "Google rejected the token request (invalid_grant): check the admin email and the key."
        )
    return f"{type(err).__name__}: {msg}"


def get_state(tenant_id: uuid.UUID, key: str) -> SyncState | None:
    with session_scope() as s:
        return s.get(SyncState, (tenant_id, key))


def _upsert(tenant_id: uuid.UUID, key: str, *, quiet: bool = False, **values: Any) -> None:
    with session_scope() as s:
        stmt = insert(SyncState).values(tenant_id=tenant_id, key=key, **values)
        s.execute(stmt.on_conflict_do_update(index_elements=["tenant_id", "key"], set_=values))
    if quiet:
        return
    # After commit: tell open browsers (status changes, progress, finished jobs).
    # `changed` (new rows) lets pages skip refreshing when a check found nothing new.
    detail = values.get("detail") or {}
    publish(
        tenant_id,
        "sync",
        key=key,
        status=values.get("status"),
        progress=detail.get("progress"),
        changed=detail.get("last_batch"),
    )


def mark_running(
    tenant_id: uuid.UUID, key: str, detail: dict[str, Any] | None = None, *, quiet: bool = False
) -> None:
    values: dict[str, Any] = {"status": "running", "last_run_at": datetime.now(UTC), "error": None}
    if detail is not None:
        values["detail"] = detail
    _upsert(tenant_id, key, quiet=quiet, **values)


def update_detail(tenant_id: uuid.UUID, key: str, detail: dict[str, Any]) -> None:
    _upsert(tenant_id, key, detail=detail)


def mark_ok(
    tenant_id: uuid.UUID,
    key: str,
    *,
    cursor: datetime | None = None,
    detail: dict[str, Any] | None = None,
    quiet: bool = False,
) -> None:
    values: dict[str, Any] = {"status": "ok", "last_success_at": datetime.now(UTC), "error": None}
    if cursor is not None:
        values["cursor_time"] = cursor
    if detail is not None:
        values["detail"] = detail
    _upsert(tenant_id, key, quiet=quiet, **values)


def mark_error(tenant_id: uuid.UUID, key: str, error: str) -> None:
    _upsert(tenant_id, key, status="error", error=error[:2000])


def mark_skipped(tenant_id: uuid.UUID, key: str, reason: str) -> None:
    _upsert(tenant_id, key, status="skipped", error=reason[:2000])


def reconcile_stale(tenant_id: uuid.UUID) -> list[str]:
    """Mark "running" jobs whose process died (no one holds their lock) as interrupted.

    A job holds its advisory lock for its whole run, and Postgres releases it when
    the process or connection dies, so a free lock means nothing is running it.
    """
    with session_scope() as s:
        running = (
            s.execute(
                text("SELECT key FROM sync_state WHERE tenant_id = :t AND status = 'running'"),
                {"t": tenant_id},
            )
            .scalars()
            .all()
        )
    stale: list[str] = []
    if not running:
        return stale
    with get_engine().connect() as conn:
        for key in running:
            lock = _lock_id(tenant_id, key)
            if conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": lock}).scalar():
                conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": lock})
                stale.append(key)
        conn.commit()
    for key in stale:
        log.warning("sync job %s was interrupted (its process stopped)", key)
        _upsert(
            tenant_id,
            key,
            status="interrupted",
            error="Stopped before finishing; it will run again.",
        )
    return stale


def _lock_id(tenant_id: uuid.UUID, key: str) -> int:
    digest = hashlib.blake2b(f"{tenant_id}:{key}".encode(), digest_size=8).digest()
    return int.from_bytes(digest, "big", signed=True)


@contextmanager
def job(tenant_id: uuid.UUID, key: str, *, quiet: bool = False) -> Iterator[None]:
    """Hold a Postgres advisory lock for the job and record running/ok/error.

    quiet: frequent live checks don't announce "running"/"ok" to browsers; the job
    announces itself only when it finds something new (and errors always show)."""
    with get_engine().connect() as conn:
        lock = _lock_id(tenant_id, key)
        if not conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": lock}).scalar():
            raise JobAlreadyRunning(key)
        try:
            mark_running(tenant_id, key, quiet=quiet)
            try:
                yield
            except JobSkipped as skip:
                log.info("sync job %s skipped: %s", key, skip)
                mark_skipped(tenant_id, key, str(skip))
                return
            except Exception as err:
                log.exception("sync job %s failed", key)
                mark_error(tenant_id, key, friendly_error(err))
                raise
            # Jobs record their own cursor/detail via mark_ok; this just closes the run.
            mark_ok(tenant_id, key, quiet=quiet)
        finally:
            conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": lock})
            conn.commit()
