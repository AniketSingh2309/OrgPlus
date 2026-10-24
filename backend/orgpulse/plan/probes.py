"""Capability probes: one cheap read call per paid feature.

success / empty result -> on            (empty means "available, no events yet")
403/400 "not available" -> locked
missing scope / setup   -> not_configured
anything else           -> error        ("check failed, retry")
"""

from __future__ import annotations

import logging
import socket
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from google.auth.exceptions import RefreshError, TransportError
from googleapiclient.errors import HttpError

from orgpulse import google_client as g
from orgpulse.config import get_settings
from orgpulse.plan.skus import TIER_RANK

log = logging.getLogger(__name__)

ON, LOCKED, ERROR, NOT_CONFIGURED = "on", "locked", "error", "not_configured"


@dataclass(frozen=True)
class ProbeResult:
    status: str
    detail: str = ""


@dataclass(frozen=True)
class ProbeContext:
    customer_id: str
    bigquery_project: str | None = None
    bigquery_dataset: str | None = None
    # From licence detection; None when the edition is unknown.
    edition: str | None = None
    tier: str | None = None


_LOCKED_HINTS = (
    "not available",
    "not enabled for",
    "does not have access",
    "not supported",
    "requires",
    "edition",
    "license",
    "licence",
    "not authorized to access this resource",
    "insufficient permission",
    "forbidden",
)


def classify_error(err: BaseException, scope: str | None = None) -> ProbeResult:
    """Turn an exception from a probe call into a status."""
    if isinstance(err, RefreshError):
        if "unauthorized_client" in str(err):
            return ProbeResult(
                NOT_CONFIGURED, f"scope not granted: {scope}" if scope else "scope not granted"
            )
        return ProbeResult(ERROR, f"token error: {err}")
    if isinstance(err, HttpError):
        status = err.resp.status
        message = str(err).lower()
        if "accessnotconfigured" in message or "has not been used in project" in message:
            return ProbeResult(NOT_CONFIGURED, "API not enabled in the GCP project")
        if status in (400, 403) and any(h in message for h in _LOCKED_HINTS):
            return ProbeResult(LOCKED, f"HTTP {status}: not available for this customer")
        if status == 403:
            return ProbeResult(LOCKED, "HTTP 403")
        if status == 400:
            return ProbeResult(LOCKED, "HTTP 400: not available for this customer")
        return ProbeResult(ERROR, f"HTTP {status}; retry")
    if isinstance(err, (TimeoutError, socket.timeout, TransportError, ConnectionError)):
        return ProbeResult(ERROR, "timed out; retry")
    return ProbeResult(ERROR, f"{type(err).__name__}: {err}")


def _run(call: Callable[[], Any], scope: str | None = None) -> ProbeResult:
    try:
        call()
    except Exception as err:
        result = classify_error(err, scope)
        log.info("probe failed: %s", result.detail)
        return result
    return ProbeResult(ON)


def _reports_app(app: str, min_tier: str | None = None) -> Callable[[ProbeContext], ProbeResult]:
    """Probe a Reports application.

    Google answers an empty list (not an access error) for log types the edition
    doesn't include, so an empty answer only counts as "on" when the detected
    edition includes the feature (or the edition is unknown). Real events = on.
    """

    def probe(ctx: ProbeContext) -> ProbeResult:
        found: list[int] = []

        def call() -> None:
            resp = g.execute(
                g.reports().activities().list(userKey="all", applicationName=app, maxResults=1),
                max_attempts=2,
            )
            found.append(len(resp.get("items") or []))

        result = _run(call, g.AUDIT_SCOPE)
        if result.status != ON or (found and found[0] > 0) or not min_tier:
            return result
        if ctx.tier in TIER_RANK and TIER_RANK[ctx.tier] < TIER_RANK[min_tier]:
            return ProbeResult(
                LOCKED,
                f"Not included in {ctx.edition or 'your edition'}; Google returns no events for it",
            )
        return ProbeResult(ON, "available; no events yet")

    return probe


def _bq_query(ctx: ProbeContext, sql: str) -> int:
    resp = g.execute(
        g.bigquery()
        .jobs()
        .query(
            projectId=ctx.bigquery_project,
            body={"query": sql, "useLegacySql": False, "timeoutMs": 20000},
        ),
        max_attempts=2,
    )
    rows = resp.get("rows") or []
    return int(rows[0]["f"][0]["v"]) if rows else 0


def probe_bigquery(ctx: ProbeContext) -> ProbeResult:
    if not (ctx.bigquery_project and ctx.bigquery_dataset):
        return ProbeResult(NOT_CONFIGURED, "no BigQuery project/dataset given")
    table = f"`{ctx.bigquery_project}.{ctx.bigquery_dataset}"
    try:
        recent_activity = _bq_query(
            ctx,
            f"SELECT COUNT(1) FROM {table}.activity` WHERE time_usec >= "
            "UNIX_MICROS(TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 3 DAY))",
        )
        recent_usage = _bq_query(
            ctx,
            f"SELECT COUNT(1) FROM {table}.usage` WHERE date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)",
        )
    except HttpError as err:
        if err.resp.status == 404:
            return ProbeResult(LOCKED, "tables activity/usage not found in dataset")
        return classify_error(err, g.BIGQUERY_SCOPE)
    except Exception as err:
        return classify_error(err, g.BIGQUERY_SCOPE)
    if recent_activity and recent_usage:
        return ProbeResult(ON, f"{recent_activity} activity rows in last 3 days")
    return ProbeResult(LOCKED, "export tables exist but have no rows in the last 3 days")


def probe_gmail_logs(ctx: ProbeContext) -> ProbeResult:
    result = _reports_app("gmail")(ctx)
    if result.status == ON or not (ctx.bigquery_project and ctx.bigquery_dataset):
        return result
    try:
        n = _bq_query(
            ctx,
            f"SELECT COUNT(1) FROM `{ctx.bigquery_project}.{ctx.bigquery_dataset}.activity` "
            "WHERE record_type = 'gmail' AND time_usec >= "
            "UNIX_MICROS(TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 3 DAY))",
        )
    except Exception:
        return result
    return ProbeResult(ON, "gmail rows in BigQuery export") if n else result


def probe_vault(_: ProbeContext) -> ProbeResult:
    return _run(
        lambda: g.execute(g.vault().matters().list(pageSize=1), max_attempts=2), g.VAULT_SCOPE
    )


def probe_alert_center(_: ProbeContext) -> ProbeResult:
    return _run(
        lambda: g.execute(g.alertcenter().alerts().list(pageSize=1), max_attempts=2), g.ALERTS_SCOPE
    )


def probe_classroom(_: ProbeContext) -> ProbeResult:
    if not get_settings().enable_classroom:
        return ProbeResult(NOT_CONFIGURED, "ENABLE_CLASSROOM=false")
    return _run(
        lambda: g.execute(g.classroom().courses().list(pageSize=1), max_attempts=2),
        g.CLASSROOM_SCOPES[0],
    )


def probe_chrome(ctx: ProbeContext) -> ProbeResult:
    return _run(
        lambda: g.execute(
            g.chromemanagement()
            .customers()
            .reports()
            .countChromeVersions(customer=f"customers/{ctx.customer_id}", pageSize=1),
            max_attempts=2,
        ),
        g.CHROME_SCOPE,
    )


PROBES: dict[str, Callable[[ProbeContext], ProbeResult]] = {
    "bigquery_logs": probe_bigquery,
    "gmail_logs": probe_gmail_logs,
    "vault": probe_vault,
    "alert_center": probe_alert_center,
    "dlp_events": _reports_app("rules", min_tier="enterprise"),
    "context_aware_access": _reports_app("context_aware_access", min_tier="enterprise"),
    "gemini_usage": _reports_app("gemini_in_workspace_apps"),
    "classroom": probe_classroom,
    "chrome_mgmt": probe_chrome,
}
