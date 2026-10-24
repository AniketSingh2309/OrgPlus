"""Third-party app risk rule.

high:   full Drive, Gmail read/modify/full, or the app is not registered with Google
medium: full Calendar or Drive read-only
low:    everything else
"""

from __future__ import annotations

from collections.abc import Iterable

_AUTH = "https://www.googleapis.com/auth/"

HIGH_SCOPES = {
    _AUTH + "drive",
    _AUTH + "gmail.readonly",
    _AUTH + "gmail.modify",
    "https://mail.google.com/",
}
MEDIUM_SCOPES = {
    _AUTH + "calendar",
    _AUTH + "drive.readonly",
}

RISK_ORDER = {"low": 0, "medium": 1, "high": 2}


def _norm(scope: str) -> str:
    """Trim whitespace/trailing slashes; full Gmail is canonically written with one."""
    s = scope.strip().rstrip("/")
    return "https://mail.google.com/" if s == "https://mail.google.com" else s


def app_risk(scopes: Iterable[str], *, unverified: bool = False) -> tuple[str, str]:
    """Return (risk, reason)."""
    normalised = {_norm(s) for s in scopes}
    if unverified:
        return "high", "app is not verified/registered with Google"
    high = sorted(normalised & HIGH_SCOPES)
    if high:
        return "high", "has " + ", ".join(s.removeprefix(_AUTH) for s in high)
    medium = sorted(normalised & MEDIUM_SCOPES)
    if medium:
        return "medium", "has " + ", ".join(s.removeprefix(_AUTH) for s in medium)
    return "low", "limited scopes"


def risk_score(scopes: Iterable[str], *, unverified: bool, users: int) -> int:
    """0-100 score for ranking apps: severity first, then breadth of access and reach."""
    scope_list = list(scopes)
    risk, _ = app_risk(scope_list, unverified=unverified)
    base = {"high": 60, "medium": 30, "low": 0}[risk]
    return min(100, base + min(20, len(scope_list) * 2) + min(20, users))
