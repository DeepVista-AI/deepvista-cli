"""A full web terminal: multiple persistent sessions, one multiplexed socket.

    uv run --with aiohttp python webterm/server.py

Prints a URL with a one-time token. Open it, get tabs. Close the browser, come
back, and the tabs are still there with their scrollback — the sessions live in
this process, not in the page.

Design notes:

* **One WebSocket for every tab.** Frames carry a session id, so N terminals
  share one connection, one heartbeat and one reconnect path. N sockets would
  mean N independent things to go wrong on a flaky link.
* **The server never blocks on a slow client.** Each connection has a bounded
  outbound queue; if a client cannot keep up with a `yes`-style flood, its
  queue is dropped and it is told to resync from a fresh tail rather than being
  fed a backlog it no longer needs.
* **Loopback-only by default**, because this endpoint is a shell.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import os
import re
import secrets
import shutil
import sys
from pathlib import Path

import wire
from aiohttp import WSMsgType, web
from sessions import SessionStore

STATIC = Path(__file__).parent / "static"
QUEUE_LIMIT = 512  # outbound chunks buffered per connection before we resync it
COOKIE = "webterm_token"


# --------------------------------------------------------------------------- #
# connections
# --------------------------------------------------------------------------- #


class Connection:
    """One browser tab-set: a socket, the sessions it watches, an outbound queue."""

    def __init__(self, ws: web.WebSocketResponse, store: SessionStore) -> None:
        self.ws = ws
        self.store = store
        self.queue: asyncio.Queue[bytes | str] = asyncio.Queue(maxsize=QUEUE_LIMIT)
        self.attached: set[str] = set()
        self.overflowed: set[str] = set()

    # Called from the PTY reader (sync context) — must never block or await.
    def on_output(self, session_id: str, offset: int, data: bytes) -> None:
        if session_id not in self.attached:
            return
        try:
            self.queue.put_nowait(wire.encode_data(wire.OUTPUT, session_id, offset, data))
        except asyncio.QueueFull:
            self.overflowed.add(session_id)
            self._drop_queued()
            with contextlib.suppress(asyncio.QueueFull):
                self.queue.put_nowait(wire.encode_ctrl(t="resync", session=session_id))

    def _drop_queued(self) -> None:
        while True:
            try:
                self.queue.get_nowait()
            except asyncio.QueueEmpty:
                return

    def send_soon(self, frame: bytes | str) -> None:
        with contextlib.suppress(asyncio.QueueFull):
            self.queue.put_nowait(frame)

    async def writer(self) -> None:
        while True:
            frame = await self.queue.get()
            if isinstance(frame, bytes):
                await self.ws.send_bytes(frame)
            else:
                await self.ws.send_str(frame)
            # An overflowed session gets a fresh tail instead of the backlog.
            for session_id in list(self.overflowed):
                self.overflowed.discard(session_id)
                session = self.store.get(session_id)
                if session:
                    start, tail = session.cold_tail()
                    await self.ws.send_bytes(wire.encode_data(wire.OUTPUT, session_id, start, tail))

    def attach(self, session_id: str) -> None:
        session = self.store.get(session_id)
        if session is None:
            return
        self.attached.add(session_id)
        session.listeners.add(self.on_output)

    def detach(self, session_id: str) -> None:
        self.attached.discard(session_id)
        session = self.store.get(session_id)
        if session:
            session.listeners.discard(self.on_output)

    def detach_all(self) -> None:
        for session_id in list(self.attached):
            self.detach(session_id)


CONNECTIONS: set[Connection] = set()


def broadcast_sessions(store: SessionStore) -> None:
    """Tell every open tab-set that the session list changed."""
    frame = wire.encode_ctrl(t="sessions", list=store.list())
    for conn in CONNECTIONS:
        conn.send_soon(frame)


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #


def _authorized(request: web.Request) -> bool:
    token = request.app["token"]
    supplied = request.query.get("token") or request.cookies.get(COOKIE) or ""
    return secrets.compare_digest(supplied, token)


@web.middleware
async def auth_middleware(request: web.Request, handler):
    if request.path.startswith(("/api/", "/ws")) and not _authorized(request):
        raise web.HTTPUnauthorized(text="bad or missing token")
    return await handler(request)


async def index(request: web.Request) -> web.StreamResponse:
    if not _authorized(request):
        return web.Response(status=401, text="append ?token=… to this URL")
    response = web.FileResponse(STATIC / "index.html")
    # Hand the token to the cookie jar so refreshes and the WS upgrade work
    # without keeping the secret in the address bar.
    response.set_cookie(COOKIE, request.app["token"], httponly=True, samesite="Strict", path="/")
    return response


async def list_sessions(request: web.Request) -> web.Response:
    return web.json_response({"sessions": request.app["store"].list()})


async def create_session(request: web.Request) -> web.Response:
    body = await request.json() if request.can_read_body else {}
    store: SessionStore = request.app["store"]
    command = body.get("command")
    argv = command.split() if isinstance(command, str) and command.strip() else None
    cwd = body.get("cwd") or None
    if cwd and not Path(cwd).is_dir():
        raise web.HTTPBadRequest(text=f"no such directory: {cwd}")
    session = store.create(
        name=body.get("name"),
        command=argv,
        cwd=cwd,
        rows=int(body.get("rows") or 24),
        cols=int(body.get("cols") or 80),
    )
    broadcast_sessions(store)
    return web.json_response(session.meta())


async def delete_session(request: web.Request) -> web.Response:
    store: SessionStore = request.app["store"]
    if not store.close(request.match_info["session_id"]):
        raise web.HTTPNotFound(text="no such session")
    broadcast_sessions(store)
    return web.json_response({"ok": True})


def ssh_hosts() -> list[dict]:
    """Offer one-click tabs for the hosts already in ~/.ssh/config."""
    config = Path.home() / ".ssh" / "config"
    if not config.is_file():
        return []
    hosts: list[str] = []
    with contextlib.suppress(OSError):
        for line in config.read_text(errors="replace").splitlines():
            match = re.match(r"^\s*Host\s+(.+)$", line, re.IGNORECASE)
            if not match:
                continue
            hosts += [h for h in match.group(1).split() if "*" not in h and "?" not in h]
    seen: list[dict] = []
    for host in dict.fromkeys(hosts):
        seen.append({"name": host, "command": f"ssh {host}", "kind": "ssh"})
    return seen


async def list_profiles(request: web.Request) -> web.Response:
    store: SessionStore = request.app["store"]
    profiles = [{"name": "shell", "command": " ".join(store.default_command), "kind": "shell"}]
    for extra in ("bash", "zsh", "fish"):
        found = shutil.which(extra)
        if found and found not in store.default_command:
            profiles.append({"name": extra, "command": found, "kind": "shell"})
    return web.json_response({"profiles": profiles + ssh_hosts()})


# --------------------------------------------------------------------------- #
# WebSocket
# --------------------------------------------------------------------------- #


async def websocket(request: web.Request) -> web.WebSocketResponse:
    # heartbeat: aiohttp pings, and drops the socket if pongs stop — this is how
    # a phone that walked out of wifi range gets cleaned up promptly.
    ws = web.WebSocketResponse(heartbeat=20, max_msg_size=8 * 1024 * 1024)
    await ws.prepare(request)
    store: SessionStore = request.app["store"]
    conn = Connection(ws, store)
    CONNECTIONS.add(conn)
    writer = asyncio.create_task(conn.writer())
    conn.send_soon(wire.encode_ctrl(t="sessions", list=store.list()))

    try:
        async for msg in ws:
            if msg.type is WSMsgType.BINARY:
                kind, session_id, _, payload = wire.decode_data(msg.data)
                if kind == wire.INPUT:
                    session = store.get(session_id)
                    if session:
                        session.write(payload)
            elif msg.type is WSMsgType.TEXT:
                await _handle_ctrl(conn, store, wire.decode_ctrl(msg.data))
            elif msg.type is WSMsgType.ERROR:
                break
    finally:
        writer.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await writer
        conn.detach_all()
        CONNECTIONS.discard(conn)
    return ws


async def _handle_ctrl(conn: Connection, store: SessionStore, msg: dict) -> None:
    kind = msg.get("t")
    session_id = str(msg.get("session", ""))
    session = store.get(session_id)

    if kind == "attach":
        if session is None:
            conn.send_soon(wire.encode_ctrl(t="gone", session=session_id))
            return
        conn.attach(session_id)
        if msg.get("rows") and msg.get("cols"):
            session.resize(int(msg["rows"]), int(msg["cols"]))
        resume_from = msg.get("from")
        if resume_from is None:  # cold attach: paint from a tail of raw stream
            start, data = session.cold_tail()
            cold = True
        else:
            start, data, truncated = session.slice_from(int(resume_from))
            cold = False
            if truncated:
                conn.send_soon(
                    wire.encode_ctrl(t="gap", session=session_id, **{"from": resume_from, "resumed_at": start})
                )
        conn.send_soon(wire.encode_ctrl(t="attached", session=session_id, offset=session.total, cold=cold))
        if data:
            conn.send_soon(wire.encode_data(wire.OUTPUT, session_id, start, data))
        if not session.alive:
            conn.send_soon(wire.encode_ctrl(t="exit", session=session_id, exit_code=session.exit_code))

    elif kind == "detach":
        conn.detach(session_id)

    elif kind == "resize" and session is not None:
        session.resize(int(msg.get("rows", 0)), int(msg.get("cols", 0)))

    elif kind == "ping":
        conn.send_soon(wire.encode_ctrl(t="pong", ts=msg.get("ts")))


# --------------------------------------------------------------------------- #
# wiring
# --------------------------------------------------------------------------- #


def build_app(token: str, command: list[str] | None = None, cwd: str | None = None) -> web.Application:
    app = web.Application(middlewares=[auth_middleware])
    app["token"] = token
    app["store"] = SessionStore(
        default_command=command or [os.environ.get("SHELL") or "/bin/bash"],
        default_cwd=cwd or str(Path.cwd()),
    )
    app.add_routes(
        [
            web.get("/", index),
            web.get("/api/sessions", list_sessions),
            web.post("/api/sessions", create_session),
            web.delete("/api/sessions/{session_id}", delete_session),
            web.get("/api/profiles", list_profiles),
            web.get("/ws", websocket),
            web.static("/static", STATIC),
        ]
    )

    async def _cleanup(app: web.Application) -> None:
        app["store"].shutdown()

    app.on_cleanup.append(_cleanup)
    return app


def main() -> int:
    ap = argparse.ArgumentParser(description="Persistent multi-session web terminal.")
    ap.add_argument("--host", default="127.0.0.1", help="bind address (default loopback only)")
    ap.add_argument("--port", type=int, default=7681)
    ap.add_argument("--token", default=os.environ.get("WEBTERM_TOKEN"), help="access token (generated if omitted)")
    ap.add_argument("--command", default=None, help="default shell for new sessions")
    ap.add_argument("--cwd", default=None, help="default working directory for new sessions")
    args = ap.parse_args()

    loopback = args.host in ("127.0.0.1", "::1", "localhost")
    if not loopback and not args.token:
        print(
            "refusing to serve a shell on a non-loopback address without --token.\n"
            "even with one, put this behind TLS and an authenticating proxy.",
            file=sys.stderr,
        )
        return 2
    token = args.token or secrets.token_urlsafe(24)

    app = build_app(token, [args.command] if args.command else None, args.cwd)
    print(f"\n  web terminal:  http://{args.host}:{args.port}/?token={token}\n", flush=True)
    if not loopback:
        print("  warning: reachable off-box. anyone with the token gets a shell.\n", flush=True)
    web.run_app(app, host=args.host, port=args.port, print=None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
