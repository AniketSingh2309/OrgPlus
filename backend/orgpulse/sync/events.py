"""Activity events from reports.activities.list, with a cursor per app.

The first run per app backfills 180 days (Google drops older logs). Later runs
start a little before the cursor because some apps publish events late;
inserts are idempotent on (tenant, app, time, uniqueQualifier, event_seq).
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from google.auth.exceptions import RefreshError
from googleapiclient.errors import HttpError

from orgpulse import geo
from orgpulse import google_client as g
from orgpulse.config import get_settings
from orgpulse.db import session_scope
from orgpulse.models import Event
from orgpulse.sync import state
from orgpulse.sync.mappers import map_activity
from orgpulse.sync.upsert import insert_ignore
from orgpulse.tenancy import tenant_domains

log = logging.getLogger(__name__)

FAST_APPS = ("login", "token")
SLOW_APPS = ("drive", "meet", "calendar", "chat", "groups", "admin", "saml", "user_accounts")
CLASSROOM_APPS = ("classroom",)
# Live checks (about every minute) only look back this far; the 6-hourly deep run
# re-reads days back for anything Google publishes late.
LIVE_LOOKBACK = timedelta(minutes=15)

# How far before the cursor each run starts again (late-arriving events).
LOOKBACK = {"login": timedelta(hours=6), "token": timedelta(hours=6)}
DEFAULT_LOOKBACK = timedelta(days=2)


def state_key(app: str) -> str:
    return f"events:{app}"


def all_core_apps() -> tuple[str, ...]:
    apps = FAST_APPS + SLOW_APPS
    return apps + CLASSROOM_APPS if get_settings().enable_classroom else apps


def _enrich_geo(row: dict[str, Any]) -> None:
    loc = geo.lookup(row.get("ip"))
    if loc is None:
        return
    row["country"] = row["country"] or loc.country
    row["city"] = loc.city
    row["lat"] = loc.lat
    row["lon"] = loc.lon


def sync_app(
    tenant_id: uuid.UUID,
    app: str,
    *,
    backfill_days: int | None = None,
    lookback: timedelta | None = None,
    quiet: bool = False,
) -> int:
    key = state_key(app)
    prev = state.get_state(tenant_id, key)
    now = datetime.now(UTC)
    if prev and prev.cursor_time:
        start = prev.cursor_time - (lookback or LOOKBACK.get(app, DEFAULT_LOOKBACK))
    else:
        start = now - timedelta(days=backfill_days or get_settings().backfill_days)
    # The API rejects startTime older than its retention; clamp just inside 180 days.
    start = max(start, now - timedelta(days=179, hours=23))

    domains = tenant_domains(tenant_id)
    total = 0
    pages = 0
    token: str | None = None
    while True:
        params: dict[str, Any] = {
            "userKey": "all",
            "applicationName": app,
            "startTime": start.isoformat().replace("+00:00", "Z"),
            "endTime": now.isoformat().replace("+00:00", "Z"),
            "maxResults": 1000,
        }
        if token:
            params["pageToken"] = token
        resp = g.execute(g.reports().activities().list(**params), what=f"activities.list({app})")
        rows: list[dict[str, Any]] = []
        for item in resp.get("items", []):
            rows += map_activity(item, app, tenant_id, domains)
        for row in rows:
            _enrich_geo(row)
        if rows:
            with session_scope() as s:
                total += insert_ignore(s, Event, rows)
        pages += 1
        if pages % 20 == 0:
            log.info("events %s: %d pages, %d events so far", app, pages, total)
        token = resp.get("nextPageToken")
        if not token:
            break

    # A quiet (live) check only tells browsers when it actually found new events.
    state.mark_ok(
        tenant_id, key, cursor=now, detail={"last_batch": total}, quiet=quiet and not total
    )
    log.info("events %s: %d events since %s", app, total, start.date())
    return total


def sync_apps(tenant_id: uuid.UUID, apps: tuple[str, ...]) -> dict[str, int | str]:
    """Sync several apps; one failing app does not stop the others."""
    out: dict[str, int | str] = {}
    for app in apps:
        try:
            with state.job(tenant_id, state_key(app)):
                out[app] = sync_app(tenant_id, app)
        except state.JobAlreadyRunning:
            out[app] = "already running"
        except HttpError as err:
            out[app] = f"HTTP {err.resp.status}"
        except RefreshError as err:  # recorded in sync_state by state.job
            out[app] = state.friendly_error(err)
    return out
