"""Apply new activity events to the people they belong to, right after they arrive.

The daily directory sync is the full refresh; these keep each person's details
current in between:
  login           -> last sign-in time
  meet/chat/cal   -> calls, meeting hours, chat and calendar counts (activity score)
  token           -> that person's third-party app grants
  admin/accounts  -> the directory (new/suspended/renamed users, 2-Step, roles, groups)
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import text

from orgpulse.db import session_scope
from orgpulse.realtime import publish
from orgpulse.sync import directory, event_metrics, state

log = logging.getLogger(__name__)

DERIVED_APPS = {"meet", "chat", "calendar"}
DIRECTORY_APPS = {"admin", "user_accounts"}


def max_event_id(tenant_id: uuid.UUID) -> int:
    with session_scope() as s:
        return int(
            s.execute(
                text("SELECT COALESCE(MAX(id), 0) FROM events WHERE tenant_id = :t"),
                {"t": tenant_id},
            ).scalar_one()
        )


def apply(tenant_id: uuid.UUID, after_id: int) -> dict[str, Any]:
    """React to every event stored after `after_id`. Each step is best effort."""
    with session_scope() as s:
        new = s.execute(
            text(
                """SELECT app, COUNT(*) AS n, ARRAY_AGG(DISTINCT user_email) AS users
                   FROM events WHERE tenant_id = :t AND id > :after GROUP BY app"""
            ),
            {"t": tenant_id, "after": after_id},
        ).all()
    if not new:
        return {}
    apps = {r.app: r for r in new}
    done: dict[str, Any] = {}

    if "login" in apps:
        with session_scope() as s:
            result = s.execute(
                text(
                    """UPDATE users u SET last_login_time = n.t
                       FROM (SELECT user_email, MAX(time) AS t FROM events
                             WHERE tenant_id = :t AND id > :after AND app = 'login'
                               AND event_name = 'login_success' GROUP BY 1) n
                       WHERE u.tenant_id = :t AND u.primary_email = n.user_email
                         AND (u.last_login_time IS NULL OR u.last_login_time < n.t)"""
                ),
                {"t": tenant_id, "after": after_id},
            )
            done["last_sign_in"] = int(result.rowcount or 0)  # type: ignore[attr-defined]

    if DERIVED_APPS & apps.keys():
        done["metrics"] = _locked(
            tenant_id, event_metrics.KEY, lambda: event_metrics.derive(tenant_id, days=2)
        )

    if "token" in apps:
        emails = {e for e in (apps["token"].users or []) if e}
        done["app_grants"] = _locked(
            tenant_id, "tokens:live", lambda: directory.sync_tokens_for(tenant_id, emails)
        )

    if DIRECTORY_APPS & apps.keys():

        def refresh_directory() -> dict[str, int]:
            return {
                "users": directory.sync_users(tenant_id),
                "admin_roles": directory.sync_admin_roles(tenant_id),
                "groups": directory.sync_groups(tenant_id),
            }

        done["directory"] = _locked(tenant_id, "directory", refresh_directory)

    # People's details changed: refresh what's on screen.
    publish(tenant_id, "changed", what="people", apps=sorted(apps))
    log.info("live: %s new events -> %s", {a: r.n for a, r in apps.items()}, done)
    return done


def _locked(tenant_id: uuid.UUID, key: str, fn: Any) -> Any:
    """Run under the job's lock (quietly); if that job is already running, it will cover this."""
    try:
        with state.job(tenant_id, key, quiet=True):
            return fn()
    except state.JobAlreadyRunning:
        return "already running"
    except Exception as err:
        log.warning("live reaction %s failed: %s", key, err)
        return f"error: {err}"
