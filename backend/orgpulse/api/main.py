"""FastAPI app: wires the core routers and every registered feature module."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, cast

import socketio
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from orgpulse import realtime
from orgpulse.api.deps import decode_session
from orgpulse.api.routers import account, admin, exports, insights, org, overview, people
from orgpulse.config import get_settings
from orgpulse.db import control_engine, multi_org, ping, use_org
from orgpulse.features.registry import load_modules
from orgpulse.logging_setup import setup_logging
from orgpulse.tenancy import ensure_default_tenant

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    setup_logging()
    if multi_org():
        from orgpulse.accounts import ensure_schema

        ensure_schema(control_engine())  # control tables + newer columns (idempotent)
        if get_settings().admin_database_url:
            log.warning(
                "ADMIN_DATABASE_URL is visible to the API. Only the worker needs it: set it in "
                "the worker's environment, not in the shared .env"
            )
    else:
        ensure_default_tenant()
    async with realtime.relay():  # Postgres NOTIFY -> Socket.IO
        yield


api = FastAPI(title="Org+ API", version="1.0.0", lifespan=lifespan)


@api.middleware("http")
async def route_to_org(request: Request, call_next: Any) -> Response:
    """Multi-org: run each request against the signed-in user's organisation database only.

    The organisation comes from the verified session token's email domain; unknown
    domains are refused before any database is touched."""
    path = request.url.path
    if (
        not multi_org()
        or not path.startswith("/api/")
        or path == "/api/health"
        or path.startswith("/api/account/")  # public: sign-up, sign-in, password links
    ):
        return cast(Response, await call_next(request))
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        return JSONResponse({"detail": "sign in required"}, status_code=401)
    try:
        claims = decode_session(auth.split(" ", 1)[1])
    except HTTPException as err:
        return JSONResponse({"detail": err.detail}, status_code=err.status_code)
    email = str(claims.get("email", "")).lower()
    from orgpulse.accounts import session_valid
    from orgpulse.orgs import org_for_domain

    # The account must still exist and must not have changed its password since sign-in.
    if not get_settings().dev_auth_bypass and not await run_in_threadpool(
        session_valid, email, claims.get("sv")
    ):
        return JSONResponse({"detail": "session expired: sign in again"}, status_code=401)
    org = await run_in_threadpool(org_for_domain, email.split("@")[-1])
    if org is None:
        return JSONResponse({"detail": "this organisation is not set up in Org+"}, status_code=403)
    if not org.ready:
        # Just signed up: the worker is creating this organisation's private database.
        if path == "/api/me":
            return JSONResponse(
                _provisioning_me(email, str(claims.get("name") or email), org.domain)
            )
        return JSONResponse(
            {"detail": "your organisation's private database is still being set up"},
            status_code=409,
        )
    with use_org(org):
        return cast(Response, await call_next(request))


def _provisioning_me(email: str, name: str, domain: str) -> dict[str, Any]:
    return {
        "email": email,
        "name": name,
        "role": "admin",
        "domain": domain,
        "connected": False,
        "provisioning": True,
        "plan_badge": "",
        "hide_locked": False,
        "sync": {"last_synced": None, "running": [], "errors": {}},
    }


for r in (
    account.router,
    account.admin_router,
    overview.router,
    people.router,
    org.router,
    admin.router,
    insights.router,
    exports.router,
):
    api.include_router(r)

for module in load_modules().values():
    if module.router is not None:
        api.include_router(module.router)


@api.get("/api/health")
def health() -> dict[str, str]:
    try:
        ping()
    except Exception as err:
        log.error("database ping failed: %s", err)
        raise HTTPException(status_code=503, detail="database unavailable") from err
    return {"status": "ok"}


# Socket.IO at /socket.io, everything else goes to FastAPI (lifespan included).
app = socketio.ASGIApp(realtime.sio, other_asgi_app=api, socketio_path="socket.io")
