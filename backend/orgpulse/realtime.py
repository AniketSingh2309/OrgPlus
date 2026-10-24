"""Real-time push: anything that changes data tells every open browser, via Socket.IO.

Any process (API or worker) calls `publish()`, which sends a Postgres NOTIFY. The
API process LISTENs and relays each notice to the Socket.IO room for that tenant,
so no extra broker (Redis etc.) is needed. Notices say *what* changed, never the
data itself; browsers then refetch only what they show, through the normal API.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import threading
import uuid
from typing import Any

import jwt
import socketio
from sqlalchemy import text

from orgpulse.config import get_settings

log = logging.getLogger(__name__)

CHANNEL = "orgplus_events"


def publish(tenant_id: uuid.UUID | str, event: str, **payload: Any) -> None:
    """Fire-and-forget notice to every browser of this tenant. Never raises.

    Multi-org: sent through the control database (NOTIFY doesn't cross databases),
    addressed to the organisation's own room."""
    from orgpulse.db import control_engine, get_engine, multi_org

    message = json.dumps({"tenant": str(tenant_id), "event": event, "data": payload}, default=str)
    try:
        with (control_engine() if multi_org() else get_engine()).connect() as conn:
            conn.execute(text("SELECT pg_notify(:c, :m)"), {"c": CHANNEL, "m": message})
            conn.commit()
    except Exception as err:
        log.debug("realtime publish failed: %s", err)


def _origins() -> list[str] | str:
    s = get_settings()
    origins = [o.strip().rstrip("/") for o in s.web_origins.split(",") if o.strip()]
    return origins or "*"


sio = socketio.AsyncServer(
    async_mode="asgi", cors_allowed_origins=_origins(), logger=False, engineio_logger=False
)


async def connect(sid: str, environ: dict[str, Any], auth: dict[str, Any] | None) -> bool:
    """Same check as the REST API: a short-lived token signed by the web app, our domain only."""
    from orgpulse.api.deps import JWT_AUDIENCE
    from orgpulse.tenancy import default_tenant_id

    settings = get_settings()
    token = (auth or {}).get("token")
    if not token or not settings.nextauth_secret:
        return False
    try:
        claims = jwt.decode(
            token, settings.nextauth_secret, algorithms=["HS256"], audience=JWT_AUDIENCE
        )
    except jwt.PyJWTError:
        return False
    email = str(claims.get("email", "")).lower()
    domain = email.split("@")[-1]
    from orgpulse.db import multi_org

    if multi_org():
        from orgpulse.accounts import session_valid
        from orgpulse.orgs import org_for_domain

        if not settings.dev_auth_bypass and not await asyncio.to_thread(
            session_valid, email, claims.get("sv")
        ):
            return False  # account gone or password changed since sign-in
        org = await asyncio.to_thread(org_for_domain, domain)  # each org in its own room
        if org is None:
            return False
        tenant = str(org.id)
    else:
        if not settings.allowed_domain or domain != settings.allowed_domain.lower():
            return False
        tenant = str(default_tenant_id())
    await sio.enter_room(sid, tenant)
    await sio.save_session(sid, {"email": email, "tenant": tenant})
    log.debug("socket %s connected for %s", sid, email)
    return True


sio.on("connect", connect)


def _listen_forever(loop: asyncio.AbstractEventLoop, stop: threading.Event) -> None:
    """Blocking LISTEN in a thread (psycopg's async mode can't run on Windows' default
    event loop); each notice is handed to the API's event loop to emit."""
    import psycopg

    settings = get_settings()
    url = settings.control_database_url or settings.database_url
    url = url.replace("postgresql+psycopg://", "postgresql://")
    while not stop.is_set():
        try:
            with psycopg.connect(url, autocommit=True) as conn:
                conn.execute(f"LISTEN {CHANNEL}")
                log.info("realtime relay listening")
                while not stop.is_set():
                    for note in conn.notifies(timeout=1.0):
                        try:
                            msg = json.loads(note.payload)
                        except ValueError:
                            continue
                        asyncio.run_coroutine_threadsafe(
                            sio.emit(msg["event"], msg.get("data", {}), room=msg["tenant"]), loop
                        )
        except Exception as err:
            if stop.wait(5):
                return
            log.warning("realtime relay reconnecting after: %s", err)


@contextlib.asynccontextmanager
async def relay() -> Any:
    stop = threading.Event()
    thread = threading.Thread(
        target=_listen_forever,
        args=(asyncio.get_running_loop(), stop),
        name="realtime-relay",
        daemon=True,
    )
    thread.start()
    try:
        yield
    finally:
        stop.set()
        await asyncio.to_thread(thread.join, 3)
