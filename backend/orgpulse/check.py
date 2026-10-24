"""Credential smoke test: `python -m orgpulse.check`.

1. Shows the config it is using (no secrets).
2. Asks Google for a token for each scope on its own, so you can see exactly
   which scopes are missing from the domain-wide delegation entry.
3. Lists 5 users from the Directory API.
4. Pings the database (optional; a failure here does not affect the Google checks).
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from googleapiclient.errors import HttpError

from orgpulse import google_client as g
from orgpulse.config import get_settings

OK, FAIL = "[ok]  ", "[FAIL]"


def _check_config() -> str | None:
    s = get_settings()
    path = s.google_service_account_json
    print("Config")
    print(f"  service account file : {path}")
    print(f"  impersonating admin  : {s.google_admin_impersonate or '(not set)'}")
    print(f"  customer id          : {s.google_customer_id}")
    print(f"  allowed domain       : {s.allowed_domain or '(not set)'}")
    print(f"  classroom enabled    : {s.enable_classroom}")
    if not s.google_admin_impersonate:
        return "GOOGLE_ADMIN_IMPERSONATE is not set"
    if not path.is_file():
        return f"service account file not found at {path}"
    try:
        info = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as err:
        return f"cannot read service account JSON: {err}"
    if info.get("type") != "service_account":
        return "that JSON is not a service account key (type != service_account)"
    print(f"  service account      : {info.get('client_email')}")
    print(f"  client id (for DWD)  : {info.get('client_id')}")
    return None


def _refresh_hint(err: RefreshError) -> str:
    args = err.args
    msg = args[0] if args and isinstance(args[0], str) else str(err)
    if "unauthorized_client" in msg:
        hint = "authorise this scope for the client ID in Admin console > Security > API controls > Domain-wide delegation"
    elif "Not a valid email" in msg:
        hint = "GOOGLE_ADMIN_IMPERSONATE is not a user in this Workspace"
    elif "Invalid JWT Signature" in msg or "invalid_client" in msg:
        hint = (
            "the key in the JSON was deleted or is wrong; create a new key for the service account"
        )
    elif "invalid_grant" in msg:
        hint = "check the admin email, and that this machine's clock is correct"
    else:
        hint = "unexpected error"
    return f"{hint}\n            ({msg})"


def _check_scopes() -> int:
    print("\nScopes (one token request per scope)")
    failures = 0
    for scope in g.configured_scopes():
        try:
            g.credentials([scope]).refresh(Request())
            print(f"  {OK} {scope}")
        except RefreshError as err:
            failures += 1
            print(f"  {FAIL} {scope}\n         -> {_refresh_hint(err)}")
    return failures


def _http_hint(err: HttpError) -> str:
    text = str(err)
    if "accessNotConfigured" in text or "has not been used" in text or "is disabled" in text:
        return "enable the Admin SDK API in the GCP project that owns the service account"
    if err.resp.status == 403:
        return "the impersonated user needs to be a super admin (or have the Users > Read admin privilege)"
    return text


def _list_users(limit: int) -> bool:
    print(f"\nFirst {limit} users (Directory API, ordered by email)")
    scope = [g.CORE_SCOPES[0]]  # admin.directory.user.readonly only
    try:
        resp: dict[str, Any] = g.execute(
            g.directory(scope)
            .users()
            .list(
                customer=get_settings().google_customer_id,
                maxResults=limit,
                orderBy="email",
                projection="full",
            ),
            what="users.list",
        )
    except RefreshError as err:
        print(f"  {FAIL} token request failed -> {_refresh_hint(err)}")
        return False
    except HttpError as err:
        print(f"  {FAIL} HTTP {err.resp.status} -> {_http_hint(err)}")
        return False

    users = resp.get("users", [])
    if not users:
        print("  (no users returned. Check GOOGLE_CUSTOMER_ID)")
        return False
    print(f"  {'email':<36} {'name':<24} {'last sign-in':<22} {'2SV':<4} {'susp':<5} org unit")
    for u in users:
        last = u.get("lastLoginTime", "")
        if last.startswith("1970-01-01"):
            last = "never"
        print(
            f"  {u.get('primaryEmail', ''):<36.36} {u.get('name', {}).get('fullName', ''):<24.24} "
            f"{last[:19]:<22} {'yes' if u.get('isEnrolledIn2Sv') else 'no':<4} "
            f"{'yes' if u.get('suspended') else 'no':<5} {u.get('orgUnitPath', '')}"
        )
    return True


def _check_db() -> None:
    print("\nDatabase")
    try:
        from orgpulse.db import ping

        ping()
        print(f"  {OK} connected")
    except Exception as err:
        print(
            f"  [skip] not reachable ({type(err).__name__}); fine if you only want to test Google"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m orgpulse.check")
    parser.add_argument("--limit", type=int, default=5, help="users to list (default 5)")
    parser.add_argument("--skip-scopes", action="store_true", help="skip per-scope token test")
    parser.add_argument("--skip-db", action="store_true", help="skip database ping")
    args = parser.parse_args(argv)

    problem = _check_config()
    if problem:
        print(f"\n{FAIL} {problem}")
        return 2

    scope_failures = 0 if args.skip_scopes else _check_scopes()
    users_ok = _list_users(args.limit)
    if not args.skip_db:
        _check_db()

    print()
    if users_ok and not scope_failures:
        print("All good: credentials work and every scope is granted.")
        return 0
    if users_ok:
        print(f"Users listed, but {scope_failures} scope(s) are missing. Add them before syncing.")
    else:
        print("Could not list users. See the errors above.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
