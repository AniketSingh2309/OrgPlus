"""Sync worker: `python -m orgpulse.worker` (APScheduler) or `--once JOB` (for cron).

Schedule (UTC):
  activity events      every minute (live: sign-ins, tokens, Meet, Drive, Calendar,
                       Chat, groups, admin, SSO, accounts, Classroom), and a deep
                       catch-up every 6 hours for events Google publishes late
  directory + licences daily 01:00
  usage                daily 03:00 (Google lags 2-3 days; the job re-pulls recent days)
  shared drives        daily 02:00
  plan detection       daily 04:00
  feature modules      per module schedule
  weekly digest        Monday 02:30 (08:00 IST)
On start, if nothing has ever synced, the full 180-day backfill runs first.

Multi-org: every scheduled job runs once per active organisation, each inside
`use_org(org)` so it can only open that organisation's database. With
ADMIN_DATABASE_URL set (the worker is the only process that should have it), the
worker also prepares Postgres on start (control tables, every organisation's
migrations) and creates the database of each newly signed-up organisation within
seconds.
"""

from __future__ import annotations

import argparse
import contextvars
import logging
import sys
import threading
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

from apscheduler.schedulers.blocking import BlockingScheduler
from sqlalchemy import text

from orgpulse import google_client as g
from orgpulse.config import get_settings
from orgpulse.db import OrgRef, multi_org, session_scope, use_org
from orgpulse.features.gating import is_enabled
from orgpulse.features.registry import load_modules
from orgpulse.logging_setup import setup_logging
from orgpulse.sync import runner, state
from orgpulse.tenancy import default_tenant_id, google_auth_for, has_credentials

log = logging.getLogger("orgpulse.worker")


def _orgs() -> list[OrgRef | None]:
    """The organisations to work on: every active one, or the single tenant (None)."""
    if not multi_org():
        return [None]
    from orgpulse.orgs import active_orgs

    return list(active_orgs())


def _run_for(org: OrgRef | None, fn: Callable[..., None], *args: object) -> None:
    if org is None:
        fn(*args, default_tenant_id())
        return
    with use_org(org):
        try:
            fn(*args, org.id)
        except Exception:
            log.exception("%s failed for %s", getattr(fn, "__name__", fn), org.domain)


_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="org")


def _each(fn: Callable[..., None], *args: object) -> None:
    """Run fn(*args, tenant_id) for every organisation, a few in parallel, each isolated."""
    orgs = _orgs()
    if len(orgs) == 1:
        _run_for(orgs[0], fn, *args)
        return
    futures = [
        _pool.submit(contextvars.copy_context().run, _run_for, org, fn, *args) for org in orgs
    ]
    for f in futures:
        f.result()


def _job(name: str, tenant_id: uuid.UUID) -> None:
    if not has_credentials(tenant_id):
        log.info("skipping %s: Workspace not connected yet", name)
        return
    try:
        runner.run(name, tenant_id)
    except state.JobAlreadyRunning:
        log.info("%s already running; skipped", name)
    except Exception:
        log.exception("%s failed", name)


def _module_job(key: str, tenant_id: uuid.UUID) -> None:
    module = load_modules()[key]
    if module.sync is None or not has_credentials(tenant_id) or not is_enabled(tenant_id, key):
        return
    token = g.use_auth(google_auth_for(tenant_id))
    try:
        with state.job(tenant_id, f"module:{key}"):
            module.sync(tenant_id)
    except state.JobAlreadyRunning:
        pass
    except Exception:
        log.exception("module %s sync failed", key)
    finally:
        g.reset_auth(token)


def _digest(tenant_id: uuid.UUID) -> None:
    from orgpulse import digest

    token = g.use_auth(google_auth_for(tenant_id)) if has_credentials(tenant_id) else None
    try:
        log.info("digest: %s", digest.send(tenant_id))
    except Exception:
        log.exception("digest failed")
    finally:
        if token is not None:
            g.reset_auth(token)


def _geoip(tenant_id: uuid.UUID) -> None:
    """Refresh the city database (no Google access needed, so no credential check)."""
    try:
        runner.run("geoip_update", tenant_id)
    except Exception:
        log.exception("GeoIP update failed; the sign-in map keeps the previous file")


def _geoip_once() -> None:
    """The city database is a shared, non-personal file: download it once, not per org."""
    orgs = _orgs()
    if orgs:
        _run_for(orgs[0], _geoip)


def _resume_interrupted(tenant_id: uuid.UUID) -> None:
    """Re-run jobs whose process died mid-run (e.g. an API restart during a backfill)."""
    state.reconcile_stale(tenant_id)
    with session_scope() as s:
        keys = (
            s.execute(
                text("SELECT key FROM sync_state WHERE tenant_id = :t AND status = 'interrupted'"),
                {"t": tenant_id},
            )
            .scalars()
            .all()
        )
    jobs = {RESUMABLE.get(k.split(":")[0], k) for k in keys}
    for name in sorted(j for j in jobs if j in runner.JOBS):
        log.info("resuming interrupted job %s", name)
        _job(name, tenant_id)


# sync_state key prefix -> runner job that redoes it
RESUMABLE = {"events": "events_slow", "derived_metrics": "derived", "module": "modules"}


def _startup(tenant_id: uuid.UUID) -> None:
    if not has_credentials(tenant_id):
        return
    state.reconcile_stale(tenant_id)
    if state.get_state(tenant_id, "directory") is None:
        log.info("first run: starting the 180-day backfill in the background")
        runner.run_in_background("all", tenant_id)


def _provision() -> None:
    from orgpulse.orgs import provision_pending

    try:
        provision_pending()
    except Exception:
        log.exception("provisioning check failed")


def prepare_databases() -> None:
    """Deploy-time self-setup: control database + tables, then migrate every organisation."""
    from orgpulse.accounts import ensure_schema
    from orgpulse.db import control_engine
    from orgpulse.orgs import migrate_all, provision_pending, setup_control, sync_allowed

    setup_control()
    ensure_schema(control_engine())
    sync_allowed()
    provision_pending()
    migrate_all()
    log.info("databases ready")


def build_scheduler() -> BlockingScheduler:
    sch = BlockingScheduler(
        timezone="UTC",
        job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 3600},
    )
    settings = get_settings()
    # Live: every activity app about once a minute, so each person's sign-ins, calls,
    # files, chat, calendar and app grants show up as soon as Google publishes them.
    sch.add_job(
        _each,
        "interval",
        seconds=settings.events_live_seconds,
        args=[_job, "events_live"],
        id="events_live",
        next_run_time=datetime.now(UTC),
    )
    # Deep catch-up for events Google publishes late (re-reads days back).
    sch.add_job(
        _each,
        "interval",
        minutes=settings.events_deep_minutes,
        args=[_job, "events_slow"],
        id="events_deep",
        next_run_time=datetime.now(UTC) + timedelta(minutes=2),
    )
    sch.add_job(_each, "interval", minutes=2, args=[_resume_interrupted], id="resume")
    if multi_org() and settings.admin_database_url:
        # New sign-ups get their private database within seconds.
        sch.add_job(_provision, "interval", seconds=5, id="provision")
    # DB-IP publishes City Lite monthly; refresh early in the month (one shared file).
    sch.add_job(_geoip_once, "cron", day=3, hour=5, id="geoip_update")
    sch.add_job(_each, "cron", hour=1, minute=0, args=[_job, "directory"], id="directory")
    sch.add_job(_each, "cron", hour=1, minute=40, args=[_job, "licences"], id="licences")
    sch.add_job(_each, "cron", hour=2, minute=0, args=[_job, "shared_drives"], id="shared_drives")
    sch.add_job(_each, "cron", hour=3, minute=0, args=[_job, "usage"], id="usage")
    sch.add_job(_each, "cron", hour=4, minute=0, args=[_job, "plan"], id="plan")
    sch.add_job(_each, "cron", day_of_week="mon", hour=2, minute=30, args=[_digest], id="digest")
    for key, module in load_modules().items():
        if module.sync is not None:
            sch.add_job(_each, args=[_module_job, key], id=f"module:{key}", **module.schedule)
    return sch


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m orgpulse.worker")
    parser.add_argument(
        "--once", choices=sorted(runner.JOBS), help="run one job and exit (for cron)"
    )
    parser.add_argument("--org", help="multi-org: only this organisation's domain (with --once)")
    args = parser.parse_args(argv)
    setup_logging()

    if args.once:
        orgs = [o for o in _orgs() if o is None or not args.org or o.domain == args.org.lower()]
        if not orgs:
            log.error("no active organisation matches %s", args.org)
            return 1
        failed = False

        def once(tenant_id: uuid.UUID) -> None:
            nonlocal failed
            if not has_credentials(tenant_id):
                log.error(
                    "Workspace not connected: upload a credential at /connect "
                    "or set GOOGLE_* env vars"
                )
                failed = True
                return
            runner.run(args.once, tenant_id)

        for org in orgs:
            _run_for(org, once)
        return 1 if failed else 0

    if multi_org():
        if get_settings().admin_database_url:
            prepare_databases()
        else:
            log.warning("ADMIN_DATABASE_URL not set: new sign-ups won't get a database until it is")
    _each(_startup)
    if not get_settings().geoip_db.is_file():
        log.info("no GeoIP database yet: downloading DB-IP City Lite in the background")
        threading.Thread(
            target=contextvars.copy_context().run, args=[_geoip_once], daemon=True
        ).start()

    sch = build_scheduler()
    log.info("scheduler jobs: %s (organisations: %d)", [j.id for j in sch.get_jobs()], len(_orgs()))
    sch.start()
    return 0


if __name__ == "__main__":
    sys.exit(main())
