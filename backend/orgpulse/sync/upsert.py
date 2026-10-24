"""Batched, idempotent Postgres upserts."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from itertools import islice
from typing import Any, cast

from sqlalchemy import Table, delete, func, literal_column
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import DeclarativeBase, Session

BATCH = 1000


def _batches(rows: Iterable[dict[str, Any]], size: int = BATCH) -> Iterable[list[dict[str, Any]]]:
    it = iter(rows)
    while chunk := list(islice(it, size)):
        yield chunk


def upsert(
    session: Session,
    model: type[DeclarativeBase],
    rows: Iterable[dict[str, Any]],
    keys: Sequence[str],
    *,
    touch_synced_at: bool = True,
) -> int:
    """INSERT ... ON CONFLICT (keys) DO UPDATE every non-key column. Returns rows sent."""
    table = cast(Table, model.__table__)
    total = 0
    for chunk in _batches(rows):
        # Duplicate keys inside one statement make Postgres refuse ON CONFLICT DO UPDATE.
        dedup = {tuple(r[k] for k in keys): r for r in chunk}
        stmt = insert(table).values(list(dedup.values()))
        cols = set(chunk[0]) - set(keys)
        updates: dict[str, Any] = {c: stmt.excluded[c] for c in cols}
        if touch_synced_at and "synced_at" in table.c:
            updates["synced_at"] = func.now()
        if updates:
            stmt = stmt.on_conflict_do_update(index_elements=list(keys), set_=updates)
        else:
            stmt = stmt.on_conflict_do_nothing(index_elements=list(keys))
        session.execute(stmt)
        total += len(dedup)
    return total


def insert_ignore(
    session: Session, model: type[DeclarativeBase], rows: Iterable[dict[str, Any]]
) -> int:
    """INSERT ... ON CONFLICT DO NOTHING (any unique constraint). Returns rows actually added
    (duplicates that were already stored don't count)."""
    table = cast(Table, model.__table__)
    total = 0
    for chunk in _batches(rows):
        # RETURNING gives exactly the rows inserted (multi-row rowcount isn't reliable).
        stmt = insert(table).values(chunk).on_conflict_do_nothing()
        total += len(session.execute(stmt.returning(literal_column("1"))).fetchall())
    return total


def delete_not_synced_since(
    session: Session, model: type[DeclarativeBase], tenant_id: Any, since: Any
) -> int:
    """Remove rows this tenant's sync did not touch (deleted upstream)."""
    table = cast(Table, model.__table__)
    result = session.execute(
        delete(table).where(table.c.tenant_id == tenant_id, table.c.synced_at < since)
    )
    return int(result.rowcount or 0)  # type: ignore[attr-defined]
