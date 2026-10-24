"""Account endpoints.

Public (no session): sign up, enrol the authenticator app, sign in, password reset.
Sign-in is called by the web server (NextAuth), which then issues the session cookie.

Admins (session): list and remove their organisation's accounts, and reset
someone's authenticator.
"""

from __future__ import annotations

import ipaddress
import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from orgpulse import accounts, mailer
from orgpulse.accounts import AuthError
from orgpulse.api.deps import Viewer, require_admin, resolve_viewer
from orgpulse.db import current_org, multi_org, session_scope, use_org
from orgpulse.orgs import org_for_domain

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/account", tags=["account"])
admin_router = APIRouter(prefix="/api/accounts", tags=["accounts"])


class SignupBody(BaseModel):
    email: str
    name: str
    password: str


class EmailBody(BaseModel):
    email: str


class TokenBody(BaseModel):
    token: str


class CodeBody(BaseModel):
    token: str
    code: str


class PasswordBody(BaseModel):
    token: str
    password: str


class LoginBody(BaseModel):
    email: str
    password: str
    code: str


SENT = {
    "ok": True,
    "message": "If that address has an Org+ account, an email with a reset link is on its way.",
}


def _client_ip(request: Request) -> str:
    """The browser's IP. Only the web server on a private/loopback address may pass it on."""
    peer = request.client.host if request.client else "unknown"
    forwarded = request.headers.get("x-orgplus-client-ip", "")
    try:
        trusted = ipaddress.ip_address(peer).is_private or ipaddress.ip_address(peer).is_loopback
    except ValueError:
        trusted = False
    return forwarded.split(",")[0].strip() if trusted and forwarded else peer


def _fail(err: AuthError) -> HTTPException:
    return HTTPException(err.status, {"code": err.code, "message": err.message})


def _require_multi_org() -> None:
    if not multi_org():
        raise HTTPException(
            404, {"code": "accounts_off", "message": "Accounts need CONTROL_DATABASE_URL."}
        )


@router.post("/signup")
async def signup(body: SignupBody, request: Request) -> dict[str, str]:
    """Step 1: name, work email, password. Returns the token for step 2 (authenticator)."""
    _require_multi_org()
    try:
        accounts.rate_limit(f"signup:{_client_ip(request)}", 10, 3600)
        token = await run_in_threadpool(accounts.start_signup, body.email, body.name, body.password)
    except AuthError as err:
        raise _fail(err) from err
    return {"enroll_token": token}


@router.post("/mfa/setup")
async def mfa_setup(body: TokenBody, request: Request) -> dict[str, str]:
    """Step 2: the QR code (and the secret, for typing in by hand)."""
    _require_multi_org()
    try:
        accounts.rate_limit(f"link:{_client_ip(request)}", 60, 600)
        return await run_in_threadpool(accounts.enrollment, body.token)
    except AuthError as err:
        raise _fail(err) from err


@router.post("/mfa/confirm")
async def mfa_confirm(body: CodeBody, request: Request) -> dict[str, str]:
    """Step 3: the first code from the app switches the authenticator on."""
    _require_multi_org()
    try:
        accounts.rate_limit(f"mfa:{_client_ip(request)}", 20, 600)
        accounts.rate_limit(
            f"mfa-token:{body.token[:16]}", 8, 600
        )  # guessing codes for one sign-up
        return await run_in_threadpool(accounts.confirm_enrollment, body.token, body.code)
    except AuthError as err:
        raise _fail(err) from err


@router.post("/forgot")
async def forgot(body: EmailBody, request: Request) -> dict[str, object]:
    _require_multi_org()
    try:
        accounts.rate_limit(f"forgot:{_client_ip(request)}", 10, 3600)
        await run_in_threadpool(accounts.forgot_password, body.email)
    except AuthError as err:
        raise _fail(err) from err
    except mailer.MailNotConfigured as err:
        log.error("reset email not sent: %s", err)
    except Exception:
        log.exception("reset email failed")
    return SENT


@router.post("/link")
async def link(body: TokenBody, request: Request) -> dict[str, str]:
    """Which account a reset / enrolment link is for (so the page can show it)."""
    _require_multi_org()
    try:
        accounts.rate_limit(f"link:{_client_ip(request)}", 60, 600)
        return await run_in_threadpool(accounts.describe_token, body.token)
    except AuthError as err:
        raise _fail(err) from err


@router.post("/password")
async def password(body: PasswordBody, request: Request) -> dict[str, str]:
    _require_multi_org()
    try:
        accounts.rate_limit(f"link:{_client_ip(request)}", 60, 600)
        email = await run_in_threadpool(accounts.set_password, body.token, body.password)
    except AuthError as err:
        raise _fail(err) from err
    return {"email": email}


def _org_access(email: str, name: str) -> None:
    """After password + code: may this person open their organisation in Org+?"""
    org = org_for_domain(email.split("@")[1])
    if org is None:
        raise AuthError("no_org", "Your organisation isn't set up in Org+.", 403)
    if not org.ready:
        return  # just signed up: they'll see "setting up" and then Connect
    with use_org(org), session_scope() as db:
        try:
            resolve_viewer(db, email, name)
        except HTTPException as err:
            raise AuthError(
                "no_access",
                "Your account works, but Org+ is only for your organisation's admins and "
                f"managers ({err.detail}).",
                403,
            ) from err


@router.post("/login")
async def login(body: LoginBody, request: Request) -> dict[str, object]:
    _require_multi_org()
    try:
        who = await run_in_threadpool(
            accounts.login, body.email, body.password, body.code, _client_ip(request)
        )
        await run_in_threadpool(_org_access, who.email, who.name)
    except AuthError as err:
        raise _fail(err) from err
    return {"email": who.email, "name": who.name, "sv": who.session_version}


# --- Admins: this organisation's accounts -------------------------------------------------


def _domain() -> str:
    org = current_org()
    if org is None:
        raise HTTPException(404, "accounts need multi-org mode")
    return org.domain


@admin_router.get("")
def list_accounts(viewer: Viewer = Depends(require_admin)) -> dict[str, Any]:
    return {"accounts": accounts.list_accounts(_domain()), "me": viewer.email}


@admin_router.delete("/{account_id}")
def remove(account_id: uuid.UUID, viewer: Viewer = Depends(require_admin)) -> dict[str, bool]:
    try:
        accounts.remove(account_id, _domain(), viewer.email)
    except AuthError as err:
        raise _fail(err) from err
    return {"ok": True}


@admin_router.post("/{account_id}/reset-mfa")
def reset_mfa(account_id: uuid.UUID, viewer: Viewer = Depends(require_admin)) -> dict[str, str]:
    """Lost phone: switch their authenticator off and get a one-time link to hand over."""
    try:
        token = accounts.reset_authenticator(account_id, _domain(), viewer.email)
    except AuthError as err:
        raise _fail(err) from err
    return {"enroll_path": f"/enroll?token={token}"}
