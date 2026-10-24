"""Time-zone helpers shared by sync jobs and API routers."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


def utc_offset(tz_name: str) -> timedelta:
    """Current UTC offset of a zone. Exact for zones without DST (e.g. Asia/Kolkata); a DST
    zone is off by an hour for part of a window, which is fine for day/team-level figures."""
    return datetime.now(ZoneInfo(tz_name)).utcoffset() or timedelta(0)
