"""Real-time push end to end: a real server, a real Socket.IO client, a NOTIFY from "another process"."""

from __future__ import annotations

import os
import socket
import threading
import time
from collections.abc import Iterator

import jwt
import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not set"
)


WEB_APP = "http://localhost:3000"  # the Org+ web app (default WEB_ORIGINS)
# python's websocket client always sends the server's own address as Origin, so the
# test server also allows that address (as a deployment allows its web app's address).
TRANSPORT = ["websocket"]
WEB: dict[str, str] = {}


def _token(email: str) -> str:
    claims = {"email": email, "name": email, "aud": "orgpulse-api", "exp": int(time.time()) + 300}
    return jwt.encode(claims, os.environ["NEXTAUTH_SECRET"], algorithm="HS256")


@pytest.fixture(scope="module")
def server() -> Iterator[str]:
    import uvicorn

    os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]
    from orgpulse.config import get_settings
    from orgpulse.db import _session_factory, get_engine
    from orgpulse.tenancy import default_tenant_id

    for cached in (get_settings, get_engine, _session_factory, default_tenant_id):
        cached.cache_clear()
    from orgpulse import realtime
    from orgpulse.api.main import app

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=srv.run, daemon=True)
    thread.start()
    for _ in range(100):
        if srv.started:
            break
        time.sleep(0.1)
    time.sleep(1.0)  # let the LISTEN relay connect
    url = f"http://127.0.0.1:{port}"
    realtime.sio.eio.cors_allowed_origins = [WEB_APP, url]
    yield url
    srv.should_exit = True
    thread.join(5)


def test_rejects_missing_or_foreign_tokens(server: str) -> None:
    import socketio

    for auth in (None, {"token": "not-a-jwt"}, {"token": _token("someone@gmail.com")}):
        client = socketio.Client()
        with pytest.raises(socketio.exceptions.ConnectionError):
            client.connect(server, auth=auth, headers=WEB, transports=TRANSPORT, wait_timeout=5)
        client.disconnect()


def test_rejects_other_websites_even_with_a_valid_token(server: str) -> None:
    import socketio

    from orgpulse import realtime

    # Only the web app may connect; the test client's address now counts as "another website".
    realtime.sio.eio.cors_allowed_origins = [WEB_APP]
    client = socketio.Client()
    with pytest.raises(socketio.exceptions.ConnectionError):
        client.connect(
            server,
            auth={"token": _token("head@example.com")},
            transports=TRANSPORT,
            wait_timeout=5,
        )
    client.disconnect()
    realtime.sio.eio.cors_allowed_origins = [WEB_APP, server]


def test_sync_status_changes_are_pushed_live(server: str) -> None:
    import socketio

    from orgpulse.sync import state
    from orgpulse.tenancy import default_tenant_id

    received: list[dict[str, object]] = []
    got = threading.Event()
    client = socketio.Client()

    @client.on("sync")
    def on_sync(data: dict[str, object]) -> None:
        received.append(data)
        if data.get("key") == "events:login" and data.get("status") == "ok":
            got.set()

    client.connect(
        server,
        auth={"token": _token("head@example.com")},
        headers=WEB,
        transports=TRANSPORT,
        wait_timeout=5,
    )
    try:
        state.mark_ok(
            default_tenant_id(), "events:login"
        )  # what a worker process does after a sync
        assert got.wait(10), f"no live update received (got {received})"
    finally:
        client.disconnect()
