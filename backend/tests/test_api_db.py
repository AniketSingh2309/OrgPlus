"""API against a real Postgres (demo data). Runs only when TEST_DATABASE_URL is set,
e.g. TEST_DATABASE_URL=postgresql://orgpulse:orgpulse@localhost:5432/orgpulse_test
(the database must be migrated: `alembic upgrade head`). It is wiped and re-seeded."""

from __future__ import annotations

import os
import time
from collections.abc import Iterator

import jwt
import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not set"
)

SECRET = os.environ["NEXTAUTH_SECRET"]


def token(email: str) -> dict[str, str]:
    claims = {"email": email, "name": email, "aud": "orgpulse-api", "exp": int(time.time()) + 300}
    return {"Authorization": "Bearer " + jwt.encode(claims, SECRET, algorithm="HS256")}


@pytest.fixture(scope="module")
def client() -> Iterator[object]:
    os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]
    os.environ["ORG_ADMINS"] = "head@example.com"
    from orgpulse.config import get_settings
    from orgpulse.db import _session_factory, get_engine
    from orgpulse.tenancy import default_tenant_id

    # Drop anything cached against another database before we start wiping data.
    for cached in (get_settings, get_engine, _session_factory, default_tenant_id):
        cached.cache_clear()

    from sqlalchemy import text

    from orgpulse.db import session_scope

    with session_scope() as s:
        if s.execute(text("SELECT 1 FROM tenant_credentials LIMIT 1")).first():
            pytest.exit(
                "TEST_DATABASE_URL has a connected Workspace; refusing to wipe it", returncode=2
            )
        # Disposable database: start from nothing, whatever earlier runs left behind.
        s.execute(text("TRUNCATE tenants CASCADE"))

    from fastapi.testclient import TestClient

    from orgpulse import demo
    from orgpulse.api.main import app

    tid = default_tenant_id()
    demo.seed(tid, "example.com")
    with TestClient(app) as c:
        yield c


def test_admin_sees_everything(client) -> None:  # type: ignore[no-untyped-def]
    r = client.get("/api/people", headers=token("head@example.com"))
    assert r.status_code == 200 and r.json()["total"] == 42
    assert client.get("/api/apps", headers=token("head@example.com")).status_code == 200


def test_other_domain_rejected(client) -> None:  # type: ignore[no-untyped-def]
    assert client.get("/api/people", headers=token("x@gmail.com")).status_code == 403
    assert client.get("/api/people").status_code == 401


def test_manager_view_is_scoped(client) -> None:  # type: ignore[no-untyped-def]
    everyone = client.get("/api/people", headers=token("head@example.com")).json()["people"]
    # A department head (has reports, not a super admin) gets the manager view.
    heads = [
        p
        for p in everyone
        if p["title"] and p["title"].startswith("Head of") and not p["admin_role"]
    ]
    head = heads[0]
    mine = client.get("/api/people", headers=token(head["email"])).json()["people"]
    assert 1 < len(mine) < len(everyone)
    assert all(p["department"] == head["department"] for p in mine)
    outsider = next(p for p in everyone if p["department"] != head["department"])
    assert (
        client.get(f"/api/people/{outsider['id']}", headers=token(head["email"])).status_code == 404
    )
    assert client.get("/api/apps", headers=token(head["email"])).status_code == 403


def test_individual_without_reports_is_refused(client) -> None:  # type: ignore[no-untyped-def]
    everyone = client.get("/api/people", headers=token("head@example.com")).json()["people"]
    ic = next(p for p in everyone if p["title"] in ("Software Engineer", "Accountant", "Recruiter"))
    assert client.get("/api/people", headers=token(ic["email"])).status_code == 403


def test_profile_view_is_audited(client) -> None:  # type: ignore[no-untyped-def]
    from sqlalchemy import text

    from orgpulse.db import session_scope

    pid = client.get("/api/people", headers=token("head@example.com")).json()["people"][0]["id"]
    with session_scope() as s:
        before = s.execute(text("SELECT COUNT(*) FROM audit_views")).scalar_one()
    assert client.get(f"/api/people/{pid}", headers=token("head@example.com")).status_code == 200
    with session_scope() as s:
        after = s.execute(
            text("SELECT COUNT(*) FROM audit_views WHERE viewer = 'head@example.com'")
        ).scalar_one()
    assert after == before + 1


def test_locked_module_returns_402(client) -> None:  # type: ignore[no-untyped-def]
    r = client.get("/api/m/vault", headers=token("head@example.com"))
    assert r.status_code == 402 and "Business Plus" in r.json()["detail"]["requires"]


def test_csv_export(client) -> None:  # type: ignore[no-untyped-def]
    r = client.get("/api/export/people.csv", headers=token("head@example.com"))
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert r.text.lstrip("﻿").startswith("id,name,email")


def test_meet_chat_calendar_derived_from_events(client) -> None:  # type: ignore[no-untyped-def]
    """Domains whose usage report lacks meet:/chat:/calendar: get them from activity events."""
    from sqlalchemy import text

    from orgpulse.db import session_scope
    from orgpulse.sync import event_metrics, state
    from orgpulse.tenancy import default_tenant_id

    tid = default_tenant_id()
    with session_scope() as s:
        s.execute(text("DELETE FROM daily_usage WHERE metric IN ('mt','mm','mh','ch','cal')"))
    state.update_detail(
        tid, "usage", {"missing_metrics": {"mt": [], "mm": [], "ch": [], "cal": []}}
    )

    result = event_metrics.derive(tid)
    assert set(result["metrics"]) == {"mt", "mm", "mh", "ch", "cal"}
    with session_scope() as s:
        mt, mm, mh, calls, secs = s.execute(
            text(
                """SELECT (SELECT SUM(value) FROM daily_usage WHERE metric = 'mt'),
                          (SELECT SUM(value) FROM daily_usage WHERE metric = 'mm'),
                          (SELECT SUM(value) FROM daily_usage WHERE metric = 'mh'),
                          (SELECT COUNT(*) FROM events WHERE app = 'meet' AND event_name = 'call_ended'
                             AND user_email IN (SELECT primary_email FROM users)),
                          (SELECT SUM((params->>'duration_seconds')::numeric) FROM events
                             WHERE app = 'meet' AND event_name = 'call_ended'
                             AND user_email IN (SELECT primary_email FROM users))"""
            )
        ).one()
    assert mt == calls > 0
    assert mm == pytest.approx(float(secs) / 60)
    assert mh == pytest.approx(float(secs) / 3600)

    # A second run recomputes in place (idempotent), it doesn't double count.
    event_metrics.derive(tid, days=180)
    with session_scope() as s:
        assert (
            s.execute(text("SELECT SUM(value) FROM daily_usage WHERE metric = 'mt'")).scalar_one()
            == mt
        )

    # Once the usage report supplies a metric, it is no longer derived.
    state.update_detail(tid, "usage", {"missing_metrics": {"ch": []}})
    assert event_metrics.metrics_to_derive(tid) == ["ch"]


def test_dead_running_job_is_marked_interrupted(client) -> None:  # type: ignore[no-untyped-def]
    """A job left "running" by a killed process is detected (its advisory lock is free)."""
    from sqlalchemy import text

    from orgpulse.db import get_engine
    from orgpulse.sync import state
    from orgpulse.tenancy import default_tenant_id

    tid = default_tenant_id()
    state.mark_running(tid, "usage")  # as if the process died mid-run
    with get_engine().connect() as live:  # a job that really is running holds its lock
        lock = state._lock_id(tid, "events:login")
        live.execute(text("SELECT pg_advisory_lock(:k)"), {"k": lock})
        state.mark_running(tid, "events:login")
        try:
            assert state.reconcile_stale(tid) == ["usage"]
            assert state.get_state(tid, "usage").status == "interrupted"
            assert state.get_state(tid, "events:login").status == "running"
        finally:
            live.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": lock})
            live.commit()
    status = client.get("/api/sync/status", headers=token("head@example.com")).json()
    assert "events:login" not in status["running"]  # lock released: reconciled on read


def test_app_adoption_never_exceeds_100_percent(client) -> None:  # type: ignore[no-untyped-def]
    """Receive-only Gmail users count as active, so no app's share can pass 100%."""
    from datetime import timedelta

    from sqlalchemy import text

    from orgpulse.db import session_scope
    from orgpulse.queries import scored_window
    from orgpulse.tenancy import default_tenant_id

    tid = default_tenant_id()
    day = scored_window(30)[1] - timedelta(days=1)
    with session_scope() as s:  # someone whose only activity is receiving email (weight 0)
        uid = s.execute(
            text("SELECT id FROM users WHERE tenant_id = :t AND suspended LIMIT 1"), {"t": tid}
        ).scalar_one()
        s.execute(text("DELETE FROM daily_usage WHERE user_id = :u"), {"u": uid})
        s.execute(
            text("INSERT INTO daily_usage VALUES (:t, :u, :d, 'er', NULL, 12)"),
            {"t": tid, "u": uid, "d": day},
        )
    body = client.get("/api/overview", headers=token("head@example.com")).json()
    shares = {a["app"]: a for a in body["app_adoption"]}
    assert all(0 <= a["pct"] <= 100 for a in shares.values())
    assert shares["gmail"]["users"] <= body["kpis"]["active_30d"]


GEOIP_FILE = (
    __import__("pathlib").Path(__file__).resolve().parents[2] / "data" / "dbip-city-lite.mmdb"
)


@pytest.mark.skipif(not GEOIP_FILE.is_file(), reason="run python -m orgpulse.geoip_update first")
def test_existing_events_get_located(client, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from datetime import UTC, datetime

    from sqlalchemy import text

    from orgpulse import geo
    from orgpulse.config import get_settings
    from orgpulse.db import session_scope
    from orgpulse.tenancy import default_tenant_id

    monkeypatch.setattr(get_settings(), "geoip_db", GEOIP_FILE)
    tid = default_tenant_id()
    with session_scope() as s:
        s.execute(
            text(
                """INSERT INTO events (tenant_id, app, time, unique_qualifier, event_seq, event_name,
                                      user_email, ip, params)
                   VALUES (:t, 'login', :now, 'geo-test', 0, 'login_success', 'x@example.com',
                           '8.8.8.8', '{}')"""
            ),
            {"t": tid, "now": datetime.now(UTC)},
        )
    assert geo.enrich_existing(tid) >= 1
    with session_scope() as s:
        row = s.execute(
            text("SELECT country, city, lat, lon FROM events WHERE unique_qualifier = 'geo-test'")
        ).one()
    assert row.country == "US" and row.lat is not None and row.lon is not None
    assert geo.enrich_existing(tid) == 0  # nothing left to locate: idempotent


def test_profile_photos_follow_viewer_scope(client) -> None:  # type: ignore[no-untyped-def]
    from sqlalchemy import text

    from orgpulse.db import session_scope

    everyone = client.get("/api/people", headers=token("head@example.com")).json()["people"]
    head = next(
        p for p in everyone if p["title"] and p["title"].startswith("Head of") and not p["roles"]
    )
    outsider = next(p for p in everyone if p["department"] != head["department"])
    with session_scope() as s:
        s.execute(
            text(
                "UPDATE users SET thumbnail_photo_url = 'https://lh3.example/' || id WHERE primary_email IN (:a, :b)"
            ),
            {"a": head["email"], "b": outsider["email"]},
        )
    admin_view = client.get("/api/people/photos", headers=token("head@example.com")).json()
    assert set(admin_view) >= {head["email"], outsider["email"]}
    manager_view = client.get("/api/people/photos", headers=token(head["email"])).json()
    assert head["email"] in manager_view and outsider["email"] not in manager_view


def test_meeting_load_ignores_unattributed_calls(client) -> None:  # type: ignore[no-untyped-def]
    """External/anonymous joiners (no actor email) are nobody's meeting load."""
    from datetime import UTC, datetime

    from sqlalchemy import text

    from orgpulse.db import session_scope
    from orgpulse.tenancy import default_tenant_id

    with session_scope() as s:
        s.execute(
            text(
                """INSERT INTO events (tenant_id, app, time, unique_qualifier, event_seq, event_name, params)
                   VALUES (:t, 'meet', :now, 'anon-call', 0, 'call_ended', '{"duration_seconds": 3600}')"""
            ),
            {"t": default_tenant_id(), "now": datetime.now(UTC)},
        )
    people = client.get("/api/insights/meetings", headers=token("head@example.com")).json()[
        "people"
    ]
    assert people and all(p["email"] for p in people)


def test_teams_fall_back_to_org_unit_and_list_members(client) -> None:  # type: ignore[no-untyped-def]
    from sqlalchemy import text

    from orgpulse.db import session_scope

    with session_scope() as s:  # someone with no department, in a nested OU
        uid = s.execute(text("SELECT id FROM users WHERE NOT suspended LIMIT 1")).scalar_one()
        s.execute(
            text("UPDATE users SET department = NULL, org_unit_path = '/Field/Pune' WHERE id = :u"),
            {"u": uid},
        )
    body = client.get("/api/insights/teams", headers=token("head@example.com")).json()
    pune = next(t for t in body["teams"] if t["department"] == "Pune")
    assert [m["id"] for m in pune["members"]] == [uid]
    assert pune["after_hours_pct"] is None  # a team of 1 stays hidden
    big = max(body["teams"], key=lambda t: t["users"])
    assert big["users"] == len(big["members"]) >= 3
    for key in (
        "meet_hours_per_week",
        "external_shares_30d",
        "storage_gb",
        "inactive_30d",
        "admins",
        "no_2sv",
    ):
        assert key in big


def test_groups_lists_every_group_with_members_and_issues(client) -> None:  # type: ignore[no-untyped-def]
    body = client.get("/api/insights/groups", headers=token("head@example.com")).json()
    assert body["total"] == len(body["groups"]) == 6
    by_email = {g["email"]: g for g in body["groups"]}
    partners = by_email["partners@example.com"]
    assert "external" in partners["issues"] and partners["external"] == 2
    assert "empty" in by_email["old-project@example.com"]["issues"]
    assert (
        by_email["all@example.com"]["owners"] == 1 and by_email["all@example.com"]["members"] == 42
    )
    assert all("member_list" in g for g in body["groups"])


def test_after_hours_classifies_by_local_time_per_team(client) -> None:  # type: ignore[no-untyped-def]
    """Events at known local (IST) times land in the right buckets for a 3-person team."""
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import text

    from orgpulse.db import session_scope
    from orgpulse.tenancy import default_tenant_id

    tid = default_tenant_id()
    ist = timedelta(hours=5, minutes=30)
    # A Monday at least a week ago, so all events fall inside the last 30 days.
    today = datetime.now(UTC).date()
    monday = today - timedelta(days=today.weekday() + 7)

    def at(day_offset: int, hour: int) -> datetime:  # local IST wall time -> UTC
        return (
            datetime(monday.year, monday.month, monday.day, hour, tzinfo=UTC)
            + timedelta(days=day_offset)
            - ist
        )

    with session_scope() as s:
        trio = (
            s.execute(
                text(
                    "SELECT primary_email FROM users WHERE NOT suspended ORDER BY primary_email LIMIT 3"
                )
            )
            .scalars()
            .all()
        )
        s.execute(
            text(
                "UPDATE users SET department = NULL, org_unit_path = '/Night Shift' WHERE primary_email = ANY(:e)"
            ),
            {"e": list(trio)},
        )
        s.execute(text("DELETE FROM events WHERE user_email = ANY(:e)"), {"e": list(trio)})
        for n, (when, who) in enumerate(
            [
                (at(0, 12), trio[0]),  # Mon 12:00 -> inside hours
                (at(1, 23), trio[1]),  # Tue 23:00 -> after hours + late night
                (at(2, 7), trio[2]),  # Wed 07:00 -> after hours (early start)
                (at(5, 10), trio[0]),  # Sat 10:00 -> weekend
            ]
        ):
            s.execute(
                text(
                    """INSERT INTO events (tenant_id, app, time, unique_qualifier, event_seq, event_name, user_email, params)
                       VALUES (:t, 'drive', :w, :q, 0, 'edit', :u, '{}')"""
                ),
                {"t": tid, "w": when, "q": f"ah-{n}", "u": who},
            )
    body = client.get("/api/insights/after-hours", headers=token("head@example.com")).json()
    team = next(t for t in body["teams"] if t["team"] == "Night Shift")
    assert team["people"] == 3 and team["events"] == 4
    assert team["after_hours_pct"] == 50.0  # Tue 23:00 + Wed 07:00
    assert team["weekend_pct"] == 25.0  # Sat
    assert team["outside_pct"] == 75.0
    assert team["late_night_pct"] == 25.0  # Tue 23:00
    assert team["early_pct"] == 25.0  # Wed 07:00
    assert team["people_outside"] == 3
    assert {a["app"] for a in team["by_app"]} == {"drive"}
    assert all(len(t) for t in body["teams"]) and all(h["people"] < 3 for h in body["hidden_teams"])


def test_live_reactions_update_people_immediately(client, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """New events update each person straight away: sign-in, calls, app grants, directory."""
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import text

    from orgpulse.db import session_scope
    from orgpulse.sync import directory, reactions, state
    from orgpulse.tenancy import default_tenant_id

    tid = default_tenant_id()
    token_refresh: list[set[str]] = []
    directory_refresh: list[str] = []
    monkeypatch.setattr(
        directory, "sync_tokens_for", lambda t, emails: token_refresh.append(emails) or 1
    )
    monkeypatch.setattr(directory, "sync_users", lambda t: directory_refresh.append("users") or 0)
    monkeypatch.setattr(directory, "sync_admin_roles", lambda t: 0)
    monkeypatch.setattr(directory, "sync_groups", lambda t: 0)
    state.update_detail(
        tid, "usage", {"missing_metrics": {"mt": [], "mm": [], "ch": [], "cal": []}}
    )

    now = datetime.now(UTC).replace(microsecond=0)
    with session_scope() as s:
        email, uid = s.execute(
            text("SELECT primary_email, id FROM users WHERE NOT suspended ORDER BY id LIMIT 1")
        ).one()
        s.execute(
            text("UPDATE users SET last_login_time = :old WHERE id = :u"),
            {"old": now - timedelta(days=9), "u": uid},
        )
        s.execute(text("DELETE FROM daily_usage WHERE user_id = :u AND metric = 'mt'"), {"u": uid})
    before = reactions.max_event_id(tid)
    with session_scope() as s:
        for n, (app, name, params) in enumerate(
            [
                ("login", "login_success", "{}"),
                ("meet", "call_ended", '{"duration_seconds": 1800}'),
                ("token", "authorize", '{"client_id": "x.apps.googleusercontent.com"}'),
                ("admin", "CHANGE_USER_ORGANIZATION", "{}"),
            ]
        ):
            s.execute(
                text(
                    """INSERT INTO events (tenant_id, app, time, unique_qualifier, event_seq, event_name, user_email, params)
                       VALUES (:t, :app, :w, :q, 0, :name, :u, CAST(:p AS jsonb))"""
                ),
                {
                    "t": tid,
                    "app": app,
                    "w": now,
                    "q": f"live-{n}",
                    "name": name,
                    "u": email,
                    "p": params,
                },
            )
    done = reactions.apply(tid, before)

    with session_scope() as s:
        last = s.execute(
            text("SELECT last_login_time FROM users WHERE id = :u"), {"u": uid}
        ).scalar_one()
        calls = s.execute(
            text("SELECT SUM(value) FROM daily_usage WHERE user_id = :u AND metric = 'mt'"),
            {"u": uid},
        ).scalar_one()
    assert last == now and done["last_sign_in"] == 1  # sign-in shown immediately
    assert calls and calls >= 1  # the call counts toward Meet calls straight away
    assert token_refresh == [{email}]  # only that person's app grants refreshed
    assert directory_refresh == ["users"]  # admin change -> directory refresh
    assert reactions.apply(tid, reactions.max_event_id(tid)) == {}  # nothing new -> nothing to do


def test_quiet_live_checks_only_announce_new_data(client, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from orgpulse.sync import state
    from orgpulse.tenancy import default_tenant_id

    sent: list[dict[str, object]] = []
    monkeypatch.setattr(state, "publish", lambda t, event, **p: sent.append({"event": event, **p}))
    tid = default_tenant_id()
    with state.job(tid, "events:quiet-test", quiet=True):
        state.mark_ok(tid, "events:quiet-test", detail={"last_batch": 0}, quiet=True)
    assert sent == []  # a check that found nothing stays silent
    with state.job(tid, "events:quiet-test", quiet=True):
        state.mark_ok(tid, "events:quiet-test", detail={"last_batch": 3})
    assert [m for m in sent if m.get("changed") == 3]  # new data is announced


def test_insert_ignore_counts_only_new_rows(client) -> None:  # type: ignore[no-untyped-def]
    from datetime import UTC, datetime

    from orgpulse.db import session_scope
    from orgpulse.models import Event
    from orgpulse.sync.upsert import insert_ignore
    from orgpulse.tenancy import default_tenant_id

    row = {
        "tenant_id": default_tenant_id(), "app": "login", "time": datetime.now(UTC),
        "unique_qualifier": "dup-check", "event_seq": 0, "event_name": "login_success", "params": {},
    }  # fmt: skip
    with session_scope() as s:
        assert insert_ignore(s, Event, [row]) == 1
    with session_scope() as s:
        assert insert_ignore(s, Event, [row]) == 0  # already stored: nothing new to announce


def test_timeline_describes_and_groups_repeats(client) -> None:  # type: ignore[no-untyped-def]
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import text

    from orgpulse.db import session_scope
    from orgpulse.tenancy import default_tenant_id

    tid = default_tenant_id()
    with session_scope() as s:
        email, uid = s.execute(
            text("SELECT primary_email, id FROM users WHERE NOT suspended ORDER BY id DESC LIMIT 1")
        ).one()
        s.execute(text("DELETE FROM events WHERE user_email = :e"), {"e": email})
        base = datetime.now(UTC).replace(hour=8, minute=0, second=0, microsecond=0) - timedelta(
            days=1
        )
        gemini = '{"app_name": "gmail", "action": "summarize_proactive"}'
        for n, (app, name, params, minutes) in enumerate(
            [
                ("gemini_in_workspace_apps", "feature_utilization", gemini, 0),
                ("gemini_in_workspace_apps", "feature_utilization", gemini, 5),
                ("gemini_in_workspace_apps", "feature_utilization", gemini, 10),
                ("login", "login_success", "{}", 20),
            ]
        ):
            s.execute(
                text(
                    """INSERT INTO events (tenant_id, app, time, unique_qualifier, event_seq, event_name, user_email, params)
                       VALUES (:t, :app, :w, :q, 0, :name, :u, CAST(:p AS jsonb))"""
                ),
                {
                    "t": tid,
                    "app": app,
                    "w": base + timedelta(minutes=minutes),
                    "q": f"tl-{n}",
                    "name": name,
                    "u": email,
                    "p": params,
                },
            )
    body = client.get(f"/api/people/{uid}/timeline", headers=token("head@example.com")).json()
    items = body["days"][0]["items"]
    assert [(i["app_label"], i["text"], i["count"]) for i in items] == [
        ("Sign-in", "Signed in", 1),
        ("Gemini", "Gemini summarised an email in Gmail", 3),  # three in a row -> one line
    ]
    assert items[1]["first"] < items[1]["time"]  # time range of the grouped run
    assert {a["label"]: a["count"] for a in body["apps"]} == {"Gemini": 3, "Sign-in": 1}
    only = client.get(
        f"/api/people/{uid}/timeline?app=login", headers=token("head@example.com")
    ).json()
    assert [i["app"] for d in only["days"] for i in d["items"]] == ["login"]
