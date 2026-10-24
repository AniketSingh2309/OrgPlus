"""Demo data for trying the dashboard before connecting Google: `python -m orgpulse.demo`.

Fills the default tenant with fictional people and ~180 days of activity.
`--clear` removes everything for the tenant again (do this before a real sync).
"""

from __future__ import annotations

import argparse
import random
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text

from orgpulse.db import session_scope
from orgpulse.logging_setup import setup_logging
from orgpulse.models import (
    AppToken,
    DailyUsage,
    Device,
    Event,
    Group,
    GroupMember,
    LicenceAssignment,
    OrgUnit,
    SharedDrive,
    TenantCapability,
    TenantPlan,
    User,
)
from orgpulse.sync.upsert import insert_ignore, upsert
from orgpulse.tenancy import default_tenant_id

FIRST = [
    "Aarav",
    "Aditi",
    "Ananya",
    "Arjun",
    "Diya",
    "Ishaan",
    "Kabir",
    "Kavya",
    "Meera",
    "Neha",
    "Nikhil",
    "Priya",
    "Rahul",
    "Riya",
    "Rohan",
    "Saanvi",
    "Sahil",
    "Sanya",
    "Shreya",
    "Tanvi",
    "Varun",
    "Vihaan",
    "Zara",
    "Dev",
    "Ira",
    "Kiran",
    "Maya",
    "Om",
    "Pooja",
    "Raj",
    "Sneha",
    "Tara",
    "Uday",
    "Veda",
    "Yash",
    "Aisha",
    "Farhan",
    "Gauri",
    "Harsh",
    "Jaya",
]
LAST = [
    "Sharma",
    "Verma",
    "Iyer",
    "Nair",
    "Reddy",
    "Gupta",
    "Mehta",
    "Kapoor",
    "Singh",
    "Rao",
    "Das",
    "Joshi",
    "Bose",
    "Menon",
    "Pillai",
    "Shah",
    "Khan",
    "Chopra",
    "Malhotra",
    "Saxena",
]
DEPTS = {
    "Engineering": ["Software Engineer", "Senior Engineer", "Engineering Manager", "QA Engineer"],
    "Sales": ["Account Executive", "Sales Manager", "SDR"],
    "Marketing": ["Marketing Lead", "Content Writer", "Designer"],
    "Finance": ["Accountant", "Finance Manager"],
    "People": ["HR Partner", "Recruiter"],
    "Operations": ["Ops Analyst", "Office Manager"],
}
APPS = [
    (
        "Slack",
        [
            "https://www.googleapis.com/auth/calendar.readonly",
            "https://www.googleapis.com/auth/userinfo.email",
        ],
        False,
    ),
    (
        "Zoom",
        [
            "https://www.googleapis.com/auth/calendar",
            "https://www.googleapis.com/auth/userinfo.email",
        ],
        False,
    ),
    (
        "Notion",
        [
            "https://www.googleapis.com/auth/drive.readonly",
            "https://www.googleapis.com/auth/userinfo.email",
        ],
        False,
    ),
    ("PDF Merger Pro", ["https://www.googleapis.com/auth/drive"], True),
    ("Mail Tracker", ["https://www.googleapis.com/auth/gmail.readonly"], False),
    ("Canva", ["https://www.googleapis.com/auth/drive.file"], False),
    ("Calendly", ["https://www.googleapis.com/auth/calendar"], False),
]
DOC_TYPES = ["document", "spreadsheet", "presentation", "pdf", "folder"]
DOC_WORDS = [
    "Q3",
    "Plan",
    "Budget",
    "Roadmap",
    "Hiring",
    "Notes",
    "Proposal",
    "Pitch",
    "Report",
    "Invoice",
    "Contract",
    "Design",
    "Sprint",
    "Review",
    "OKRs",
    "Forecast",
    "Brief",
    "Policy",
]
CITIES = [
    ("IN", "Bengaluru", 12.97, 77.59),
    ("IN", "Mumbai", 19.08, 72.88),
    ("IN", "Delhi", 28.61, 77.21),
    ("IN", "Pune", 18.52, 73.86),
]
FOREIGN = [
    ("SG", "Singapore", 1.35, 103.82),
    ("AE", "Dubai", 25.20, 55.27),
    ("US", "San Jose", 37.34, -121.89),
    ("NG", "Lagos", 6.52, 3.38),
]


# Everything the demo writes (credentials and settings are left alone).
DEMO_TABLES = (
    "events", "daily_usage", "app_tokens", "devices", "group_members", "groups", "users",
    "org_units", "licence_assignments", "shared_drives", "module_data", "tenant_capabilities",
    "tenant_plan", "capability_changes", "sync_state", "audit_views",
)  # fmt: skip


def clear(tenant_id: uuid.UUID) -> None:
    with session_scope() as s:
        for table in DEMO_TABLES:
            s.execute(text(f"DELETE FROM {table} WHERE tenant_id = :t"), {"t": tenant_id})
    print("cleared tenant data")


def seed(tenant_id: uuid.UUID, domain: str, n_users: int = 42, days: int = 180) -> None:
    rnd = random.Random(42)
    now = datetime.now(UTC)
    today = now.date()

    ous = [
        {
            "id": "id:root",
            "tenant_id": tenant_id,
            "name": domain,
            "path": "/",
            "parent_path": None,
            "description": None,
        }
    ]
    ous += [
        {
            "id": f"id:{d.lower()}",
            "tenant_id": tenant_id,
            "name": d,
            "path": f"/{d}",
            "parent_path": "/",
            "description": None,
        }
        for d in DEPTS
    ]

    users: list[dict[str, Any]] = []
    names = rnd.sample([(f, la) for f in FIRST for la in LAST], n_users)
    managers: dict[str, str] = {}
    for i, (first, last) in enumerate(names):
        dept = list(DEPTS)[i % len(DEPTS)]
        title = DEPTS[dept][0 if i < len(DEPTS) else rnd.randrange(len(DEPTS[dept]))]
        email = f"{first}.{last}@{domain}".lower()
        if i < len(DEPTS):
            managers[dept] = email
            title = f"Head of {dept}"
        created = (
            now - timedelta(days=rnd.randint(200, 1500))
            if i < n_users - 3
            else now - timedelta(days=rnd.randint(3, 20))
        )
        suspended = i in (n_users - 4,)
        inactive = i in (n_users - 5, n_users - 6)
        last_login = (
            None
            if suspended
            else (
                now - timedelta(days=rnd.randint(35, 80))
                if inactive
                else now - timedelta(hours=rnd.randint(1, 60))
            )
        )
        users.append(
            {
                "id": str(100000000000000000000 + i),
                "tenant_id": tenant_id,
                "primary_email": email,
                "full_name": f"{first} {last}",
                "given_name": first,
                "family_name": last,
                "org_unit_path": f"/{dept}",
                "department": dept,
                "title": title,
                "manager_email": None if i < len(DEPTS) else managers[dept],
                "is_admin": i == 0,
                "is_delegated_admin": i == 1,
                "admin_role": "Super Admin" if i == 0 else ("Help Desk Admin" if i == 1 else None),
                "suspended": suspended,
                "suspension_reason": "ADMIN" if suspended else None,
                "archived": False,
                "is_enrolled_in_2sv": rnd.random() > 0.18 or i == 0,
                "is_enforced_in_2sv": False,
                "creation_time": created,
                "last_login_time": last_login,
                "thumbnail_photo_url": None,
                "aliases": [],
                "raw": {"demo": True},
                "_inactive": inactive or suspended,
                "_level": rnd.choice([0.4, 0.7, 1.0, 1.0, 1.3, 1.8]),
            }
        )
    users[0]["manager_email"] = None
    for u in users[1 : len(DEPTS)]:
        u["manager_email"] = users[0]["primary_email"]

    # Daily usage
    usage: list[dict[str, Any]] = []
    for u in users:
        start = max(today - timedelta(days=days), u["creation_time"].date())
        d = start
        while d <= today - timedelta(days=3):
            weekend = d.weekday() >= 5
            if u["_inactive"] and d > today - timedelta(days=40):
                d += timedelta(days=1)
                continue
            if rnd.random() < (0.12 if weekend else 0.9):
                lvl = u["_level"] * (0.3 if weekend else 1)
                vals = {
                    "dc": rnd.randint(0, 4) * lvl,
                    "de": rnd.randint(0, 15) * lvl,
                    "dv": rnd.randint(0, 30) * lvl,
                    "es": rnd.randint(0, 25) * lvl,
                    "er": rnd.randint(5, 80) * lvl,
                    "mt": rnd.randint(0, 6) * lvl,
                    "mm": rnd.randint(0, 240) * lvl,
                    "ch": rnd.randint(0, 60) * lvl,
                    "cal": rnd.randint(0, 3) * lvl,
                }
                vals["mh"] = vals["mm"] / 60
                for m, v in vals.items():
                    if v:
                        usage.append(
                            {
                                "tenant_id": tenant_id,
                                "user_id": u["id"],
                                "date": d,
                                "metric": m,
                                "user_email": u["primary_email"],
                                "value": round(v),
                            }
                        )
            if d.weekday() == 0 or d == today - timedelta(days=3):
                used = 2000 + int(u["_level"] * 9000) + (today - d).days * -20
                usage += [
                    {
                        "tenant_id": tenant_id,
                        "user_id": u["id"],
                        "date": d,
                        "metric": "st_used",
                        "user_email": u["primary_email"],
                        "value": max(used, 300),
                    },
                    {
                        "tenant_id": tenant_id,
                        "user_id": u["id"],
                        "date": d,
                        "metric": "st_total",
                        "user_email": u["primary_email"],
                        "value": 30720 if u["_level"] < 1.5 else 15360,
                    },
                    {
                        "tenant_id": tenant_id,
                        "user_id": u["id"],
                        "date": d,
                        "metric": "st_drive",
                        "user_email": u["primary_email"],
                        "value": max(used, 300) * 0.6,
                    },
                    {
                        "tenant_id": tenant_id,
                        "user_id": u["id"],
                        "date": d,
                        "metric": "st_gmail",
                        "user_email": u["primary_email"],
                        "value": max(used, 300) * 0.4,
                    },
                ]
            d += timedelta(days=1)

    # Events
    events: list[dict[str, Any]] = []
    seq = 0

    def ev(app: str, name: str, u: dict[str, Any], when: datetime, **kw: Any) -> None:
        nonlocal seq
        seq += 1
        params = kw.pop("params", {})
        events.append(
            {
                "tenant_id": tenant_id,
                "app": app,
                "time": when,
                "unique_qualifier": str(seq),
                "event_seq": 0,
                "event_name": name,
                "event_type": kw.pop("event_type", None),
                "user_email": u["primary_email"],
                "user_id": u["id"],
                "ip": kw.pop("ip", f"49.36.{rnd.randint(0, 255)}.{rnd.randint(1, 254)}"),
                "doc_id": kw.pop("doc_id", None),
                "doc_title": kw.pop("doc_title", None),
                "doc_type": kw.pop("doc_type", None),
                "visibility": kw.pop("visibility", None),
                "is_external": kw.pop("is_external", None),
                "country": kw.pop("country", None),
                "city": kw.pop("city", None),
                "lat": kw.pop("lat", None),
                "lon": kw.pop("lon", None),
                "params": params,
            }
        )

    for u in users:
        if u["suspended"]:
            continue
        home = CITIES[int(u["id"]) % len(CITIES)]
        for day_back in range(0, 60 if not u["_inactive"] else 0):
            d = now - timedelta(days=day_back)
            if d.weekday() >= 5 and rnd.random() > 0.15:
                continue
            hour = rnd.choice([8, 9, 9, 10, 10, 11, 14, 20, 22])
            t0 = d.replace(hour=max(hour - 5, 0), minute=rnd.randint(0, 59))  # UTC ~ IST - 5:30
            c, city, lat, lon = home
            ev(
                "login",
                "login_success",
                u,
                t0,
                country=c,
                city=city,
                lat=lat,
                lon=lon,
                event_type="login",
                params={"login_type": "google_password", "is_suspicious": False},
            )
            for _ in range(rnd.randint(0, 5)):
                title = f"{rnd.choice(DOC_WORDS)} {rnd.choice(DOC_WORDS)}"
                ext = rnd.random() < 0.03
                ev(
                    "drive",
                    rnd.choice(
                        ["edit", "view", "view", "create", "download"]
                        + (["change_user_access"] if ext else [])
                    ),
                    u,
                    t0 + timedelta(minutes=rnd.randint(5, 500)),
                    doc_id=f"doc{rnd.randint(1, 900)}",
                    doc_title=title,
                    doc_type=rnd.choice(DOC_TYPES),
                    visibility="shared_externally"
                    if ext
                    else rnd.choice(["private", "shared_internally"]),
                    is_external=ext,
                    params={
                        "owner": u["primary_email"],
                        **(
                            {
                                "target_user": f"partner@{rnd.choice(['acme.io', 'globex.com', 'gmail.com'])}"
                            }
                            if ext
                            else {}
                        ),
                    },
                )
            if rnd.random() < 0.6:
                ev(
                    "meet",
                    "call_ended",
                    u,
                    t0 + timedelta(hours=rnd.randint(1, 6)),
                    params={
                        "duration_seconds": rnd.randint(600, 4200),
                        "meeting_code": f"abc-{rnd.randint(1000, 9999)}",
                        "organizer_email": u["primary_email"]
                        if rnd.random() < 0.3
                        else users[0]["primary_email"],
                        "device_type": rnd.choice(["web", "android", "ios"]),
                        "is_external": rnd.random() < 0.1,
                    },
                )
            if rnd.random() < 0.2:
                ev(
                    "saml",
                    "login_success",
                    u,
                    t0 + timedelta(minutes=3),
                    params={"application_name": rnd.choice(["Salesforce", "Jira", "Zoho People"])},
                )
        # Some failures / foreign sign-ins
        if rnd.random() < 0.12:
            for k in range(rnd.randint(3, 5)):
                ev(
                    "login",
                    "login_failure",
                    u,
                    now - timedelta(days=rnd.randint(0, 6), minutes=k * 7),
                    params={"login_type": "google_password"},
                )
        if rnd.random() < 0.06:
            c, city, lat, lon = rnd.choice(FOREIGN)
            ev(
                "login",
                "suspicious_login" if rnd.random() < 0.5 else "login_success",
                u,
                now - timedelta(days=rnd.randint(0, 5)),
                country=c,
                city=city,
                lat=lat,
                lon=lon,
                params={"login_type": "google_password", "is_suspicious": True},
            )
    admin = users[0]
    for k, (name, target) in enumerate(
        [
            ("CREATE_USER", users[-1]["primary_email"]),
            ("SUSPEND_USER", users[-4]["primary_email"]),
            ("CHANGE_PASSWORD", users[5]["primary_email"]),
            ("ADD_GROUP_MEMBER", users[9]["primary_email"]),
            ("CHANGE_APPLICATION_SETTING", None),
        ]
    ):
        ev(
            "admin",
            name,
            admin,
            now - timedelta(days=k * 2, hours=k),
            event_type="USER_SETTINGS",
            params={"USER_EMAIL": target}
            if target
            else {"SETTING_NAME": "Drive sharing outside domain", "NEW_VALUE": "WARN"},
        )

    # Directory odds and ends
    groups: list[dict[str, Any]] = [
        {
            "id": f"g{i}",
            "tenant_id": tenant_id,
            "email": f"{n}@{domain}",
            "name": n.title(),
            "description": None,
            "direct_members_count": c,
            "admin_created": True,
            "raw": {},
        }
        for i, (n, c) in enumerate(
            [
                ("all", n_users),
                ("engineering", 7),
                ("sales", 7),
                ("leadership", 6),
                ("old-project", 0),
                ("partners", 3),
            ]
        )
    ]
    members = [
        {
            "group_id": "g0",
            "member_id": u["id"],
            "tenant_id": tenant_id,
            "email": u["primary_email"],
            "role": "OWNER" if u is admin else "MEMBER",
            "type": "USER",
            "status": "ACTIVE",
        }
        for u in users
    ]
    members += [
        {
            "group_id": "g1",
            "member_id": u["id"],
            "tenant_id": tenant_id,
            "email": u["primary_email"],
            "role": "MEMBER",
            "type": "USER",
            "status": "ACTIVE",
        }
        for u in users
        if u["department"] == "Engineering"
    ]
    members += [
        {
            "group_id": "g3",
            "member_id": u["id"],
            "tenant_id": tenant_id,
            "email": u["primary_email"],
            "role": "OWNER" if u is admin else "MEMBER",
            "type": "USER",
            "status": "ACTIVE",
        }
        for u in users[: len(DEPTS)]
    ]
    members += [
        {
            "group_id": "g5",
            "member_id": f"ext{i}",
            "tenant_id": tenant_id,
            "email": e,
            "role": "MEMBER",
            "type": "USER",
            "status": "ACTIVE",
        }
        for i, e in enumerate(["vendor@acme.io", "consultant@gmail.com", users[3]["primary_email"]])
    ]

    devices, tokens, licences = [], [], []
    for i, u in enumerate(users):
        if rnd.random() < 0.7:
            devices.append(
                {
                    "kind": "mobile",
                    "id": f"m{i}",
                    "tenant_id": tenant_id,
                    "user_email": u["primary_email"],
                    "model": rnd.choice(["Pixel 8", "iPhone 15", "Galaxy S23", "OnePlus 12"]),
                    "os": rnd.choice(["Android 14", "iOS 17.5"]),
                    "os_version": None,
                    "status": rnd.choice(["APPROVED"] * 6 + ["PENDING"]),
                    "device_type": rnd.choice(["ANDROID", "IOS_SYNC"]),
                    "serial_number": None,
                    "first_sync": now - timedelta(days=300),
                    "last_sync": now - timedelta(days=rnd.choice([0, 1, 2, 45])),
                    "raw": {
                        "deviceCompromisedStatus": "Compromise detected"
                        if i == 7
                        else "No compromise detected",
                        "encryptionStatus": "Encrypted",
                    },
                }
            )
        if i % 6 == 0:
            devices.append(
                {
                    "kind": "chromeos",
                    "id": f"c{i}",
                    "tenant_id": tenant_id,
                    "user_email": u["primary_email"],
                    "model": "Acer Chromebook 514",
                    "os": "ChromeOS",
                    "os_version": "126.0.6478",
                    "status": "ACTIVE",
                    "device_type": "CHROMEBOOK",
                    "serial_number": f"SN{i:05d}",
                    "first_sync": None,
                    "last_sync": now - timedelta(days=rnd.randint(0, 10)),
                    "raw": {},
                }
            )
        for name, scopes, anon in rnd.sample(APPS, rnd.randint(1, 3)):
            from orgpulse.risk import app_risk

            tokens.append(
                {
                    "user_id": u["id"],
                    "client_id": f"{name.lower().replace(' ', '-')}.apps.googleusercontent.com",
                    "tenant_id": tenant_id,
                    "user_email": u["primary_email"],
                    "display_text": name,
                    "scopes": scopes,
                    "anonymous": anon,
                    "native_app": False,
                    "risk": app_risk(scopes, unverified=anon)[0],
                    "raw": {},
                }
            )
        licences.append(
            {
                "tenant_id": tenant_id,
                "user_email": u["primary_email"],
                "sku_id": "1010020028",
                "product_id": "Google-Apps",
                "sku_name": "Google Workspace Business Standard",
            }
        )

    for u in users[:20]:
        for _ in range(rnd.randint(0, 6)):
            when = now - timedelta(days=rnd.randint(0, 80))
            ev(
                "gemini_in_workspace_apps",
                "feature_utilization",
                u,
                when,
                params={"app_name": rnd.choice(["docs", "gmail", "sheets", "meet"])},
            )

    drives = [
        {
            "id": f"sd{i}",
            "tenant_id": tenant_id,
            "name": n,
            "created_time": now - timedelta(days=200),
            "hidden": False,
            "member_count": m,
            "external_member_count": x,
            "members": {
                "items": [
                    {"emailAddress": admin["primary_email"], "role": "organizer", "type": "user"}
                ]
            },
            "restrictions": {},
        }
        for i, (n, m, x) in enumerate(
            [
                ("Company", 42, 0),
                ("Sales Collateral", 9, 2),
                ("Design Assets", 6, 1),
                ("Finance", 4, 0),
            ]
        )
    ]

    with session_scope() as s:
        upsert(s, OrgUnit, ous, ["id"])
        upsert(
            s, User, [{k: v for k, v in u.items() if not k.startswith("_")} for u in users], ["id"]
        )
        upsert(s, Group, groups, ["id"])
        upsert(s, GroupMember, members, ["group_id", "member_id"])
        upsert(s, Device, devices, ["kind", "id"])
        upsert(s, AppToken, tokens, ["user_id", "client_id"])
        upsert(s, LicenceAssignment, licences, ["tenant_id", "user_email", "sku_id"])
        upsert(s, SharedDrive, drives, ["id"])
        upsert(
            s, DailyUsage, usage, ["tenant_id", "user_id", "date", "metric"], touch_synced_at=False
        )
        insert_ignore(s, Event, events)
        s.merge(
            TenantPlan(
                tenant_id=tenant_id,
                edition="Business Standard",
                tier="free",
                sku_breakdown={
                    "1010020028": {
                        "edition": "Business Standard",
                        "tier": "free",
                        "count": n_users,
                        "known": True,
                    }
                },
                licences_total=48,
                licences_assigned=n_users,
                licensing_error=None,
                detected_at=now,
            )
        )
        for key, status, detail in [
            ("bigquery_logs", "not_configured", "no BigQuery project/dataset given"),
            ("gmail_logs", "locked", "HTTP 403: not available for this customer"),
            ("vault", "locked", "HTTP 403: not available for this customer"),
            ("alert_center", "locked", "HTTP 403: not available for this customer"),
            ("dlp_events", "locked", "HTTP 400: not available for this customer"),
            ("context_aware_access", "locked", "HTTP 400: not available for this customer"),
            ("gemini_usage", "on", "demo"),
            ("classroom", "not_configured", "ENABLE_CLASSROOM=false"),
            ("chrome_mgmt", "locked", "HTTP 403"),
        ]:
            s.merge(
                TenantCapability(
                    tenant_id=tenant_id, key=key, status=status, detail=detail, detected_at=now
                )
            )
        for key in ("directory", "usage", "events:login", "events:drive", "plan"):
            s.execute(
                text("""INSERT INTO sync_state (tenant_id, key, status, last_run_at, last_success_at, cursor_time, detail)
                        VALUES (:t, :k, 'ok', :n, :n, :n, '{"demo": true}') ON CONFLICT (tenant_id, key) DO UPDATE
                        SET status = 'ok', last_success_at = :n"""),
                {"t": tenant_id, "k": key, "n": now},
            )
    print(f"seeded demo data: {len(users)} people, {len(usage)} usage rows, {len(events)} events")


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m orgpulse.demo")
    parser.add_argument("--clear", action="store_true", help="remove all data for the tenant")
    args = parser.parse_args()
    setup_logging("WARNING")
    tid = default_tenant_id()
    from orgpulse.config import get_settings

    clear(tid)
    if not args.clear:
        seed(tid, get_settings().allowed_domain)


if __name__ == "__main__":
    main()
