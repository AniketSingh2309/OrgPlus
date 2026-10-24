"""SKU -> edition/tier, probe outcome classification, require_feature gating."""

from __future__ import annotations

import json
import uuid
from typing import Any

import httplib2
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from google.auth.exceptions import RefreshError, TransportError
from googleapiclient.errors import HttpError

from orgpulse.api.deps import Viewer, get_viewer
from orgpulse.features import gating
from orgpulse.features.registry import load_modules
from orgpulse.plan import probes, skus


def _assign(*skus_: str) -> list[dict[str, str]]:
    return [{"skuId": s, "userId": f"u{i}@example.com"} for i, s in enumerate(skus_)]


# --- SKU mapping -----------------------------------------------------------------------


def test_single_edition() -> None:
    r = skus.detect_edition(_assign("1010020028", "1010020028"))
    assert (r.edition, r.tier, r.licences_assigned) == ("Business Standard", "free", 2)


def test_mixed_domain_takes_highest_tier_and_keeps_breakdown(fixture: Any) -> None:
    r = skus.detect_edition(fixture("licence_assignments.json")["items"])
    assert (r.edition, r.tier) == ("Business Plus", "plus")
    assert r.breakdown["1010020028"]["count"] == 3
    assert r.breakdown["1010020027"]["edition"] == "Business Starter"
    assert r.breakdown["9999999999"] == {
        "edition": "Some Future SKU",
        "tier": "unknown",
        "count": 1,
        "known": False,
    }
    assert r.licences_assigned == 6


def test_enterprise_beats_plus_and_rank_within_tier() -> None:
    assert skus.detect_edition(_assign("1010020025", "1010020026")).edition == "Enterprise Standard"
    assert skus.detect_edition(_assign("1010020026", "1010020020")).edition == "Enterprise Plus"
    assert skus.detect_edition(_assign("1010310005", "1010070001")).edition == "Education Standard"
    assert skus.detect_edition(_assign("1010020034", "1010020030")).tier == "plus"  # Frontline Plus


def test_no_known_skus_is_unknown() -> None:
    assert skus.detect_edition(_assign("123")).tier == "unknown"
    assert skus.detect_edition([]).edition == "Unknown"


# --- Probe classification --------------------------------------------------------------


def _http(status: int, message: str) -> HttpError:
    resp = httplib2.Response({"status": status})
    body = json.dumps({"error": {"code": status, "message": message}}).encode()
    return HttpError(resp, body, uri="https://admin.googleapis.com/x")


@pytest.mark.parametrize(
    ("exc", "status"),
    [
        (_http(403, "Caller does not have access to the customers reporting data."), "locked"),
        (_http(400, "Application rules is not available for this customer"), "locked"),
        (
            _http(403, "Admin SDK API has not been used in project 123 before or it is disabled"),
            "not_configured",
        ),
        (_http(500, "Backend Error"), "error"),
        (_http(503, "Service unavailable"), "error"),
        (
            RefreshError("unauthorized_client: Client is unauthorized to retrieve access tokens"),
            "not_configured",
        ),
        (RefreshError("invalid_grant: Invalid JWT Signature."), "error"),
        (TimeoutError("timed out"), "error"),
        (TimeoutError("timed out"), "error"),
        (TransportError("connection reset"), "error"),
    ],
)
def test_classify_error(exc: BaseException, status: str) -> None:
    assert probes.classify_error(exc, "scope").status == status


def test_probe_success_and_empty_are_on(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []

    def fake_execute(request: Any, **_: Any) -> dict[str, Any]:
        calls.append(request)
        return {}  # empty result: available, no events yet

    class FakeReports:
        def activities(self) -> FakeReports:
            return self

        def list(self, **kw: Any) -> dict[str, Any]:
            return kw

    monkeypatch.setattr(probes.g, "execute", fake_execute)
    monkeypatch.setattr(probes.g, "reports", lambda *a, **k: FakeReports())
    result = probes.PROBES["dlp_events"](probes.ProbeContext("my_customer"))
    assert result.status == "on"
    assert calls[0]["applicationName"] == "rules" and calls[0]["maxResults"] == 1


def test_probe_403_is_locked(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_: Any, **__: Any) -> Any:
        raise _http(403, "not available for this customer")

    monkeypatch.setattr(probes.g, "vault", boom)
    assert probes.probe_vault(probes.ProbeContext("c")).status == "locked"


def test_bigquery_not_configured_without_dataset() -> None:
    assert probes.probe_bigquery(probes.ProbeContext("c")).status == "not_configured"


def test_probe_application_names() -> None:
    """Keep the Reports application names the probes use in one visible place."""
    assert set(probes.PROBES) == {
        "bigquery_logs", "gmail_logs", "vault", "alert_center", "dlp_events",
        "context_aware_access", "gemini_usage", "classroom", "chrome_mgmt",
    }  # fmt: skip


# --- require_feature -------------------------------------------------------------------

TENANT = uuid.uuid4()


class _Cap:
    def __init__(self, status: str, detail: str = "") -> None:
        self.status = status
        self.detail = detail


@pytest.fixture
def app(monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    load_modules()
    state = {"vault": _Cap("locked", "HTTP 403"), "gemini_usage": _Cap("on")}
    monkeypatch.setattr(gating, "capability_status", lambda tid: state)
    monkeypatch.setattr(
        gating, "is_enabled", lambda tid, key: key in state and state[key].status == "on"
    )

    app = FastAPI()
    app.dependency_overrides[get_viewer] = lambda: Viewer(
        "a@example.com", "A", TENANT, "admin", None
    )

    @app.get("/vault", dependencies=[Depends(gating.require_feature("vault"))])
    def vault() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/gemini", dependencies=[Depends(gating.require_feature("gemini_usage"))])
    def gemini() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/dlp", dependencies=[Depends(gating.require_feature("dlp_events"))])
    def dlp() -> dict[str, bool]:
        return {"ok": True}

    return app


def test_require_feature_402_when_locked(app: FastAPI) -> None:
    r = TestClient(app).get("/vault")
    assert r.status_code == 402
    body = r.json()["detail"]
    assert body["feature"] == "vault"
    assert body["requires"].startswith("Business Plus or above")
    assert body["status"] == "locked"


def test_require_feature_passes_when_on(app: FastAPI) -> None:
    assert TestClient(app).get("/gemini").json() == {"ok": True}


def test_require_feature_402_when_never_checked(app: FastAPI) -> None:
    r = TestClient(app).get("/dlp")
    assert r.status_code == 402 and r.json()["detail"]["status"] == "unknown"


def test_every_module_registers_a_probe() -> None:
    assert set(load_modules()) == set(probes.PROBES)


def _fake_reports(monkeypatch: pytest.MonkeyPatch, items: list[dict[str, Any]]) -> None:
    class FakeReports:
        def activities(self) -> FakeReports:
            return self

        def list(self, **kw: Any) -> dict[str, Any]:
            return kw

    monkeypatch.setattr(probes.g, "execute", lambda request, **_: {"items": items})
    monkeypatch.setattr(probes.g, "reports", lambda *a, **k: FakeReports())


@pytest.mark.parametrize(
    ("tier", "items", "status"),
    [
        ("free", [], "locked"),  # Business Starter: Google answers empty for DLP -> not included
        ("plus", [], "locked"),
        ("enterprise", [], "on"),  # included, just no events yet
        (None, [], "on"),  # edition unknown: trust the API
        ("free", [{"id": {}}], "on"),  # real events always win
    ],
)
def test_reports_probe_uses_edition_for_empty_answers(
    monkeypatch: pytest.MonkeyPatch, tier: str | None, items: list[dict[str, Any]], status: str
) -> None:
    _fake_reports(monkeypatch, items)
    ctx = probes.ProbeContext(
        "c", edition="Business Starter" if tier == "free" else None, tier=tier
    )
    result = probes.PROBES["dlp_events"](ctx)
    assert result.status == status
    if status == "locked":
        assert "Not included" in result.detail
