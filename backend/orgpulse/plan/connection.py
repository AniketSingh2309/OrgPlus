"""Connection check: request a token for each scope on its own."""

from __future__ import annotations

from typing import Any

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request

from orgpulse import google_client as g
from orgpulse.config import get_settings

SCOPE_PURPOSE: dict[str, str] = {
    **{s: "core (Directory / Reports)" for s in g.CORE_SCOPES},
    **{s: "Classroom insights" for s in g.CLASSROOM_SCOPES},
    **g.OPTIONAL_SCOPES,
}


NOT_AUTHORISED = (
    "Not authorised in Admin console > Security > API controls > Domain-wide delegation"
)


def diagnose(results: list[dict[str, Any]], client_id: str) -> str | None:
    """One plain explanation when the failures share a cause (e.g. no delegation entry at all)."""
    failed = [r for r in results if not r["granted"]]
    if not failed or len(failed) < len(results):
        return None
    if all(r["error"] == NOT_AUTHORISED for r in failed):
        return (
            f"Google does not recognise client ID {client_id} for domain-wide delegation, so every scope "
            "fails. In the Admin console of this Workspace (as a super admin) go to Security > Access and "
            "data control > API controls > Manage Domain Wide Delegation and add this exact client ID "
            "(not the OAuth sign-in client ID) with the scopes below. If you just added it, wait a few "
            "minutes and re-check."
        )
    errors = {r["error"] for r in failed}
    return f"Every scope failed with the same error: {errors.pop()}" if len(errors) == 1 else None


def check_scopes(auth: g.GoogleAuth) -> dict[str, Any]:
    """{"scopes": [{scope, purpose, required, granted, error}], "core_ok": bool}"""
    # Only the core scopes are required; Classroom and the rest just switch features on.
    scopes: list[tuple[str, bool]] = [(s, True) for s in g.CORE_SCOPES]
    if get_settings().enable_classroom:
        scopes += [(s, False) for s in g.CLASSROOM_SCOPES]
    scopes += [(s, False) for s in g.OPTIONAL_SCOPES]
    results: list[dict[str, Any]] = []
    for scope, required in scopes:
        error = None
        try:
            g.credentials([scope], auth=auth).refresh(Request())
            granted = True
        except RefreshError as err:
            granted = False
            msg = str(err.args[0]) if err.args else str(err)
            if "unauthorized_client" in msg or "Requested client not authorized" in msg:
                error = NOT_AUTHORISED
            elif "Not a valid email" in msg:
                error = "The admin email is not a user in this Workspace"
            elif "invalid_grant" in msg:
                error = "Invalid grant: check the admin email and the key"
            else:
                error = msg[:200]
        results.append(
            {
                "scope": scope,
                "purpose": SCOPE_PURPOSE.get(scope, ""),
                "required": required,
                "granted": granted,
                "error": error,
            }
        )
    return {
        "diagnosis": diagnose(results, auth.client_id),
        "client_id": auth.client_id,
        "client_email": auth.client_email,
        "scopes": results,
        "core_ok": all(r["granted"] for r in results if r["required"]),
        "missing_csv": ",".join(r["scope"] for r in results if not r["granted"]),
    }
