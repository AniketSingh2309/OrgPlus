"""IP -> location from a city .mmdb (DB-IP City Lite or MaxMind GeoLite2 City)."""

from __future__ import annotations

import ipaddress
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Any

from sqlalchemy import text

from orgpulse.config import get_settings

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Location:
    country: str | None
    city: str | None
    lat: float | None
    lon: float | None


@lru_cache(maxsize=2)
def _open(path: str, mtime: float) -> Any:
    import geoip2.database

    log.info("GeoIP database loaded: %s", path)
    return geoip2.database.Reader(path)


def _reader() -> Any | None:
    """Current reader; a newly downloaded file is picked up without a restart."""
    path = get_settings().geoip_db
    if not path.is_file():
        return None
    return _open(str(path), path.stat().st_mtime)


def available() -> bool:
    return _reader() is not None


@lru_cache(maxsize=50_000)
def _lookup(ip: str, db_mtime: float) -> Location | None:
    reader = _reader()
    if reader is None:
        return None
    try:
        r = reader.city(ip)
    except Exception:
        return None
    return Location(r.country.iso_code, r.city.name, r.location.latitude, r.location.longitude)


def lookup(ip: str | None) -> Location | None:
    if not ip:
        return None
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return None
    if addr.is_private or addr.is_loopback:
        return None
    path = get_settings().geoip_db
    if not path.is_file():
        return None
    return _lookup(ip, path.stat().st_mtime)


def enrich_existing(tenant_id: uuid.UUID, days: int = 180) -> int:
    """Fill city/lat/lon for already-synced events that have an IP but no coordinates."""
    from orgpulse.db import session_scope

    if not available():
        log.info("no GeoIP database; skipping location backfill")
        return 0
    since = datetime.now(UTC) - timedelta(days=days)
    with session_scope() as s:
        ips = (
            s.execute(
                text(
                    """SELECT DISTINCT ip FROM events
                   WHERE tenant_id = :t AND ip IS NOT NULL AND lat IS NULL AND time >= :s"""
                ),
                {"t": tenant_id, "s": since},
            )
            .scalars()
            .all()
        )
    located = [(ip, loc) for ip in ips if (loc := lookup(ip)) is not None and loc.lat is not None]
    updated = 0
    with session_scope() as s:
        # One set-based UPDATE per batch (the events table is large and ip isn't indexed).
        for i in range(0, len(located), 500):
            batch = located[i : i + 500]
            values = ", ".join(
                f"(:ip{n}, :city{n}, :lat{n}, :lon{n}, :country{n})" for n in range(len(batch))
            )
            params: dict[str, Any] = {"t": tenant_id, "s": since}
            for n, (ip, loc) in enumerate(batch):
                params |= {
                    f"ip{n}": ip,
                    f"city{n}": loc.city,
                    f"lat{n}": loc.lat,
                    f"lon{n}": loc.lon,
                    f"country{n}": loc.country,
                }
            result = s.execute(
                text(
                    f"""UPDATE events e SET city = v.city, lat = v.lat::float, lon = v.lon::float,
                               country = COALESCE(e.country, v.country)
                        FROM (VALUES {values}) AS v(ip, city, lat, lon, country)
                        WHERE e.tenant_id = :t AND e.ip = v.ip AND e.lat IS NULL AND e.time >= :s"""
                ),
                params,
            )
            updated += int(result.rowcount or 0)  # type: ignore[attr-defined]
    log.info("located %d events from %d IPs", updated, len(ips))
    return updated
