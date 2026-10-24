from __future__ import annotations

import json
from typing import Any

import httplib2
import pytest
from googleapiclient.errors import HttpError

from orgpulse import google_client as g
from orgpulse.risk import app_risk


class FakeRequest:
    def __init__(
        self,
        method: str = "GET",
        uri: str = "https://admin.googleapis.com/admin/directory/v1/users",
        outcomes: list[Any] | None = None,
    ) -> None:
        self.method = method
        self.uri = uri
        self.outcomes = list(outcomes or [{"ok": True}])
        self.calls = 0

    def execute(self, num_retries: int = 0) -> Any:
        self.calls += 1
        out = self.outcomes.pop(0)
        if isinstance(out, Exception):
            raise out
        return out


def _err(status: int, reason: str = "") -> HttpError:
    body = json.dumps(
        {"error": {"code": status, "message": "x", "errors": [{"reason": reason}]}}
    ).encode()
    return HttpError(httplib2.Response({"status": status}), body, uri="u")


@pytest.mark.parametrize(
    ("method", "uri"),
    [
        ("POST", "https://admin.googleapis.com/admin/directory/v1/users"),
        ("DELETE", "https://admin.googleapis.com/admin/directory/v1/users/x"),
        ("PUT", "https://admin.googleapis.com/admin/directory/v1/users/x"),
        ("PATCH", "https://admin.googleapis.com/admin/directory/v1/users/x"),
        (
            "POST",
            "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
        ),  # not allowed by default
        ("POST", "https://bigquery.googleapis.com/bigquery/v2/projects/p/datasets"),  # BQ write
    ],
)
def test_write_calls_are_refused(method: str, uri: str) -> None:
    req = FakeRequest(method, uri)
    with pytest.raises(g.ReadOnlyViolation):
        g.execute(req)  # type: ignore[arg-type]
    assert req.calls == 0


def test_allowed_read_only_posts() -> None:
    assert g.execute(
        FakeRequest("POST", "https://bigquery.googleapis.com/bigquery/v2/projects/p/queries")
    ) == {"ok": True}  # type: ignore[arg-type]
    send = FakeRequest(
        "POST", "https://gmail.googleapis.com/gmail/v1/users/me/messages/send?alt=json"
    )
    assert g.execute(send, allow_send=True) == {"ok": True}  # type: ignore[arg-type]


def test_backoff_on_429_and_rate_limit_403(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(g.time, "sleep", lambda s: None)
    req = FakeRequest(
        outcomes=[_err(429), _err(403, "userRateLimitExceeded"), _err(503), {"ok": 1}]
    )
    assert g.execute(req) == {"ok": 1}  # type: ignore[arg-type]
    assert req.calls == 4


def test_no_retry_on_plain_403(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(g.time, "sleep", lambda s: None)
    req = FakeRequest(outcomes=[_err(403, "forbidden")])
    with pytest.raises(HttpError):
        g.execute(req)  # type: ignore[arg-type]
    assert req.calls == 1


def test_gives_up_after_max_attempts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(g.time, "sleep", lambda s: None)
    req = FakeRequest(outcomes=[_err(500)] * 3)
    with pytest.raises(HttpError):
        g.execute(req, max_attempts=3)  # type: ignore[arg-type]
    assert req.calls == 3


def test_paginate_follows_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    pages = {None: {"users": [1, 2], "nextPageToken": "t2"}, "t2": {"users": [3]}}
    seen: list[Any] = []

    def method(**params: Any) -> FakeRequest:
        seen.append(params.get("pageToken"))
        return FakeRequest(outcomes=[pages[params.get("pageToken")]])

    assert list(g.paginate(method, "users", customer="c")) == [1, 2, 3]  # type: ignore[arg-type]
    assert seen == [None, "t2"]


@pytest.mark.parametrize(
    ("scopes", "unverified", "risk"),
    [
        (["https://www.googleapis.com/auth/drive"], False, "high"),
        (["https://www.googleapis.com/auth/gmail.readonly"], False, "high"),
        (["https://www.googleapis.com/auth/gmail.modify"], False, "high"),
        (["https://mail.google.com/"], False, "high"),
        (["https://www.googleapis.com/auth/calendar"], False, "medium"),
        (["https://www.googleapis.com/auth/drive.readonly"], False, "medium"),
        (["https://www.googleapis.com/auth/drive.file"], False, "low"),
        (["https://www.googleapis.com/auth/calendar.readonly"], False, "low"),
        (["openid"], True, "high"),
    ],
)
def test_app_risk_rule(scopes: list[str], unverified: bool, risk: str) -> None:
    assert app_risk(scopes, unverified=unverified)[0] == risk
