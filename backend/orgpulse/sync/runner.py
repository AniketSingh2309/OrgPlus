"""Named sync jobs, shared by the worker, `POST /api/sync/run` and the connect flow."""

from __future__ import annotations

import contextvars
import logging
import threading
import uuid
from collections.abc import Callable
from typing import Any

from google.auth.exceptions import RefreshError
from googleapiclient.errors import HttpError

from orgpulse import google_client as g
from orgpulse.features.gating import is_enabled
from orgpulse.features.registry import load_modules
from orgpulse.sync import directory, event_metrics, events, extras, reactions, state, usage
from orgpulse.tenancy import google_auth_for

log = logging.getLogger(__name__)


def _with_auth(tenant_id: uuid.UUID, fn: Callable[[], Any]) -> Any:
    token = g.use_auth(google_auth_for(tenant_id))
    try:
        return fn()
    finally:
        g.reset_auth(token)


def _locked(tenant_id: uuid.UUID, key: str, fn: Callable[[], Any]) -> Any:
    with state.job(tenant_id, key):
        return fn()


def run_directory(tenant_id: uuid.UUID) -> Any:
    return _locked(tenant_id, "directory", lambda: directory.sync_all(tenant_id))


def run_usage(tenant_id: uuid.UUID) -> Any:
    return _locked(tenant_id, usage.KEY, lambda: usage.sync_usage(tenant_id))


def run_events_live(tenant_id: uuid.UUID) -> Any:
    """Every app, short look-back, about once a minute; new events update their people."""
    before = reactions.max_event_id(tenant_id)
    found: dict[str, Any] = {}
    for app in events.all_core_apps():
        try:
            with state.job(tenant_id, events.state_key(app), quiet=True):
                found[app] = events.sync_app(
                    tenant_id, app, lookback=events.LIVE_LOOKBACK, quiet=True
                )
        except state.JobAlreadyRunning:
            found[app] = "running"  # the deep run has it
        except Exception as err:
            found[app] = f"error: {err}"
    if any(isinstance(n, int) and n for n in found.values()):
        found["reactions"] = reactions.apply(tenant_id, before)
    return found


def run_events_slow(tenant_id: uuid.UUID) -> Any:
    """Deep catch-up: every app, days of look-back, for events Google publishes late."""
    before = reactions.max_event_id(tenant_id)
    result = events.sync_apps(tenant_id, events.all_core_apps())
    run_derived(tenant_id)  # Meet/Chat/Calendar counts may come from these events
    reactions.apply(tenant_id, before)
    return result


# Kept for cron setups that call the old name.
run_events_fast = run_events_live


def run_geo(tenant_id: uuid.UUID) -> Any:
    """Locate already-synced events (new ones are located as they're inserted)."""
    from orgpulse import geo

    return _locked(tenant_id, "geo", lambda: geo.enrich_existing(tenant_id))


def run_geoip_update(tenant_id: uuid.UUID) -> Any:
    """Fetch this month's DB-IP City Lite, then locate events with the new data."""
    from orgpulse import geoip_update

    path = _locked(tenant_id, "geoip_update", geoip_update.update)
    return {"database": str(path), "located": run_geo(tenant_id)}


def run_derived(tenant_id: uuid.UUID) -> Any:
    return _locked(tenant_id, event_metrics.KEY, lambda: event_metrics.derive(tenant_id))


def run_licences(tenant_id: uuid.UUID) -> Any:
    def go() -> Any:
        try:
            return extras.sync_licences(tenant_id)
        except HttpError as err:
            raise state.JobSkipped(f"License Manager API returned HTTP {err.resp.status}") from err
        except RefreshError as err:
            raise state.JobSkipped("apps.licensing scope not granted (optional)") from err

    return _locked(tenant_id, "licences", go)


def run_shared_drives(tenant_id: uuid.UUID) -> Any:
    def go() -> Any:
        try:
            return extras.sync_shared_drives(tenant_id)
        except HttpError as err:
            raise state.JobSkipped(f"Drive API returned HTTP {err.resp.status}") from err
        except RefreshError as err:
            raise state.JobSkipped("drive.readonly scope not granted (optional)") from err

    return _locked(tenant_id, "shared_drives", go)


def run_plan(tenant_id: uuid.UUID) -> Any:
    from orgpulse.plan.detect import run_detection

    return _locked(tenant_id, "plan", lambda: run_detection(tenant_id))


def run_modules(tenant_id: uuid.UUID) -> dict[str, Any]:
    """Sync every enabled feature module."""
    out: dict[str, Any] = {}
    for key, module in load_modules().items():
        if module.sync is None or not is_enabled(tenant_id, key):
            continue
        sync = module.sync
        try:
            out[key] = _locked(tenant_id, f"module:{key}", lambda s=sync: s(tenant_id))  # type: ignore[misc]
        except Exception as err:
            out[key] = f"error: {err}"
    return out


def run_full(tenant_id: uuid.UUID) -> dict[str, Any]:
    """Everything, in dependency order. On an empty DB this is the 180-day backfill."""
    result: dict[str, Any] = {}
    for name, fn in (
        ("directory", run_directory),
        ("licences", run_licences),
        ("plan", run_plan),
        ("events_fast", run_events_fast),
        ("usage", run_usage),
        ("events_slow", run_events_slow),
        ("shared_drives", run_shared_drives),
        ("modules", run_modules),
    ):
        try:
            result[name] = fn(tenant_id)
        except state.JobAlreadyRunning:
            result[name] = "already running"
        except Exception as err:
            log.exception("%s failed", name)
            result[name] = f"error: {err}"
    return result


JOBS: dict[str, Callable[[uuid.UUID], Any]] = {
    "all": run_full,
    "directory": run_directory,
    "usage": run_usage,
    "events_live": run_events_live,
    "events_fast": run_events_fast,
    "events_slow": run_events_slow,
    "licences": run_licences,
    "shared_drives": run_shared_drives,
    "plan": run_plan,
    "modules": run_modules,
    "derived": run_derived,
    "geo": run_geo,
    "geoip_update": run_geoip_update,
}


def run(name: str, tenant_id: uuid.UUID) -> Any:
    log.info("sync job %s starting", name)
    result = _with_auth(tenant_id, lambda: JOBS[name](tenant_id))
    log.info("sync job %s finished: %s", name, result)
    return result


def run_in_background(name: str, tenant_id: uuid.UUID) -> None:
    def target() -> None:
        try:
            run(name, tenant_id)
        except Exception:
            log.exception("background sync %s failed", name)

    # Threads don't inherit context variables: carry the selected organisation along.
    ctx = contextvars.copy_context()
    threading.Thread(target=lambda: ctx.run(target), name=f"sync-{name}", daemon=True).start()
