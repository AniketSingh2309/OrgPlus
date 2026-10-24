from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

import pytest

from orgpulse.sync import mappers
from orgpulse.sync.extras import is_external_member

TENANT = "tenant-1"


def test_parse_time_treats_epoch_as_never() -> None:
    assert mappers.parse_time("1970-01-01T00:00:00.000Z") is None
    assert mappers.parse_time(None) is None
    assert mappers.parse_time("2026-10-19T08:12:45.000Z") == datetime(
        2026, 10, 19, 8, 12, 45, tzinfo=UTC
    )


def test_map_user_full(fixture: Any) -> None:
    raw = fixture("users_list.json")["users"][0]
    row = mappers.map_user(raw, TENANT)
    assert row["primary_email"] == "priya.sharma@example.com"  # lower-cased
    assert row["department"] == "Engineering"  # primary organization wins
    assert row["title"] == "Engineering Manager"
    assert row["manager_email"] == "cto@example.com"
    assert row["is_admin"] is True
    assert row["is_enrolled_in_2sv"] is True
    assert row["last_login_time"] == datetime(2026, 10, 19, 8, 12, 45, tzinfo=UTC)
    assert row["aliases"] == ["priya@example.com"]
    assert row["raw"]["primaryEmail"] == raw["primaryEmail"]  # everything Org+ uses is kept


def test_map_user_drops_personal_fields_org_plus_never_uses(fixture: Any) -> None:
    raw = {
        **fixture("users_list.json")["users"][0],
        "recoveryEmail": "me@gmail.com",
        "recoveryPhone": "+919999999999",
        "phones": [{"value": "+91 98 7654 3210"}],
        "addresses": [{"formatted": "12 MG Road"}],
        "sshPublicKeys": [{"key": "ssh-rsa AAA"}],
    }
    stored = mappers.map_user(raw, TENANT)["raw"]
    assert not (set(stored) & mappers.SENSITIVE_USER_FIELDS)
    assert stored["orgUnitPath"] == "/Engineering"


def test_map_device_drops_hardware_identifiers() -> None:
    raw = {
        "resourceId": "r1",
        "email": ["a@example.com"],
        "imei": "3567",
        "wifiMacAddress": "aa:bb",
        "deviceCompromisedStatus": "No compromise detected",
    }
    stored = mappers.map_mobile_device(raw, TENANT)["raw"]
    assert "imei" not in stored and "wifiMacAddress" not in stored
    assert stored["deviceCompromisedStatus"] == "No compromise detected"  # still used by Devices


def test_map_user_sparse_and_suspended(fixture: Any) -> None:
    row = mappers.map_user(fixture("users_list.json")["users"][1], TENANT)
    assert row["last_login_time"] is None
    assert row["suspended"] is True
    assert row["department"] is None
    assert row["manager_email"] is None


def test_admin_roles_by_user() -> None:
    roles = [
        {"roleId": "1", "roleName": "_SEED_ADMIN_ROLE"},
        {"roleId": "2", "roleName": "Help Desk Admin"},
    ]
    assignments = [
        {"roleId": "2", "assignedTo": "u1", "assigneeType": "user"},
        {"roleId": "1", "assignedTo": "u1"},
        {"roleId": "2", "assignedTo": "g1", "assigneeType": "group"},
    ]
    assert mappers.admin_roles_by_user(assignments, roles) == {
        "u1": "Help Desk Admin, _SEED_ADMIN_ROLE"
    }


def test_usage_mapping_with_fallback_and_missing(
    fixture: Any, caplog: pytest.LogCaptureFixture
) -> None:
    resp = fixture("usage_report.json")
    mapper = mappers.UsageMapper()
    rows = [r for rep in resp["usageReports"] for r in mapper.map_report(rep, TENANT)]
    values = {r["metric"]: r["value"] for r in rows}

    assert {r["user_id"] for r in rows} == {
        "103456789012345678901"
    }  # report without profileId skipped
    assert all(r["date"] == date(2026, 10, 17) for r in rows)
    assert values["dc"] == 3 and values["de"] == 12 and values["dv"] == 40
    assert values["es"] == 9 and values["er"] == 55
    assert values["mt"] == 4 and values["mm"] == 150
    assert values["mh"] == pytest.approx(2.5)  # derived: minutes / 60
    assert values["ch"] == 20  # second candidate name used
    assert values["st_used"] == 2048
    assert "cal" not in values

    missing = mapper.report_missing()
    assert "cal" in missing
    assert "calendar:num_meetings_organized" in missing["cal"]  # similar names offered
    assert "usage metric 'cal'" in caplog.text


def test_flatten_params_handles_every_value_type() -> None:
    params = [
        {"name": "a", "value": "x"},
        {"name": "b", "intValue": "7"},
        {"name": "c", "boolValue": True},
        {"name": "d", "multiValue": ["p", "q"]},
        {"name": "e", "multiIntValue": ["1", "2"]},
        {"name": "f", "messageValue": {"parameter": [{"name": "g", "value": "h"}]}},
        {"name": "i", "multiMessageValue": [{"parameter": [{"name": "j", "intValue": "3"}]}]},
    ]
    assert mappers.flatten_params(params) == {
        "a": "x", "b": 7, "c": True, "d": ["p", "q"], "e": [1, 2], "f": {"g": "h"}, "i": [{"j": 3}],
    }  # fmt: skip


def test_map_login_activity(fixture: Any) -> None:
    items = fixture("activities_login.json")["items"]
    rows = [
        r for item in items for r in mappers.map_activity(item, "login", TENANT, {"example.com"})
    ]
    assert len(rows) == 3  # second activity carries two events
    first = rows[0]
    assert first["event_name"] == "login_success"
    assert first["user_email"] == "priya.sharma@example.com"
    assert first["country"] == "IN"  # from networkInfo.regionCode
    assert first["params"]["login_challenge_method"] == ["password", "google_authenticator"]
    assert first["unique_qualifier"] == "-7012345678901234567"
    # Same activity -> same time/qualifier, distinct event_seq (the idempotency key).
    assert [(r["unique_qualifier"], r["event_seq"]) for r in rows[1:]] == [("42", 0), ("42", 1)]
    assert rows[2]["params"]["is_suspicious"] is True


def test_map_drive_activity_external_detection(fixture: Any) -> None:
    items = fixture("activities_drive.json")["items"]
    rows = [
        r for item in items for r in mappers.map_activity(item, "drive", TENANT, {"example.com"})
    ]
    share, edit, internal_share = rows
    assert share["doc_title"] == "Q3 Roadmap" and share["visibility"] == "shared_externally"
    assert share["is_external"] is True
    assert edit["is_external"] is False
    assert internal_share["is_external"] is None  # internal target, no visibility param


def test_map_tokens_risk(fixture: Any) -> None:
    rows = {
        r["display_text"]: r
        for r in (
            mappers.map_token(t, "u1", "u@example.com", TENANT)
            for t in fixture("tokens_list.json")["items"]
        )
    }
    assert rows["Slack"]["risk"] == "low"
    assert rows["PDF Merger"]["risk"] == "high"  # full drive
    assert rows["Mail Tracker"]["risk"] == "high"  # mail.google.com without trailing slash
    assert rows["Calendly"]["risk"] == "medium"  # full calendar, trailing slash
    assert rows["Unknown app"]["risk"] == "high" and rows["Unknown app"]["anonymous"] is True


def test_devices_mapping() -> None:
    mobile = mappers.map_mobile_device(
        {
            "resourceId": "r1",
            "email": ["A@Example.com"],
            "model": "Pixel 8",
            "os": "Android 14",
            "type": "ANDROID",
            "status": "APPROVED",
            "lastSync": "2026-10-01T00:00:00Z",
        },
        TENANT,
    )
    assert mobile["kind"] == "mobile" and mobile["user_email"] == "a@example.com"
    chrome = mappers.map_chromeos_device(
        {
            "deviceId": "d1",
            "recentUsers": [{"type": "USER_TYPE_MANAGED", "email": "b@example.com"}],
        },
        TENANT,
    )
    assert chrome["kind"] == "chromeos" and chrome["user_email"] == "b@example.com"


@pytest.mark.parametrize(
    ("perm", "external"),
    [
        ({"type": "anyone"}, True),
        ({"type": "domain", "domain": "example.com"}, False),
        ({"type": "domain", "domain": "partner.io"}, True),
        ({"type": "user", "emailAddress": "x@example.com"}, False),
        ({"type": "user", "emailAddress": "x@gmail.com"}, True),
        ({"type": "group", "emailAddress": "team@partner.io"}, True),
    ],
)
def test_shared_drive_external_members(perm: dict[str, Any], external: bool) -> None:
    assert is_external_member(perm, {"example.com"}) is external
