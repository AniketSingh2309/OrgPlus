"""Daily metrics derived from activity events, for metrics the usage report doesn't carry.

Some domains get no meet:/chat:/calendar: parameters in userUsageReport at all
(seen on Business Starter), but the Reports *activity* logs for those apps are
there. For any score metric the usage sync recorded as missing, we count it
from events instead, per user and local day:

  mt  Meet calls          meet / call_ended (the actor is the internal participant)
  mm  Meet minutes        sum of call_ended duration_seconds / 60
  mh  Meet hours          mm / 60
  ch  Chat messages       chat / message_posted
  cal Calendar events     calendar / create_event

Values from the usage report always win: a metric is only derived while the
usage sync lists it as missing.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text

from orgpulse.db import session_scope
from orgpulse.models import TenantSettings
from orgpulse.sync import state
from orgpulse.sync.usage import KEY as USAGE_KEY
from orgpulse.timeutil import utc_offset

log = logging.getLogger(__name__)

KEY = "derived_metrics"
RECOMPUTE_DAYS = 7  # late-arriving events can still change recent days

# metric -> (app, event_name, SQL value expression per event)
SOURCES: dict[str, tuple[str, str, str]] = {
    "mt": ("meet", "call_ended", "1"),
    "mm": ("meet", "call_ended", "COALESCE((e.params->>'duration_seconds')::numeric, 0) / 60.0"),
    "mh": ("meet", "call_ended", "COALESCE((e.params->>'duration_seconds')::numeric, 0) / 3600.0"),
    "ch": ("chat", "message_posted", "1"),
    "cal": ("calendar", "create_event", "1"),
}
# mh follows mm: derive hours whenever minutes come from events.
FOLLOWS = {"mh": "mm"}


def metrics_to_derive(tenant_id: uuid.UUID) -> list[str]:
    usage = state.get_state(tenant_id, USAGE_KEY)
    missing = set((usage.detail or {}).get("missing_metrics", {}) if usage else ())
    return [m for m in SOURCES if m in missing or FOLLOWS.get(m) in missing]


def derive(tenant_id: uuid.UUID, *, days: int | None = None) -> dict[str, Any]:
    metrics = metrics_to_derive(tenant_id)
    if not metrics:
        state.mark_ok(tenant_id, KEY, detail={"metrics": []})
        return {"metrics": [], "rows": 0}

    prev = state.get_state(tenant_id, KEY)
    first_run = prev is None or not (prev.detail or {}).get("metrics")
    window = days or (180 if first_run else RECOMPUTE_DAYS)
    since = datetime.now(UTC) - timedelta(days=window)

    with session_scope() as s:
        tz = s.get(TenantSettings, tenant_id)
        tz_name = tz.timezone if tz else "Asia/Kolkata"
    offset = utc_offset(tz_name)
    total = 0
    with session_scope() as s:
        for metric in metrics:
            app, event_name, value = SOURCES[metric]
            result = s.execute(
                text(
                    f"""
                    INSERT INTO daily_usage (tenant_id, user_id, date, metric, user_email, value)
                    SELECT e.tenant_id, u.id, ((e.time AT TIME ZONE 'UTC') + :offset)::date, :metric,
                           u.primary_email, SUM({value})
                    FROM events e
                    JOIN users u ON u.tenant_id = e.tenant_id AND u.primary_email = e.user_email
                    WHERE e.tenant_id = :t AND e.app = :app AND e.event_name = :ev AND e.time >= :since
                    GROUP BY e.tenant_id, u.id, u.primary_email, 3
                    ON CONFLICT (tenant_id, user_id, date, metric) DO UPDATE SET value = EXCLUDED.value
                    """
                ),
                {
                    "t": tenant_id,
                    "app": app,
                    "ev": event_name,
                    "since": since,
                    "metric": metric,
                    "offset": offset,
                },
            )
            total += int(result.rowcount or 0)  # type: ignore[attr-defined]

    log.info("derived %s from events: %d user-days (last %d days)", metrics, total, window)
    state.mark_ok(tenant_id, KEY, detail={"metrics": metrics, "rows": total, "window_days": window})
    return {"metrics": metrics, "rows": total}
