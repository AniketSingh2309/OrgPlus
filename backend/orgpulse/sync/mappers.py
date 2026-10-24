"""Pure functions: Google API JSON -> row dicts. No I/O, so they are easy to test."""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Iterable
from datetime import UTC, date, datetime
from typing import Any

from orgpulse.risk import app_risk

log = logging.getLogger(__name__)

Row = dict[str, Any]

# Our metric -> candidate usage-report parameter names, first match wins.
# Check against the live API: unseen names are logged by UsageMapper.report_missing().
USAGE_PARAMS: dict[str, tuple[str, ...]] = {
    "dc": ("drive:num_items_created",),
    "de": ("drive:num_items_edited",),
    "dv": ("drive:num_items_viewed",),
    "es": ("gmail:num_emails_sent",),
    "er": ("gmail:num_emails_received",),
    "mt": ("meet:num_calls",),
    "mm": ("meet:total_call_minutes",),
    "ch": ("chat:num_messages_posted", "chat:num_messages_sent", "chat:num_messages"),
    "cal": ("calendar:num_events_created", "calendar:num_created_events"),
    # Storage (not part of the activity score).
    "st_used": ("accounts:used_quota_in_mb",),
    "st_total": ("accounts:total_quota_in_mb",),
    "st_drive": ("accounts:drive_used_quota_in_mb",),
    "st_gmail": ("accounts:gmail_used_quota_in_mb",),
}
# Metrics derived from others: mh = meeting hours.
DERIVED = {"mh": ("mm", 1 / 60)}

SCORE_METRICS = ("dc", "de", "dv", "es", "er", "mt", "mh", "ch", "cal")
APP_METRICS: dict[str, tuple[str, ...]] = {
    "drive": ("dc", "de", "dv"),
    "gmail": ("es", "er"),
    "meet": ("mt", "mh"),
    "chat": ("ch",),
    "calendar": ("cal",),
}

# Drive visibility values that mean "reachable outside the domain".
EXTERNAL_VISIBILITY = {"shared_externally", "public_on_the_web", "people_with_link"}


# Personal data Google returns that Org+ never uses: never stored (data minimisation).
SENSITIVE_USER_FIELDS = frozenset(
    {
        "recoveryEmail", "recoveryPhone", "phones", "addresses", "sshPublicKeys",
        "posixAccounts", "ims", "customSchemas", "notes", "gender", "keywords",
        "websites", "locations", "languages", "externalIds", "emails",
    }
)  # fmt: skip
SENSITIVE_DEVICE_FIELDS = frozenset(
    {
        "imei", "meid", "wifiMacAddress", "bluetoothMacAddress", "ethernetMacAddress",
        "ethernetMacAddress0", "macAddress", "networkOperator", "otherAccountsInfo",
        "applications", "lastKnownNetwork", "cpuStatusReports", "diskVolumeReports",
        "recentUsers", "activeTimeRanges", "deviceFiles", "systemRamFreeReports",
    }
)  # fmt: skip


def _minimal(raw: dict[str, Any], drop: frozenset[str]) -> dict[str, Any]:
    return {k: v for k, v in raw.items() if k not in drop}


def parse_time(value: str | None) -> datetime | None:
    """RFC 3339 -> aware datetime. Google uses 1970-01-01 for "never"."""
    if not value or value.startswith("1970-01-01"):
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _primary(items: list[dict[str, Any]] | None) -> dict[str, Any]:
    if not items:
        return {}
    return next((i for i in items if i.get("primary")), items[0])


def map_user(raw: dict[str, Any], tenant_id: Any) -> Row:
    org = _primary(raw.get("organizations"))
    manager = next(
        (r.get("value") for r in raw.get("relations") or [] if r.get("type") == "manager"), None
    )
    name = raw.get("name") or {}
    return {
        "id": raw["id"],
        "tenant_id": tenant_id,
        "primary_email": raw["primaryEmail"].lower(),
        "full_name": name.get("fullName"),
        "given_name": name.get("givenName"),
        "family_name": name.get("familyName"),
        "org_unit_path": raw.get("orgUnitPath"),
        "department": org.get("department"),
        "title": org.get("title"),
        "manager_email": manager.lower() if isinstance(manager, str) else None,
        "is_admin": bool(raw.get("isAdmin")),
        "is_delegated_admin": bool(raw.get("isDelegatedAdmin")),
        "suspended": bool(raw.get("suspended")),
        "suspension_reason": raw.get("suspensionReason"),
        "archived": bool(raw.get("archived")),
        "is_enrolled_in_2sv": bool(raw.get("isEnrolledIn2Sv")),
        "is_enforced_in_2sv": bool(raw.get("isEnforcedIn2Sv")),
        "creation_time": parse_time(raw.get("creationTime")),
        "last_login_time": parse_time(raw.get("lastLoginTime")),
        "thumbnail_photo_url": raw.get("thumbnailPhotoUrl"),
        "aliases": [a.lower() for a in raw.get("aliases") or []],
        "raw": _minimal(raw, SENSITIVE_USER_FIELDS),
    }


def map_org_unit(raw: dict[str, Any], tenant_id: Any) -> Row:
    return {
        "id": raw["orgUnitId"],
        "tenant_id": tenant_id,
        "name": raw.get("name") or raw["orgUnitPath"],
        "path": raw["orgUnitPath"],
        "parent_path": raw.get("parentOrgUnitPath"),
        "description": raw.get("description"),
    }


def map_group(raw: dict[str, Any], tenant_id: Any) -> Row:
    count = raw.get("directMembersCount")
    return {
        "id": raw["id"],
        "tenant_id": tenant_id,
        "email": raw["email"].lower(),
        "name": raw.get("name"),
        "description": raw.get("description"),
        "direct_members_count": int(count) if count is not None else None,
        "admin_created": bool(raw.get("adminCreated")),
        "raw": raw,
    }


def map_member(raw: dict[str, Any], group_id: str, tenant_id: Any) -> Row:
    email = raw.get("email")
    return {
        "group_id": group_id,
        "member_id": raw.get("id") or email,
        "tenant_id": tenant_id,
        "email": email.lower() if email else None,
        "role": raw.get("role"),
        "type": raw.get("type"),
        "status": raw.get("status"),
    }


def admin_roles_by_user(
    assignments: Iterable[dict[str, Any]], roles: Iterable[dict[str, Any]]
) -> dict[str, str]:
    """user id -> comma-separated role names."""
    names = {str(r["roleId"]): r.get("roleName", str(r["roleId"])) for r in roles}
    by_user: dict[str, set[str]] = {}
    for a in assignments:
        if a.get("assigneeType", "user") != "user":
            continue
        role = names.get(str(a.get("roleId")), str(a.get("roleId")))
        by_user.setdefault(str(a["assignedTo"]), set()).add(role)
    return {uid: ", ".join(sorted(r)) for uid, r in by_user.items()}


def map_mobile_device(raw: dict[str, Any], tenant_id: Any) -> Row:
    emails = raw.get("email") or []
    return {
        "kind": "mobile",
        "id": raw["resourceId"],
        "tenant_id": tenant_id,
        "user_email": emails[0].lower() if emails else None,
        "model": raw.get("model"),
        "os": raw.get("os") or raw.get("type"),
        "os_version": raw.get("os"),
        "status": raw.get("status"),
        "device_type": raw.get("type"),
        "serial_number": raw.get("serialNumber"),
        "first_sync": parse_time(raw.get("firstSync")),
        "last_sync": parse_time(raw.get("lastSync")),
        "raw": _minimal(raw, SENSITIVE_DEVICE_FIELDS),
    }


def map_chromeos_device(raw: dict[str, Any], tenant_id: Any) -> Row:
    user = raw.get("annotatedUser")
    if not user:
        recent = raw.get("recentUsers") or []
        user = next((u.get("email") for u in recent if u.get("email")), None)
    return {
        "kind": "chromeos",
        "id": raw["deviceId"],
        "tenant_id": tenant_id,
        "user_email": user.lower() if user else None,
        "model": raw.get("model"),
        "os": "ChromeOS",
        "os_version": raw.get("osVersion"),
        "status": raw.get("status"),
        "device_type": "CHROMEBOOK",
        "serial_number": raw.get("serialNumber"),
        "first_sync": None,
        "last_sync": parse_time(raw.get("lastSync")),
        "raw": _minimal(raw, SENSITIVE_DEVICE_FIELDS),
    }


def map_token(raw: dict[str, Any], user_id: str, user_email: str, tenant_id: Any) -> Row:
    scopes = list(raw.get("scopes") or [])
    # tokens.list has no "verified" flag; anonymous = not registered with Google.
    unverified = bool(raw.get("anonymous"))
    risk, _ = app_risk(scopes, unverified=unverified)
    return {
        "user_id": user_id,
        "client_id": raw["clientId"],
        "tenant_id": tenant_id,
        "user_email": user_email,
        "display_text": raw.get("displayText"),
        "scopes": scopes,
        "anonymous": unverified,
        "native_app": bool(raw.get("nativeApp")),
        "risk": risk,
        "raw": raw,
    }


# --- Usage reports --------------------------------------------------------------------


def _param_value(p: dict[str, Any]) -> float | None:
    if "intValue" in p:
        return float(p["intValue"])
    if "boolValue" in p:
        return 1.0 if p["boolValue"] else 0.0
    return None


class UsageMapper:
    """Maps userUsageReport entries and remembers which parameters were never seen."""

    def __init__(self) -> None:
        self.reports = 0
        self.metric_hits: Counter[str] = Counter()
        self.params_seen: set[str] = set()

    def map_report(self, report: dict[str, Any], tenant_id: Any) -> list[Row]:
        entity = report.get("entity") or {}
        user_id = entity.get("profileId")
        if not user_id:
            return []
        day = date.fromisoformat(report["date"])
        params = {p["name"]: p for p in report.get("parameters") or []}
        self.reports += 1
        self.params_seen.update(params)

        values: dict[str, float] = {}
        for metric, candidates in USAGE_PARAMS.items():
            for name in candidates:
                if name in params:
                    v = _param_value(params[name])
                    if v is not None:
                        values[metric] = v
                        self.metric_hits[metric] += 1
                    break
        for metric, (source, factor) in DERIVED.items():
            if source in values:
                values[metric] = values[source] * factor

        email = entity.get("userEmail")
        return [
            {
                "tenant_id": tenant_id,
                "user_id": user_id,
                "date": day,
                "metric": m,
                "user_email": email.lower() if email else None,
                "value": v,
            }
            for m, v in values.items()
        ]

    def missing_metrics(self) -> dict[str, list[str]]:
        """metric -> similar parameter names actually seen (to fix the mapping)."""
        if not self.reports:
            return {}
        out: dict[str, list[str]] = {}
        for metric, candidates in USAGE_PARAMS.items():
            if self.metric_hits[metric] == 0:
                prefix = candidates[0].split(":")[0] + ":"
                out[metric] = sorted(p for p in self.params_seen if p.startswith(prefix))[:15]
        return out

    def report_missing(self) -> dict[str, list[str]]:
        missing = self.missing_metrics()
        for metric, similar in missing.items():
            log.warning(
                "usage metric %r: none of %s present in %d reports; similar params seen: %s",
                metric,
                list(USAGE_PARAMS[metric]),
                self.reports,
                similar or "none",
            )
        return missing


# --- Activities ------------------------------------------------------------------------


def flatten_params(params: Iterable[dict[str, Any]] | None) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for p in params or []:
        name = p.get("name")
        if not name:
            continue
        if "value" in p:
            out[name] = p["value"]
        elif "intValue" in p:
            out[name] = int(p["intValue"])
        elif "boolValue" in p:
            out[name] = bool(p["boolValue"])
        elif "multiValue" in p:
            out[name] = list(p["multiValue"])
        elif "multiIntValue" in p:
            out[name] = [int(v) for v in p["multiIntValue"]]
        elif "messageValue" in p:
            out[name] = flatten_params(p["messageValue"].get("parameter"))
        elif "multiMessageValue" in p:
            out[name] = [flatten_params(m.get("parameter")) for m in p["multiMessageValue"]]
    return out


def _is_external(app: str, params: dict[str, Any], own_domains: set[str]) -> bool | None:
    if app == "drive":
        if params.get("visibility") in EXTERNAL_VISIBILITY:
            return True
        target = params.get("target_user") or params.get("target_domain")
        if isinstance(target, str) and target:
            domain = target.split("@")[-1].lower()
            if own_domains and domain not in own_domains and domain != "all":
                return True
        return False if "visibility" in params else None
    if "is_external" in params:
        return bool(params["is_external"])
    return None


def map_activity(
    item: dict[str, Any], app: str, tenant_id: Any, own_domains: set[str]
) -> list[Row]:
    ident = item.get("id") or {}
    when = parse_time(ident.get("time"))
    if when is None:
        return []
    actor = item.get("actor") or {}
    email = actor.get("email")
    network = item.get("networkInfo") or {}
    rows: list[Row] = []
    for seq, ev in enumerate(item.get("events") or []):
        params = flatten_params(ev.get("parameters"))
        rows.append(
            {
                "tenant_id": tenant_id,
                "app": app,
                "time": when,
                "unique_qualifier": str(ident.get("uniqueQualifier", "")),
                "event_seq": seq,
                "event_name": ev.get("name", ""),
                "event_type": ev.get("type"),
                "user_email": email.lower() if email else None,
                "user_id": actor.get("profileId"),
                "ip": item.get("ipAddress"),
                "doc_id": params.get("doc_id"),
                "doc_title": params.get("doc_title"),
                "doc_type": params.get("doc_type"),
                "visibility": params.get("visibility"),
                "is_external": _is_external(app, params, own_domains),
                "country": network.get("regionCode") or params.get("location_country"),
                "city": None,
                "lat": None,
                "lon": None,
                "params": params,
            }
        )
    return rows


# --- Licensing -------------------------------------------------------------------------


def map_licence(raw: dict[str, Any], tenant_id: Any) -> Row:
    return {
        "tenant_id": tenant_id,
        "user_email": str(raw.get("userId", "")).lower(),
        "sku_id": str(raw.get("skuId")),
        "product_id": str(raw.get("productId")),
        "sku_name": raw.get("skuName"),
    }
