"""Org+ accounts: work email + password + authenticator app (TOTP) (multi-org mode).

Identities live in the control database; each organisation's Workspace data stays in
its own database. Design choices:

- Passwords are hashed with Argon2id and never stored or logged in clear.
- Every account must enrol an authenticator app (RFC 6238 TOTP, 6 digits, 30 s) before it
  can sign in, and every sign-in needs password + current code. The TOTP secret is stored
  encrypted with the master key; the QR code is drawn here, never by a third party.
  A code works once (replays are refused) and wrong codes count towards the lockout.
- Sign-up sends no email and needs no approval: an account is active once its
  authenticator is confirmed. What it may see is still decided by the organisation's
  directory (admins and managers only, once it has synced). The first account of a
  brand-new organisation creates the organisation.
- Enrolment and password-reset tokens are random 256-bit values; only their SHA-256 is
  stored; single use; short-lived.
- Wrong passwords or codes lock the account for a while; requests are rate-limited per
  IP and per email. Unknown emails cost the same time as known ones.
- Each account has a session version: a new password or a reset authenticator signs out
  every session.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import logging
import re
import secrets
import sys
import threading
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import pyotp
import segno
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from sqlalchemy import DateTime, Engine, ForeignKey, Integer, Text, func, select, text, update
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, Session, mapped_column

from orgpulse import crypto, mailer
from orgpulse.config import get_settings
from orgpulse.db import control_session
from orgpulse.orgs import ControlBase, org_for_domain, register_org

log = logging.getLogger(__name__)

_hasher = PasswordHasher()  # Argon2id, library defaults (64 MiB, 3 passes)
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(16))

ENROLL_TTL = timedelta(minutes=30)  # finishing sign-up (scan the QR code)
ADMIN_ENROLL_TTL = timedelta(hours=24)  # a link an admin hands over after a reset
RESET_TTL = timedelta(hours=1)
ISSUER = "Org+"
_EMAIL = re.compile(r"^[a-z0-9._%+'-]+@([a-z0-9-]+\.)+[a-z]{2,}$")
# Org+ is for Google Workspace organisations: personal mailboxes can't own one.
PERSONAL_DOMAINS = frozenset(
    [
        "gmail.com",
        "googlemail.com",
        "outlook.com",
        "hotmail.com",
        "live.com",
        "msn.com",
        "yahoo.com",
        "yahoo.co.in",
        "icloud.com",
        "me.com",
        "aol.com",
        "proton.me",
        "protonmail.com",
        "gmx.com",
        "zoho.com",
        "yandex.com",
        "rediffmail.com",
        "mail.com",
    ]
)
_COMMON_PASSWORDS = frozenset(
    [
        "password",
        "password1",
        "password123",
        "1234567890",
        "12345678910",
        "qwertyuiop",
        "qwerty12345",
        "iloveyou123",
        "welcome123",
        "admin12345",
        "letmein123",
        "changeme123",
    ]
)


class Account(ControlBase):
    __tablename__ = "accounts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    email: Mapped[str] = mapped_column(Text, unique=True)
    name: Mapped[str] = mapped_column(Text)
    password_hash: Mapped[str | None] = mapped_column(Text)
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # unused
    # Authenticator app: secret encrypted with the master key; enabled once a code is confirmed.
    totp_secret_enc: Mapped[str | None] = mapped_column(Text)
    totp_enabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    totp_last_step: Mapped[int] = mapped_column(Integer, server_default="0")  # no code reuse
    # No longer used (sign-ups needed approval in an earlier version); kept, not dropped.
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_by: Mapped[str | None] = mapped_column(Text)
    failed_logins: Mapped[int] = mapped_column(Integer, server_default="0")
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    session_version: Mapped[int] = mapped_column(Integer, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuthToken(ControlBase):
    __tablename__ = "auth_tokens"

    token_hash: Mapped[str] = mapped_column(Text, primary_key=True)
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="CASCADE"), index=True
    )
    purpose: Mapped[str] = mapped_column(Text)  # enroll / reset
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# Columns added after the first release (create_all only creates missing tables).
_ADDED_COLUMNS = (
    "totp_secret_enc text",
    "totp_enabled_at timestamptz",
    "totp_last_step integer NOT NULL DEFAULT 0",
    "approved_at timestamptz",
    "approved_by text",
)


def ensure_schema(engine: Engine) -> None:
    """Create the account tables and add any newer columns (idempotent)."""
    ControlBase.metadata.create_all(engine)
    with engine.begin() as conn:
        for col in _ADDED_COLUMNS:
            conn.execute(text(f"ALTER TABLE accounts ADD COLUMN IF NOT EXISTS {col}"))


class AuthError(Exception):
    def __init__(self, code: str, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


@dataclass(frozen=True)
class SignedIn:
    email: str
    name: str
    session_version: int


# --- Validation ------------------------------------------------------------------------


def normalise_email(email: str) -> str:
    email = (email or "").strip().lower()
    if len(email) > 254 or not _EMAIL.match(email):
        raise AuthError("bad_email", "Enter a valid work email address.")
    return email


def _work_email(email: str) -> str:
    email = normalise_email(email)
    if email.split("@")[1] in PERSONAL_DOMAINS:
        raise AuthError(
            "personal_email", "Use your organisation's Google Workspace email, not a personal one."
        )
    return email


def check_password(password: str, email: str) -> None:
    if not 10 <= len(password or "") <= 128:
        raise AuthError("weak_password", "Use 10 to 128 characters.")
    lowered = password.lower()
    if lowered in _COMMON_PASSWORDS or lowered == email or email.split("@")[0] in lowered:
        raise AuthError("weak_password", "Choose a less guessable password (not your email).")
    if len(set(password)) < 5:
        raise AuthError("weak_password", "Use a greater variety of characters.")


# --- Rate limiting (per process; the account lockout is the durable guard) --------------

_hits: dict[str, deque[float]] = defaultdict(deque)
_hits_lock = threading.Lock()


def rate_limit(key: str, limit: int, window_s: float) -> None:
    now = time.monotonic()
    with _hits_lock:
        q = _hits[key]
        while q and now - q[0] > window_s:
            q.popleft()
        if len(q) >= limit:
            raise AuthError("too_many", "Too many attempts. Wait a few minutes and try again.", 429)
        q.append(now)


# --- Tokens ----------------------------------------------------------------------------


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _new_token(account_id: uuid.UUID, purpose: str, ttl: timedelta) -> str:
    token = secrets.token_urlsafe(32)
    with control_session() as s:
        # One live token per account and purpose: older ones stop working.
        s.execute(
            update(AuthToken)
            .where(
                AuthToken.account_id == account_id,
                AuthToken.purpose == purpose,
                AuthToken.used_at.is_(None),
            )
            .values(used_at=func.now())
        )
        s.add(
            AuthToken(
                token_hash=_hash_token(token),
                account_id=account_id,
                purpose=purpose,
                expires_at=datetime.now(UTC) + ttl,
            )
        )
    return token


def _live_token(s: Session, token: str, purpose: str | None = None) -> tuple[AuthToken, Account]:
    row = s.get(AuthToken, _hash_token(token or ""), with_for_update=True)
    if (
        row is None
        or row.used_at is not None
        or row.expires_at < datetime.now(UTC)
        or (purpose and row.purpose != purpose)
    ):
        raise AuthError("bad_link", "This link has expired or was already used.")
    account = s.get(Account, row.account_id)
    if account is None:
        raise AuthError("bad_link", "This link has expired or was already used.")
    return row, account


def describe_token(token: str) -> dict[str, str]:
    with control_session() as s:
        row, account = _live_token(s, token)
        return {"email": account.email, "purpose": row.purpose}


# --- Authenticator (TOTP) ---------------------------------------------------------------


def _totp(secret_enc: str) -> pyotp.TOTP:
    return pyotp.TOTP(crypto.decrypt(secret_enc))


def _matching_step(totp: pyotp.TOTP, code: str) -> int | None:
    """The 30-second step this code belongs to (now, or one step either side for clock
    drift), compared in constant time; None if it matches none."""
    code = re.sub(r"\s", "", code or "")
    if not re.fullmatch(r"\d{6}", code):
        return None
    now = totp.timecode(datetime.now(UTC))
    found = None
    for step in (now - 1, now, now + 1):
        if hmac.compare_digest(totp.generate_otp(step), code):
            found = step
    return found


def enrollment(token: str) -> dict[str, str]:
    """QR code (SVG data URI) + secret for the authenticator app, for an enrolment token."""
    with control_session() as s:
        _, account = _live_token(s, token, "enroll")
        if not account.totp_secret_enc:
            account.totp_secret_enc = crypto.encrypt(pyotp.random_base32())
        secret = crypto.decrypt(account.totp_secret_enc)
        email = account.email
    uri = pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name=ISSUER)
    qr = segno.make(uri, error="m").svg_data_uri(scale=5, border=2)
    return {"email": email, "secret": secret, "uri": uri, "qr": qr}


def confirm_enrollment(token: str, code: str) -> dict[str, str]:
    """First code from the app: turns the authenticator on. Returns the account status."""
    with control_session() as s:
        row, account = _live_token(s, token, "enroll")
        if not account.totp_secret_enc:
            raise AuthError("bad_code", "Scan the QR code first.")
        step = _matching_step(_totp(account.totp_secret_enc), code)
        if step is None:
            raise AuthError("bad_code", "That code didn't match. Use the current 6-digit code.")
        now = datetime.now(UTC)
        account.totp_enabled_at = now
        # Not recorded as "used": signing in straight after setup may reuse this code.
        account.totp_last_step = 0
        account.session_version += 1
        row.used_at = now
        email = account.email
    domain = email.split("@")[1]
    if org_for_domain(domain) is None:
        register_org(domain)  # first account of a brand-new organisation creates it
    _session_cache.pop(email, None)
    log.info("authenticator enrolled for %s", email)
    return {"email": email, "status": "active"}


# --- Flows -----------------------------------------------------------------------------


def start_signup(email: str, name: str, password: str) -> str:
    """Create the account (or restart an unfinished sign-up); returns an enrolment token."""
    email = _work_email(email)
    name = " ".join((name or "").split())[:100]
    if not name:
        raise AuthError("bad_name", "Enter your name.")
    check_password(password, email)
    with control_session() as s:
        account = s.scalar(select(Account).where(Account.email == email).with_for_update())
        if account is not None and account.totp_enabled_at is not None:
            raise AuthError(
                "exists", "There's already an Org+ account for this email. Sign in instead.", 409
            )
        if account is None:
            account = Account(id=uuid.uuid4(), email=email, name=name)
            s.add(account)
        account.name = name
        account.password_hash = _hasher.hash(password)
        account.totp_secret_enc = crypto.encrypt(pyotp.random_base32())  # fresh each attempt
        s.flush()
        account_id = account.id
    return _new_token(account_id, "enroll", ENROLL_TTL)


def forgot_password(email: str) -> None:
    """Email a reset link (needs SMTP). Same outcome whether or not the account exists."""
    try:
        email = normalise_email(email)
    except AuthError:
        return
    with control_session() as s:
        account = s.scalar(select(Account).where(Account.email == email))
        if account is None or account.totp_enabled_at is None:
            return
        account_id, name = account.id, account.name
    token = _new_token(account_id, "reset", RESET_TTL)
    mailer.send_link(
        email,
        "Reset your Org+ password",
        f"Hi {name}, someone (hopefully you) asked to reset your Org+ password. "
        "The link works once, for 1 hour. You'll still need your authenticator code to sign in.",
        f"{get_settings().app_url.rstrip('/')}/setup?token={token}",
        "Choose a new password",
    )


def set_password(token: str, password: str) -> str:
    """Use a reset link: new password, every other session signed out."""
    with control_session() as s:
        row, account = _live_token(s, token, "reset")
        check_password(password, account.email)
        account.password_hash = _hasher.hash(password)
        account.session_version += 1
        account.failed_logins = 0
        account.locked_until = None
        row.used_at = datetime.now(UTC)
        email = account.email
    _session_cache.pop(email, None)
    log.info("password reset for %s", email)
    return email


def _verify(hash_: str, password: str) -> bool:
    try:
        return _hasher.verify(hash_, password)
    except (VerificationError, InvalidHashError):
        return False


def login(email: str, password: str, code: str, client_ip: str) -> SignedIn:
    rate_limit(f"ip:{client_ip}", 30, 600)
    wrong = AuthError("invalid", "Wrong email, password or authenticator code.", 401)
    try:
        email = normalise_email(email)
    except AuthError:
        _verify(_DUMMY_HASH, password)  # same cost as a real check
        raise wrong from None
    rate_limit(f"email:{email}", 10, 600)
    settings = get_settings()
    error: AuthError | None = None
    # The session commits on exit, so failed attempts are recorded before we raise.
    with control_session() as s:
        account = s.scalar(select(Account).where(Account.email == email).with_for_update())
        now = datetime.now(UTC)
        if (
            account is None
            or account.password_hash is None
            or account.totp_enabled_at is None
            or not account.totp_secret_enc
        ):
            _verify(_DUMMY_HASH, password)
            error = wrong
        elif account.locked_until and account.locked_until > now:
            error = AuthError(
                "locked",
                "Too many failed sign-ins: this account is locked for a few minutes.",
                423,
            )
        else:
            password_ok = _verify(account.password_hash, password)
            step = _matching_step(_totp(account.totp_secret_enc), code) if password_ok else None
            if step is None or step <= account.totp_last_step:  # wrong, or a reused code
                account.failed_logins += 1
                error = wrong
                if account.failed_logins >= settings.login_max_failures:
                    account.failed_logins = 0
                    account.locked_until = now + timedelta(minutes=settings.login_lock_minutes)
                    log.warning("account %s locked after repeated failed sign-ins", email)
            else:
                if _hasher.check_needs_rehash(account.password_hash):
                    account.password_hash = _hasher.hash(password)
                account.totp_last_step = step
                account.failed_logins = 0
                account.locked_until = None
                account.last_login_at = now
                signed_in = SignedIn(account.email, account.name, account.session_version)
    if error is not None:
        raise error
    return signed_in


# --- Admin: authenticator resets, removal -------------------------------------------------


def _status(a: Account) -> str:
    return "active" if a.totp_enabled_at else "setup_incomplete"


def list_accounts(domain: str) -> list[dict[str, Any]]:
    with control_session() as s:
        rows = s.scalars(
            select(Account).where(Account.email.like(f"%@{domain}")).order_by(Account.created_at)
        ).all()
        return [
            {
                "id": str(a.id),
                "email": a.email,
                "name": a.name,
                "status": _status(a),
                "created_at": a.created_at,
                "last_login_at": a.last_login_at,
            }
            for a in rows
            if a.email.split("@")[1] == domain
        ]


def _in_domain(s: Session, account_id: uuid.UUID, domain: str) -> Account:
    account = s.get(Account, account_id, with_for_update=True)
    if account is None or account.email.split("@")[1] != domain:
        raise AuthError("not_found", "No such account in your organisation.", 404)
    return account


def remove(account_id: uuid.UUID, domain: str, by: str) -> None:
    with control_session() as s:
        account = _in_domain(s, account_id, domain)
        if account.email == by:
            raise AuthError("self", "You can't remove your own account.")
        email = account.email
        s.delete(account)
    _session_cache.pop(email, None)
    log.info("account %s removed by %s", email, by)


def reset_authenticator(account_id: uuid.UUID, domain: str, by: str) -> str:
    """Turn the authenticator off, sign the person out everywhere, and return a one-time
    enrolment token (24 h) for the admin to hand over."""
    with control_session() as s:
        account = _in_domain(s, account_id, domain)
        account.totp_enabled_at = None
        account.totp_secret_enc = crypto.encrypt(pyotp.random_base32())
        account.totp_last_step = 0
        account.session_version += 1
        email = account.email
    _session_cache.pop(email, None)
    log.info("authenticator reset for %s by %s", email, by)
    return _new_token(account_id, "enroll", ADMIN_ENROLL_TTL)


# --- Session checks (every API request) -------------------------------------------------

_session_cache: dict[str, tuple[float, int | None]] = {}
_SESSION_CACHE_S = 15.0


def session_valid(email: str, session_version: object) -> bool:
    """The signed-in account still exists, has its authenticator on, and
    hasn't changed its password or authenticator since this session began."""
    hit = _session_cache.get(email)
    if hit is None or time.monotonic() - hit[0] > _SESSION_CACHE_S:
        with control_session() as s:
            row = s.execute(
                select(Account.session_version).where(
                    Account.email == email,
                    Account.totp_enabled_at.is_not(None),
                )
            ).first()
        hit = (time.monotonic(), row[0] if row else None)
        _session_cache[email] = hit
    return hit[1] is not None and session_version == hit[1]


# --- Operator CLI ------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """python -m orgpulse.accounts list <domain> | reset-mfa <email>"""
    from orgpulse.logging_setup import setup_logging

    setup_logging()
    parser = argparse.ArgumentParser(prog="python -m orgpulse.accounts")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list").add_argument("domain")
    sub.add_parser("reset-mfa").add_argument("email")
    args = parser.parse_args(argv)
    from orgpulse.db import control_engine

    ensure_schema(control_engine())
    if args.cmd == "list":
        for a in list_accounts(args.domain.lower()):
            print(f"{a['email']:40} {a['status']}")
        return 0
    email = normalise_email(args.email)
    with control_session() as s:
        account = s.scalar(select(Account).where(Account.email == email))
        if account is None:
            print(f"no account for {email}", file=sys.stderr)
            return 1
        account_id = account.id
    domain = email.split("@")[1]
    token = reset_authenticator(account_id, domain, "operator (CLI)")
    print(f"{get_settings().app_url.rstrip('/')}/enroll?token={token}  (valid 24 h, once)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
