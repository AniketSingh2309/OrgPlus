"""Google API access through a service account with domain-wide delegation.

Credentials are built with `.with_subject(ADMIN)` so every call runs as the
impersonated admin. The service-account key comes from the tenant's encrypted
credential (stored by /connect) or, failing that, GOOGLE_SERVICE_ACCOUNT_JSON.
Service objects are cached per thread, because googleapiclient's httplib2
transport is not thread-safe.

Org+ is read-only against Google: `execute()` refuses anything that is not
a GET, except a short allowlist of read-only POST endpoints (BigQuery queries)
and the optional digest send, which callers must name explicitly.
"""

from __future__ import annotations

import contextvars
import json
import logging
import random
import threading
import time
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from typing import Any, cast

from google.oauth2 import service_account
from googleapiclient.discovery import Resource, build
from googleapiclient.errors import HttpError
from googleapiclient.http import HttpRequest

from orgpulse.config import get_settings

log = logging.getLogger(__name__)

_AUTH = "https://www.googleapis.com/auth/"


def _scopes(*names: str) -> tuple[str, ...]:
    return tuple(_AUTH + n for n in names)


CORE_SCOPES: tuple[str, ...] = _scopes(
    "admin.directory.user.readonly",
    "admin.directory.group.readonly",
    "admin.directory.orgunit.readonly",
    "admin.directory.rolemanagement.readonly",
    "admin.directory.device.mobile.readonly",
    "admin.directory.device.chromeos.readonly",
    # No read-only variant exists; needed for tokens.list. We only ever read.
    "admin.directory.user.security",
    "admin.reports.audit.readonly",
    "admin.reports.usage.readonly",
)
CLASSROOM_SCOPES = _scopes(
    "classroom.courses.readonly",
    "classroom.rosters.readonly",
    "classroom.coursework.students.readonly",
)
AUDIT_SCOPE = _AUTH + "admin.reports.audit.readonly"
LICENSING_SCOPE = _AUTH + "apps.licensing"
DRIVE_SCOPE = _AUTH + "drive.readonly"
VAULT_SCOPE = _AUTH + "ediscovery.readonly"
ALERTS_SCOPE = _AUTH + "apps.alerts"
CHROME_SCOPE = _AUTH + "chrome.management.reports.readonly"
BIGQUERY_SCOPE = _AUTH + "bigquery.readonly"
GMAIL_SEND_SCOPE = _AUTH + "gmail.send"

# Optional scopes the connection check reports on (missing = feature off, not an error).
OPTIONAL_SCOPES: dict[str, str] = {
    LICENSING_SCOPE: "plan detection (License Manager API)",
    DRIVE_SCOPE: "shared drives list (metadata only)",
    VAULT_SCOPE: "legal hold status (Vault)",
    ALERTS_SCOPE: "Google security alerts (Alert Center)",
    CHROME_SCOPE: "Chrome insights",
}

# Read-only endpoints that happen to use POST.
_READ_ONLY_POST_PREFIXES = ("https://bigquery.googleapis.com/bigquery/v2/projects/",)
_RATE_LIMIT_REASONS = {"rateLimitExceeded", "userRateLimitExceeded", "quotaExceeded"}
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class ReadOnlyViolation(RuntimeError):
    """Raised if code tries to send a write request to Google."""


@dataclass(frozen=True)
class GoogleAuth:
    """Which key to use and whom to impersonate."""

    sa_json: str  # the service-account key file contents
    admin: str
    customer_id: str = "my_customer"

    @property
    def client_email(self) -> str:
        return str(json.loads(self.sa_json).get("client_email", ""))

    @property
    def client_id(self) -> str:
        return str(json.loads(self.sa_json).get("client_id", ""))


_current_auth: contextvars.ContextVar[GoogleAuth | None] = contextvars.ContextVar(
    "google_auth", default=None
)


def env_auth() -> GoogleAuth:
    s = get_settings()
    if not s.google_admin_impersonate:
        raise RuntimeError("GOOGLE_ADMIN_IMPERSONATE is not set")
    sa_json = s.google_service_account_json.read_text(encoding="utf-8")
    return GoogleAuth(sa_json, s.google_admin_impersonate, s.google_customer_id)


def use_auth(auth: GoogleAuth | None) -> contextvars.Token[GoogleAuth | None]:
    """Make `auth` the credential for Google calls in this context."""
    return _current_auth.set(auth)


def reset_auth(token: contextvars.Token[GoogleAuth | None]) -> None:
    _current_auth.reset(token)


def current_auth() -> GoogleAuth:
    return _current_auth.get() or env_auth()


def configured_scopes() -> tuple[str, ...]:
    """Core scopes Org+ requests, given the current feature flags."""
    if get_settings().enable_classroom:
        return CORE_SCOPES + CLASSROOM_SCOPES
    return CORE_SCOPES


def credentials(
    scopes: Sequence[str] | None = None,
    subject: str | None = None,
    auth: GoogleAuth | None = None,
    *,
    delegated: bool = True,
) -> service_account.Credentials:
    """Credentials for the service account, impersonating the admin by default.

    With domain-wide delegation the token request fails outright if *any*
    requested scope is not authorised in the Admin console, so each caller asks
    only for the scopes its API needs. `delegated=False` uses the service
    account itself (BigQuery access is granted through IAM, not delegation).
    """
    auth = auth or current_auth()
    info = json.loads(auth.sa_json)
    base = service_account.Credentials.from_service_account_info(info)
    scoped = base.with_scopes(list(scopes or configured_scopes()))
    if not delegated:
        return cast(service_account.Credentials, scoped)
    return cast(service_account.Credentials, scoped.with_subject(subject or auth.admin))


_local = threading.local()


def service(
    api: str,
    version: str,
    scopes: Sequence[str] | None = None,
    *,
    delegated: bool = True,
) -> Resource:
    """A cached googleapiclient service object for this thread and credential."""
    auth = current_auth()
    key = (api, version, tuple(scopes or configured_scopes()), auth, delegated)
    cache: dict[Any, Resource] = _local.__dict__.setdefault("services", {})
    if key not in cache:
        log.debug("building %s %s service", api, version)
        creds = credentials(key[2], auth=auth, delegated=delegated)
        cache[key] = build(api, version, credentials=creds, cache_discovery=False)
    return cache[key]


def directory(scopes: Sequence[str] | None = None) -> Resource:
    return service("admin", "directory_v1", scopes or CORE_SCOPES)


def reports(scopes: Sequence[str] | None = None) -> Resource:
    return service("admin", "reports_v1", scopes or CORE_SCOPES)


def classroom() -> Resource:
    return service("classroom", "v1", CLASSROOM_SCOPES)


def licensing() -> Resource:
    return service("licensing", "v1", [LICENSING_SCOPE])


def drive() -> Resource:
    return service("drive", "v3", [DRIVE_SCOPE])


def vault() -> Resource:
    return service("vault", "v1", [VAULT_SCOPE])


def alertcenter() -> Resource:
    return service("alertcenter", "v1beta1", [ALERTS_SCOPE])


def chromemanagement() -> Resource:
    return service("chromemanagement", "v1", [CHROME_SCOPE])


def bigquery() -> Resource:
    return service("bigquery", "v2", [BIGQUERY_SCOPE], delegated=False)


def error_reasons(err: HttpError) -> set[str]:
    try:
        details = err.error_details or []
    except AttributeError:
        return set()
    if not isinstance(details, list):
        return set()
    return {d.get("reason", "") for d in details if isinstance(d, dict)}


def _is_retryable(err: HttpError) -> bool:
    status = err.resp.status
    if status in _RETRYABLE_STATUS:
        return True
    return status == 403 and bool(error_reasons(err) & _RATE_LIMIT_REASONS)


def _check_read_only(request: HttpRequest, allow_send: bool) -> None:
    method = request.method.upper()
    if method == "GET":
        return
    path = request.uri.split("?")[0]
    is_bq_query = path.startswith(_READ_ONLY_POST_PREFIXES) and path.endswith(("/queries", "/jobs"))
    if method == "POST" and is_bq_query:
        return
    if allow_send and method == "POST" and path.endswith("/gmail/v1/users/me/messages/send"):
        return
    raise ReadOnlyViolation(f"refusing {method} {request.uri}: Org+ is read-only")


def execute(
    request: HttpRequest,
    *,
    max_attempts: int = 7,
    what: str = "",
    allow_send: bool = False,
) -> dict[str, Any]:
    """Run a request with exponential backoff (plus jitter) on 429/5xx/rate-limit 403s."""
    _check_read_only(request, allow_send)
    label = what or request.uri.split("?")[0]
    for attempt in range(1, max_attempts + 1):
        try:
            result: dict[str, Any] = request.execute(num_retries=0)
            return result
        except HttpError as err:
            if not _is_retryable(err):
                raise
            status = err.resp.status
            if status in (403, 429):
                log.warning("quota/rate limit on %s (HTTP %s, attempt %d)", label, status, attempt)
            if attempt == max_attempts:
                log.error("giving up on %s after %d attempts (HTTP %s)", label, attempt, status)
                raise
            delay = min(64.0, 2.0**attempt) + random.uniform(0, 1)
            log.info("retrying %s in %.1fs (HTTP %s)", label, delay, status)
            time.sleep(delay)
    raise AssertionError("unreachable")


def paginate(
    method: Callable[..., HttpRequest], items_key: str, *, what: str = "", **params: Any
) -> Iterator[dict[str, Any]]:
    """Yield every item across all pages of a list call."""
    page_token: str | None = None
    while True:
        if page_token:
            params["pageToken"] = page_token
        response = execute(method(**params), what=what)
        yield from response.get(items_key, [])
        page_token = response.get("nextPageToken")
        if not page_token:
            return
