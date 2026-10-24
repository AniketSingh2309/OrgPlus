"""Paid modules backed by their own APIs: Vault (legal hold), Alert Center, Chrome management."""

from __future__ import annotations

import uuid
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import Depends
from googleapiclient.errors import HttpError

from orgpulse import google_client as g
from orgpulse.api.deps import Viewer, get_viewer
from orgpulse.features.registry import FeatureModule, UiCard, register
from orgpulse.modules._common import gated_router, load_snapshot_map, load_snapshots, save_snapshots

# --- Vault: legal hold status (no content) ---------------------------------------------

vault = gated_router("vault")


def sync_vault(tenant_id: uuid.UUID) -> int:
    items: list[tuple[str, dict[str, Any]]] = []
    for matter in g.paginate(
        g.vault().matters().list, "matters", what="matters.list", pageSize=100, view="BASIC"
    ):
        holds: list[dict[str, Any]] = []
        if matter.get("state") == "OPEN":
            try:
                holds = list(
                    g.paginate(
                        g.vault().matters().holds().list,
                        "holds",
                        what="holds.list",
                        matterId=matter["matterId"],
                        pageSize=100,
                        view="BASIC_HOLD",
                    )
                )
            except HttpError as err:
                if err.resp.status != 403:
                    raise
        items.append(
            (
                matter["matterId"],
                {
                    "matter_id": matter["matterId"],
                    "name": matter.get("name"),
                    "state": matter.get("state"),
                    "holds": [
                        {
                            "name": h.get("name"),
                            "corpus": h.get("corpus"),
                            "accounts": [
                                a.get("email") for a in h.get("accounts") or [] if a.get("email")
                            ],
                            "org_unit": (h.get("orgUnit") or {}).get("orgUnitId"),
                            "updated": h.get("updateTime"),
                        }
                        for h in holds
                    ],
                },
            )
        )
    return save_snapshots(tenant_id, "vault", items)


@vault.get("")
def vault_summary(viewer: Viewer = Depends(get_viewer)) -> dict[str, Any]:
    matters = load_snapshots(viewer.tenant_id, "vault")
    on_hold: dict[str, list[str]] = {}
    ou_holds = []
    for m in matters:
        for h in m.get("holds", []):
            for email in h["accounts"]:
                on_hold.setdefault(email.lower(), []).append(
                    f"{m['name']} / {h['name']} ({h['corpus']})"
                )
            if h.get("org_unit"):
                ou_holds.append(
                    {
                        "matter": m["name"],
                        "hold": h["name"],
                        "org_unit": h["org_unit"],
                        "corpus": h["corpus"],
                    }
                )
    return {
        "open_matters": sum(1 for m in matters if m.get("state") == "OPEN"),
        "closed_matters": sum(1 for m in matters if m.get("state") == "CLOSED"),
        "users_on_hold": [{"email": e, "holds": hs} for e, hs in sorted(on_hold.items())],
        "org_unit_holds": ou_holds,
    }


register(
    FeatureModule(
        key="vault",
        title="Legal hold status",
        requires="Business Plus or above (Google Vault)",
        description="Users and accounts under legal hold and the open matters count. No content is read.",
        how_to_enable="https://support.google.com/vault/answer/2462365",
        page="/m/vault",
        router=vault,
        sync=sync_vault,
        schedule={"trigger": "interval", "hours": 24},
        cards=[
            UiCard("legal-hold", "Legal holds", "Who is under hold and how many matters are open.")
        ],
    )
)

# --- Alert Center ----------------------------------------------------------------------

alerts = gated_router("alert_center")


def sync_alert_center(tenant_id: uuid.UUID) -> int:
    since = (datetime.now(UTC) - timedelta(days=30)).isoformat().replace("+00:00", "Z")
    items = []
    for a in g.paginate(
        g.alertcenter().alerts().list,
        "alerts",
        what="alerts.list",
        pageSize=100,
        filter=f'createTime >= "{since}"',
        orderBy="createTime desc",
    ):
        data = a.get("data") or {}
        items.append(
            (
                a["alertId"],
                {
                    "alertId": a["alertId"],
                    "type": a.get("type"),
                    "source": a.get("source"),
                    "createTime": a.get("createTime"),
                    "startTime": a.get("startTime"),
                    "severity": (a.get("metadata") or {}).get("severity"),
                    "status": (a.get("metadata") or {}).get("status"),
                    "email": data.get("email") or (data.get("loginDetails") or {}).get("ipAddress"),
                },
            )
        )
    return save_snapshots(tenant_id, "alert_center", items)


@alerts.get("")
def alert_list(viewer: Viewer = Depends(get_viewer)) -> dict[str, Any]:
    items = sorted(
        load_snapshots(viewer.tenant_id, "alert_center"),
        key=lambda a: a.get("createTime") or "",
        reverse=True,
    )
    return {
        "alerts": items,
        "by_type": dict(Counter(a.get("type") or "Other" for a in items).most_common()),
    }


register(
    FeatureModule(
        key="alert_center",
        title="Google security alerts",
        requires="Business Plus or above (Alert Center)",
        description="Phishing, suspicious login and device compromised alerts, merged into Needs attention.",
        how_to_enable="https://support.google.com/a/answer/9104586",
        page="/m/alert_center",
        router=alerts,
        sync=sync_alert_center,
        schedule={"trigger": "interval", "hours": 1},
        cards=[
            UiCard(
                "gac-alerts",
                "Google alerts",
                "Alerts raised by Google's own detection in the last 30 days.",
            )
        ],
    )
)

# --- Chrome management -----------------------------------------------------------------

chrome = gated_router("chrome_mgmt")


def sync_chrome(tenant_id: uuid.UUID) -> int:
    customer = f"customers/{g.current_auth().customer_id}"
    reports = g.chromemanagement().customers().reports()
    versions = list(
        g.paginate(
            reports.countChromeVersions,
            "browserVersions",
            what="countChromeVersions",
            customer=customer,
            pageSize=100,
        )
    )
    apps = list(
        g.paginate(
            reports.countInstalledApps,
            "installedApps",
            what="countInstalledApps",
            customer=customer,
            pageSize=100,
            filter="app_type=EXTENSION",
            orderBy="total_install_count desc",
        )
    )
    return save_snapshots(
        tenant_id,
        "chrome_mgmt",
        [("versions", {"items": versions}), ("extensions", {"items": apps})],
    )


@chrome.get("")
def chrome_summary(viewer: Viewer = Depends(get_viewer)) -> dict[str, Any]:
    data = load_snapshot_map(viewer.tenant_id, "chrome_mgmt")
    versions = data.get("versions", {}).get("items", [])
    extensions = data.get("extensions", {}).get("items", [])
    majors = sorted(
        {
            int(str(v.get("version", "0")).split(".")[0])
            for v in versions
            if str(v.get("version", "")).split(".")[0].isdigit()
        }
    )
    latest = majors[-1] if majors else 0
    outdated = [
        v
        for v in versions
        if str(v.get("version", "0")).split(".")[0].isdigit()
        and int(str(v["version"]).split(".")[0]) < latest - 2
    ]
    risky_perms = {
        "<all_urls>",
        "tabs",
        "webRequest",
        "cookies",
        "history",
        "clipboardRead",
        "debugger",
        "proxy",
    }
    return {
        "versions": versions,
        "outdated_devices": sum(int(v.get("count", 0)) for v in outdated),
        "latest_major": latest,
        "extensions": [
            {
                "id": e.get("appId"),
                "name": e.get("displayName"),
                "installs": e.get("browserDeviceCount") or e.get("osUserCount"),
                "permissions": e.get("permissions") or [],
                "risky": bool(set(e.get("permissions") or []) & risky_perms),
                "install_type": e.get("appInstallType"),
            }
            for e in extensions
        ],
    }


register(
    FeatureModule(
        key="chrome_mgmt",
        title="Chrome insights",
        requires="Chrome Enterprise",
        description="Browser versions, outdated browsers and risky extensions.",
        how_to_enable="https://support.google.com/chrome/a/answer/9301891",
        page="/m/chrome_mgmt",
        router=chrome,
        sync=sync_chrome,
        schedule={"trigger": "interval", "hours": 24},
        cards=[
            UiCard(
                "chrome",
                "Chrome browsers",
                "Outdated browser versions and extensions with broad permissions.",
            )
        ],
    )
)
