"""One database per organisation: provisioning, isolation, routing, per-org encryption.

Runs only when MULTI_ORG_ADMIN_URL is set to a Postgres superuser URL, e.g.
MULTI_ORG_ADMIN_URL=postgresql://postgres@127.0.0.1:5432/postgres
The superuser only creates a throwaway provisioning role like deploy/postgres/init.sql
does; everything else runs with that non-superuser role, as in production. The control
database and every organisation created here are dropped afterwards.
"""

from __future__ import annotations

import os
import time
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import jwt
import psycopg
import pyotp
import pytest
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url

pytestmark = pytest.mark.skipif(
    not os.environ.get("MULTI_ORG_ADMIN_URL"), reason="MULTI_ORG_ADMIN_URL not set"
)

CONTROL = "orgplus_ctl_pytest"
PROVISIONER = "orgplus_admin_pytest"
ENV_KEYS = (
    "CONTROL_DATABASE_URL",
    "ADMIN_DATABASE_URL",
    "ORG_DATABASE_URL_TEMPLATE",
    "CREDENTIAL_ENC_KEY",
    "ORG_ADMINS",
    "DATABASE_URL",
)


def _clear_caches() -> None:
    from orgpulse import orgs
    from orgpulse.config import get_settings
    from orgpulse.db import get_engine
    from orgpulse.tenancy import default_tenant_id

    for engine_cache in (get_engine,):
        engine_cache.cache_clear()  # type: ignore[attr-defined]
    get_settings.cache_clear()
    default_tenant_id.cache_clear()  # type: ignore[attr-defined]
    orgs._org_fernet.cache_clear()
    orgs._cache.clear()
    from orgpulse import accounts

    accounts._session_cache.clear()
    accounts._hits.clear()


def _conninfo(role: str, db: str) -> str:
    u = make_url(os.environ["MULTI_ORG_ADMIN_URL"])
    return f"host={u.host} port={u.port or 5432} user={role} dbname={db}"


def _superuser() -> Any:
    url = os.environ["MULTI_ORG_ADMIN_URL"].replace("postgresql://", "postgresql+psycopg://", 1)
    return create_engine(url, isolation_level="AUTOCOMMIT")


@pytest.fixture(scope="module")
def two_orgs() -> Iterator[tuple[Any, Any]]:
    u = make_url(os.environ["MULTI_ORG_ADMIN_URL"])
    hostport = f"{u.host}:{u.port or 5432}"
    root = _superuser()
    with root.connect() as conn:  # what deploy/postgres/init.sql sets up
        conn.execute(text(f"DROP ROLE IF EXISTS {PROVISIONER}"))
        conn.execute(
            text(f"CREATE ROLE {PROVISIONER} LOGIN NOSUPERUSER CREATEDB CREATEROLE NOINHERIT")
        )
        conn.execute(text(f"ALTER ROLE {PROVISIONER} SET createrole_self_grant = 'set'"))
        conn.execute(text(f"GRANT CONNECT ON DATABASE postgres TO {PROVISIONER}"))
    saved = {k: os.environ.get(k) for k in ENV_KEYS}
    os.environ.update(
        CONTROL_DATABASE_URL=f"postgresql://{CONTROL}@{hostport}/{CONTROL}",
        ADMIN_DATABASE_URL=f"postgresql://{PROVISIONER}@{hostport}/postgres",
        ORG_DATABASE_URL_TEMPLATE=f"postgresql://{{role}}@{hostport}/{{db}}",
        CREDENTIAL_ENC_KEY=Fernet.generate_key().decode(),
        ORG_ADMINS="head@alpha.test,head@beta.test,owner@alpha.test,signer@beta.test",
    )
    os.environ.pop("DATABASE_URL", None)
    _clear_caches()

    from orgpulse import orgs

    try:
        orgs.setup_control()
        a = orgs.add_org("alpha.test", "Alpha")
        b = orgs.add_org("beta.test", "Beta")
        yield a, b
    finally:
        _clear_caches()
        with root.connect() as conn:
            try:
                with psycopg.connect(_conninfo("postgres", CONTROL)) as c:
                    names = [r[0] for r in c.execute("SELECT db_name FROM orgs").fetchall()]
            except psycopg.OperationalError:
                names = []
            for name in [*names, CONTROL]:
                conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
                conn.execute(text(f'DROP ROLE IF EXISTS "{name}"'))
            conn.execute(text(f"REVOKE CONNECT ON DATABASE postgres FROM {PROVISIONER}"))
            conn.execute(text(f"DROP ROLE IF EXISTS {PROVISIONER}"))
        root.dispose()
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        _clear_caches()


def token(email: str, sv: int | None = None) -> dict[str, str]:
    """A web-app session token; `sv` is the account's session version (signed in)."""
    secret = os.environ["NEXTAUTH_SECRET"]
    claims: dict[str, Any] = {
        "email": email,
        "name": email,
        "aud": "orgpulse-api",
        "exp": int(time.time()) + 300,
    }
    if sv is not None:
        claims["sv"] = sv
    return {"Authorization": "Bearer " + jwt.encode(claims, secret, algorithm="HS256")}


def _account(email: str, password: str | None = None, secret: str | None = None) -> int:
    """A finished account with an authenticator (session version returned),
    created directly in the control DB."""
    from orgpulse import crypto
    from orgpulse.accounts import Account, _hasher
    from orgpulse.db import control_session

    with control_session() as s:
        acc = s.scalar(select(Account).where(Account.email == email))
        if acc is None:
            acc = Account(id=uuid.uuid4(), email=email, name=email.split("@")[0])
            s.add(acc)
        now = datetime.now(UTC)
        acc.password_hash = _hasher.hash(password or "unused-" + uuid.uuid4().hex)
        acc.totp_secret_enc = crypto.encrypt(secret or pyotp.random_base32())
        acc.totp_enabled_at = now
        acc.totp_last_step = 0
        s.flush()
        return int(acc.session_version or 1)


def test_each_org_gets_its_own_database_and_role(two_orgs: tuple[Any, Any]) -> None:
    a, b = two_orgs
    assert a.db_name != b.db_name
    assert a.db_name.startswith("orgplus_org_") and b.db_name.startswith("orgplus_org_")
    from orgpulse.db import session_scope, use_org

    for org in (a, b):
        with use_org(org), session_scope() as s:
            rows = s.execute(text("SELECT id, domain FROM tenants")).all()
        assert [(r.id, r.domain) for r in rows] == [(org.id, org.domain)]


def test_org_role_cannot_open_another_orgs_database(two_orgs: tuple[Any, Any]) -> None:
    a, b = two_orgs
    with psycopg.connect(_conninfo(a.db_name, a.db_name)) as ok:
        assert ok.execute("SELECT current_user").fetchone() == (a.db_name,)
    for role, db in ((a.db_name, b.db_name), (b.db_name, a.db_name), (a.db_name, CONTROL)):
        with pytest.raises(psycopg.OperationalError, match="permission denied"):
            psycopg.connect(_conninfo(role, db))


def test_org_roles_have_no_special_powers(two_orgs: tuple[Any, Any]) -> None:
    a, b = two_orgs
    with psycopg.connect(_conninfo(a.db_name, a.db_name)) as conn:
        row = conn.execute(
            "SELECT rolsuper, rolcreatedb, rolcreaterole, rolinherit, rolbypassrls "
            "FROM pg_roles WHERE rolname = current_user"
        ).fetchone()
        assert row == (False, False, False, False, False)
        # Nobody else (PUBLIC) may connect to an organisation's database.
        acl = conn.execute(
            "SELECT datacl::text[] FROM pg_database WHERE datname = %s", (b.db_name,)
        ).fetchone()
    assert acl is not None
    assert not any(entry.startswith("=") and "c" in entry.split("/")[0] for entry in acl[0])


def test_secrets_are_sealed_with_each_orgs_own_key(two_orgs: tuple[Any, Any]) -> None:
    a, b = two_orgs
    from orgpulse.db import use_org
    from orgpulse.tenancy import seal, unseal

    with use_org(a):
        sealed_a = seal("alpha-secret")
        assert unseal(sealed_a) == "alpha-secret"
    with use_org(b):
        sealed_b = seal("alpha-secret")
        with pytest.raises(InvalidToken):  # beta's key can't open alpha's secret
            unseal(sealed_a)
    assert sealed_a.startswith("enc:") and sealed_a != sealed_b
    assert "alpha-secret" not in sealed_a


def test_data_keys_are_stored_encrypted(two_orgs: tuple[Any, Any]) -> None:
    from orgpulse import orgs
    from orgpulse.db import control_session

    with control_session() as s:
        keys = [o.data_key_enc for o in s.query(orgs.Org).all()]
    assert len(keys) == 2 and len(set(keys)) == 2
    for k in keys:  # a raw Fernet key is 44 chars of base64; stored ones are ciphertext
        with pytest.raises(ValueError):
            Fernet(k.encode())


def test_requests_are_routed_to_the_signed_in_users_org(two_orgs: tuple[Any, Any]) -> None:
    from fastapi.testclient import TestClient

    from orgpulse.api.main import api

    with TestClient(api) as client:
        for domain in ("alpha.test", "beta.test"):
            r = client.get("/api/me", headers=token(f"head@{domain}", _account(f"head@{domain}")))
            assert r.status_code == 200, r.text
            assert r.json()["domain"] == domain
        r = client.get(
            "/api/me", headers=token("someone@unknown.test", _account("someone@unknown.test"))
        )
        assert r.status_code == 403
        assert "not set up" in r.json()["detail"]
        assert client.get("/api/health").status_code == 200


def test_no_database_without_an_organisation(two_orgs: tuple[Any, Any]) -> None:
    from orgpulse.db import NoOrgSelected, get_engine

    with pytest.raises(NoOrgSelected):
        get_engine()


def test_worker_runs_each_job_once_per_org_in_its_own_context(
    two_orgs: tuple[Any, Any],
) -> None:
    a, b = two_orgs
    from orgpulse import worker
    from orgpulse.db import current_org

    seen: list[tuple[str, uuid.UUID]] = []

    def job(label: str, tenant_id: uuid.UUID) -> None:
        org = current_org()
        assert org is not None and org.id == tenant_id
        seen.append((org.domain, tenant_id))

    worker._each(job, "x")
    assert sorted(seen) == sorted([(a.domain, a.id), (b.domain, b.id)])


# --- Accounts: email + password + authenticator app ------------------------------------------


@pytest.fixture
def outbox(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, str]]:
    """Captures password-reset emails instead of sending them."""
    from orgpulse import mailer

    sent: list[dict[str, str]] = []

    def fake(to: str, subject: str, intro: str, link: str, action: str) -> None:
        sent.append({"to": to, "subject": subject, "token": link.split("token=")[1]})

    monkeypatch.setattr(mailer, "send_link", fake)
    return sent


@pytest.fixture
def client(two_orgs: tuple[Any, Any]) -> Iterator[Any]:
    from fastapi.testclient import TestClient

    from orgpulse.api.main import api

    _clear_caches()
    with TestClient(api) as c:
        yield c


PASSWORD = "Tangerine-Lantern-42"


def _code(secret: str, offset: int = 0) -> str:
    """The authenticator code for now (+offset steps: lets one test sign in twice)."""
    t = pyotp.TOTP(secret)
    return t.generate_otp(t.timecode(datetime.now(UTC)) + offset)


def _enrol(client: Any, email: str, password: str = PASSWORD) -> tuple[str, dict[str, str]]:
    """Sign up and scan the QR code: returns (secret, confirm response)."""
    r = client.post(
        "/api/account/signup", json={"email": email, "name": "Test", "password": password}
    )
    assert r.status_code == 200, r.text
    tok = r.json()["enroll_token"]
    setup = client.post("/api/account/mfa/setup", json={"token": tok}).json()
    assert setup["qr"].startswith("data:image/svg+xml") and setup["uri"].startswith(
        "otpauth://totp/"
    )
    done = client.post(
        "/api/account/mfa/confirm", json={"token": tok, "code": _code(setup["secret"])}
    )
    assert done.status_code == 200, done.text
    return setup["secret"], done.json()


def _login(client: Any, email: str, code: str, password: str = PASSWORD) -> Any:
    return client.post(
        "/api/account/login", json={"email": email, "password": password, "code": code}
    )


def _admin_headers(email: str) -> dict[str, str]:
    return token(email, _account(email))


def test_signup_shows_a_qr_code_and_needs_a_code_to_finish(client: Any) -> None:
    r = client.post(
        "/api/account/signup",
        json={"email": "newbie@alpha.test", "name": "Newbie", "password": "short"},
    )
    assert r.status_code == 400 and r.json()["detail"]["code"] == "weak_password"
    r = client.post(
        "/api/account/signup",
        json={"email": "newbie@alpha.test", "name": "Newbie", "password": PASSWORD},
    )
    tok = r.json()["enroll_token"]
    setup = client.post("/api/account/mfa/setup", json={"token": tok}).json()
    assert "issuer=Org%2B" in setup["uri"] and "newbie%40alpha.test" in setup["uri"]
    bad = client.post("/api/account/mfa/confirm", json={"token": tok, "code": "000000"})
    assert bad.status_code == 400 and bad.json()["detail"]["code"] == "bad_code"
    # Not usable until the authenticator is confirmed.
    assert _login(client, "newbie@alpha.test", _code(setup["secret"])).status_code == 401
    ok = client.post(
        "/api/account/mfa/confirm", json={"token": tok, "code": _code(setup["secret"])}
    )
    assert ok.json() == {"email": "newbie@alpha.test", "status": "active"}
    again = client.post(
        "/api/account/mfa/confirm", json={"token": tok, "code": _code(setup["secret"])}
    )
    assert again.json()["detail"]["code"] == "bad_link"  # single use


def test_new_account_is_active_but_sees_only_what_its_role_allows(client: Any) -> None:
    secret, done = _enrol(client, "waiting@alpha.test")
    assert done["status"] == "active"  # no approval step
    # Not in ORG_ADMINS and not a Workspace admin/manager: the role check still refuses it.
    r = _login(client, "waiting@alpha.test", _code(secret))
    assert r.status_code == 403 and r.json()["detail"]["code"] == "no_access"


def test_admin_signs_in_with_password_and_code(client: Any) -> None:
    secret, done = _enrol(client, "owner@alpha.test")  # in ORG_ADMINS
    assert done["status"] == "active"
    r = _login(client, "OWNER@alpha.test", _code(secret))
    assert r.status_code == 200, r.text
    who = r.json()
    me = client.get("/api/me", headers=token(who["email"], who["sv"]))
    assert me.status_code == 200 and me.json()["domain"] == "alpha.test"
    listed = client.get("/api/accounts", headers=token(who["email"], who["sv"])).json()["accounts"]
    assert listed and all(a["email"].endswith("@alpha.test") for a in listed)  # own org only


def test_sign_in_needs_the_current_code_once(client: Any) -> None:
    secret, _ = _enrol(client, "signer@beta.test")
    wrong = _login(client, "signer@beta.test", "123456")
    missing = _login(client, "signer@beta.test", "")
    bad_pw = _login(client, "signer@beta.test", _code(secret), "Wrong-pass-123")
    unknown = _login(client, "nobody@beta.test", _code(secret))
    assert {r.status_code for r in (wrong, missing, bad_pw, unknown)} == {401}
    assert wrong.json() == bad_pw.json() == unknown.json()  # nothing reveals which part failed
    code = _code(secret, 1)
    assert _login(client, "signer@beta.test", code).status_code == 200
    assert _login(client, "signer@beta.test", code).status_code == 401  # a code works once


def test_failures_lock_the_account(client: Any) -> None:
    secret = "JBSWY3DPEHPK3PXP"
    _account("locky@alpha.test", PASSWORD, secret)
    for _ in range(5):
        assert _login(client, "locky@alpha.test", "000000").status_code in (401, 423)
    r = _login(client, "locky@alpha.test", _code(secret))
    assert r.status_code == 423 and r.json()["detail"]["code"] == "locked"


def test_secrets_are_hashed_or_encrypted(two_orgs: tuple[Any, Any]) -> None:
    from orgpulse import crypto

    with psycopg.connect(_conninfo("postgres", CONTROL)) as c:
        rows = c.execute("SELECT password_hash, totp_secret_enc FROM accounts").fetchall()
        tokens = [r[0] for r in c.execute("SELECT token_hash FROM auth_tokens").fetchall()]
    assert rows and all(h.startswith("$argon2id$") for h, _ in rows if h)
    for _, enc in rows:  # TOTP secrets: ciphertext that only the master key opens
        assert enc and len(crypto.decrypt(enc)) >= 16 and crypto.decrypt(enc) not in enc
    assert all(len(t) == 64 for t in tokens)  # sha256 hex, never the token itself


def test_a_finished_account_cannot_be_signed_up_again(client: Any) -> None:
    _account("taken@alpha.test", PASSWORD)
    r = client.post(
        "/api/account/signup",
        json={"email": "taken@alpha.test", "name": "Impostor", "password": "Impostor-pass-99"},
    )
    assert r.status_code == 409 and r.json()["detail"]["code"] == "exists"


def test_personal_email_cannot_sign_up(client: Any) -> None:
    r = client.post(
        "/api/account/signup", json={"email": "me@gmail.com", "name": "Me", "password": PASSWORD}
    )
    assert r.status_code == 400 and r.json()["detail"]["code"] == "personal_email"


def test_admin_resets_a_lost_authenticator(client: Any) -> None:
    old = "JBSWY3DPEHPK3PXQ"
    sv = _account("phoneless@alpha.test", PASSWORD, old)
    admin = _admin_headers("head@alpha.test")
    row = next(
        a
        for a in client.get("/api/accounts", headers=admin).json()["accounts"]
        if a["email"] == "phoneless@alpha.test"
    )
    path = client.post(f"/api/accounts/{row['id']}/reset-mfa", headers=admin).json()["enroll_path"]
    from orgpulse import accounts

    accounts._session_cache.clear()
    assert client.get("/api/me", headers=token("phoneless@alpha.test", sv)).status_code == 401
    assert _login(client, "phoneless@alpha.test", _code(old)).status_code == 401
    tok = path.split("token=")[1]
    setup = client.post("/api/account/mfa/setup", json={"token": tok}).json()
    assert setup["secret"] != old
    done = client.post(
        "/api/account/mfa/confirm", json={"token": tok, "code": _code(setup["secret"])}
    )
    assert done.json()["status"] == "active"


def test_admins_only_manage_their_own_organisation(client: Any) -> None:
    _account("other@beta.test", PASSWORD)
    from orgpulse import accounts
    from orgpulse.db import control_session

    with control_session() as s:
        beta_id = s.scalar(
            select(accounts.Account.id).where(accounts.Account.email == "other@beta.test")
        )
    admin = _admin_headers("head@alpha.test")
    r = client.post(f"/api/accounts/{beta_id}/reset-mfa", headers=admin)
    assert r.status_code == 404
    assert client.delete(f"/api/accounts/{beta_id}", headers=admin).status_code == 404


def test_password_reset_still_needs_the_code(client: Any, outbox: list[dict[str, str]]) -> None:
    secret = "JBSWY3DPEHPK3PXR"
    sv = _account("forgetful@alpha.test", PASSWORD, secret)
    client.post("/api/account/forgot", json={"email": "forgetful@alpha.test"})
    reset = outbox[-1]["token"]
    new = "Another-Long-Secret-77"
    assert (
        client.post("/api/account/password", json={"token": reset, "password": new}).status_code
        == 200
    )
    from orgpulse import accounts

    accounts._session_cache.clear()
    assert client.get("/api/me", headers=token("forgetful@alpha.test", sv)).status_code == 401
    assert _login(client, "forgetful@alpha.test", "", new).status_code == 401
    assert _login(client, "forgetful@alpha.test", _code(secret), PASSWORD).status_code == 401


def test_new_organisation_signs_up_and_gets_its_own_database(
    client: Any, two_orgs: tuple[Any, Any]
) -> None:
    from orgpulse import orgs
    from orgpulse.db import session_scope, use_org

    secret, done = _enrol(client, "founder@gamma.test")
    assert done["status"] == "active"  # first account of a new organisation
    pending = orgs.org_for_domain("gamma.test")
    assert pending is not None and pending.status == "provisioning"

    r = _login(client, "founder@gamma.test", _code(secret))
    assert r.status_code == 200, r.text
    h = token("founder@gamma.test", r.json()["sv"])
    assert client.get("/api/me", headers=h).json()["provisioning"] is True
    assert client.get("/api/overview", headers=h).status_code == 409

    # The worker (holding the non-superuser provisioning role) creates the database.
    assert orgs.provision_pending() == 1
    ready = orgs.org_for_domain("gamma.test")
    assert ready is not None and ready.ready
    with use_org(ready), session_scope() as s:
        assert s.execute(text("SELECT domain FROM tenants")).scalar() == "gamma.test"
    alpha, _ = two_orgs
    with pytest.raises(psycopg.OperationalError, match="permission denied"):
        psycopg.connect(_conninfo(ready.db_name, alpha.db_name))
    me = client.get("/api/me", headers=h).json()
    assert me["domain"] == "gamma.test" and me["role"] == "admin" and not me.get("provisioning")

    # A colleague from the same organisation is active straight away too.
    _, second = _enrol(client, "colleague@gamma.test")
    assert second["status"] == "active"


def test_only_admins_and_managers_of_a_synced_org_get_in(client: Any) -> None:
    from orgpulse import orgs
    from orgpulse.db import session_scope, use_org

    beta = orgs.org_for_domain("beta.test")
    assert beta is not None
    with use_org(beta), session_scope() as s:
        for email, suspended in (("staff@beta.test", False), ("gone@beta.test", True)):
            s.execute(
                text(
                    "INSERT INTO users (tenant_id, id, primary_email, full_name, suspended)"
                    " VALUES (:t, :g, :e, :e, :s) ON CONFLICT DO NOTHING"
                ),
                {"t": beta.id, "g": email, "e": email, "s": suspended},
            )
    for email in ("staff@beta.test", "gone@beta.test", "stranger@beta.test"):
        secret = pyotp.random_base32()
        _account(email, PASSWORD, secret)
        r = _login(client, email, _code(secret))
        assert r.status_code == 403 and r.json()["detail"]["code"] == "no_access", (email, r.text)
