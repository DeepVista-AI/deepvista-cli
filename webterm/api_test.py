"""End-to-end checks for the server: HTTP API, multiplexed socket, persistence.

cd webterm && uv run --with aiohttp python api_test.py
"""

from __future__ import annotations

import asyncio
import socket
import sys

import aiohttp
import server
import wire
from aiohttp import web

TOKEN = "test-token"
results: list[tuple[bool, str]] = []


def check(ok: object, label: str) -> None:
    results.append((bool(ok), label))
    print(f"  {'PASS' if ok else 'FAIL'}  {label}", flush=True)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Client:
    """A browser stand-in: one socket, many sessions, offsets tracked per session."""

    def __init__(self, session: aiohttp.ClientSession, base: str) -> None:
        self.http = session
        self.base = base
        self.ws: aiohttp.ClientWebSocketResponse | None = None
        self.text: dict[str, str] = {}
        self.offsets: dict[str, int] = {}
        self.ctrl: list[dict] = []
        self._pump: asyncio.Task | None = None

    async def open(self) -> None:
        self.ws = await self.http.ws_connect(f"{self.base}/ws?token={TOKEN}")
        self._pump = asyncio.create_task(self._read())

    async def close(self) -> None:
        if self._pump:
            self._pump.cancel()
        if self.ws:
            await self.ws.close()

    async def _read(self) -> None:
        assert self.ws is not None
        async for msg in self.ws:
            if msg.type is aiohttp.WSMsgType.BINARY:
                _, sid, offset, payload = wire.decode_data(msg.data)
                self.text[sid] = self.text.get(sid, "") + payload.decode("utf-8", "replace")
                self.offsets[sid] = offset + len(payload)
            elif msg.type is aiohttp.WSMsgType.TEXT:
                self.ctrl.append(wire.decode_ctrl(msg.data))

    async def attach(self, sid: str, resume_from: int | None = None) -> None:
        assert self.ws is not None
        await self.ws.send_str(wire.encode_ctrl(t="attach", session=sid, **{"from": resume_from}))

    async def type(self, sid: str, keys: str) -> None:
        assert self.ws is not None
        await self.ws.send_bytes(wire.encode_data(wire.INPUT, sid, 0, keys.encode()))

    async def resize(self, sid: str, rows: int, cols: int) -> None:
        assert self.ws is not None
        await self.ws.send_str(wire.encode_ctrl(t="resize", session=sid, rows=rows, cols=cols))

    async def wait_for(self, sid: str, needle: str, timeout: float = 6.0) -> bool:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while loop.time() < deadline:
            if needle in self.text.get(sid, ""):
                return True
            await asyncio.sleep(0.05)
        return False

    async def new_session(self, command: str | None = None, name: str | None = None) -> dict:
        async with self.http.post(
            f"{self.base}/api/sessions?token={TOKEN}", json={"command": command, "name": name, "rows": 24, "cols": 80}
        ) as response:
            return await response.json()

    async def sessions(self) -> list[dict]:
        async with self.http.get(f"{self.base}/api/sessions?token={TOKEN}") as response:
            return (await response.json())["sessions"]

    async def kill(self, sid: str) -> int:
        async with self.http.delete(f"{self.base}/api/sessions/{sid}?token={TOKEN}") as response:
            return response.status


def overflow_check() -> None:
    """The backpressure path, exercised directly — a slow client must be resynced,
    not fed a backlog it no longer needs."""

    class StubWS:
        pass

    store = server.SessionStore(["/bin/sh"], "/tmp")
    conn = server.Connection(StubWS(), store)  # type: ignore[arg-type]
    conn.queue = asyncio.Queue(maxsize=4)
    conn.attached.add("s")
    for i in range(20):
        conn.on_output("s", i * 10, b"x" * 10)
    drained = []
    while not conn.queue.empty():
        drained.append(conn.queue.get_nowait())
    check(
        "s" in conn.overflowed or any(isinstance(f, str) and "resync" in f for f in drained), "slow client is flagged"
    )
    check(
        any(isinstance(f, str) and wire.decode_ctrl(f).get("t") == "resync" for f in drained),
        "a resync instruction is queued instead of a backlog",
    )
    check(len(drained) <= 5, f"the backlog is dropped rather than buffered (queued {len(drained)})")


async def scenarios(base: str) -> None:
    async with aiohttp.ClientSession() as http:
        print("\n1) the endpoint is not open to the world", flush=True)
        async with http.get(f"{base}/api/sessions") as response:
            check(response.status == 401, "no token, no session list")
        async with http.get(f"{base}/") as response:
            check(response.status == 401, "no token, no page")
        async with http.get(f"{base}/?token={TOKEN}") as response:
            check(response.status == 200 and "xterm" in await response.text(), "the page loads with a token")
            check(server.COOKIE in response.headers.get("set-cookie", ""), "the token is moved into a cookie")

        client = Client(http, base)
        await client.open()

        print("\n2) sessions are created and driven over one socket", flush=True)
        first = await client.new_session(name="one")
        second = await client.new_session(command="/bin/sh", name="two")
        await client.attach(first["id"])
        await client.attach(second["id"])
        await client.type(first["id"], "echo FROM_FIRST\n")
        await client.type(second["id"], "echo FROM_SECOND\n")
        check(await client.wait_for(first["id"], "FROM_FIRST"), "first session responds")
        check(await client.wait_for(second["id"], "FROM_SECOND"), "second session responds")
        check("FROM_SECOND" not in client.text[first["id"]], "output is routed to the right session, not broadcast")
        check(len(await client.sessions()) == 2, "both sessions are listed")

        print("\n3) resize reaches the tty", flush=True)
        await client.resize(first["id"], 44, 132)
        await asyncio.sleep(0.2)
        await client.type(first["id"], "stty size\n")
        check(await client.wait_for(first["id"], "44 132"), "stty size reports the browser's geometry")

        print("\n4) closing the browser does not close the session", flush=True)
        await client.type(first["id"], "MARK=still_here\n")
        await client.type(first["id"], "(sleep 1.5; printf 'LATER%s\\n' _OUTPUT) &\n")
        warm_offset = client.offsets[first["id"]]
        await client.close()  # the whole socket goes away, as when a tab is closed
        await asyncio.sleep(2.5)

        reopened = Client(http, base)
        await reopened.open()
        check(len(await reopened.sessions()) == 2, "sessions survive with no clients attached")

        print("\n5) a fresh page is painted from a tail of raw stream (cold attach)", flush=True)
        await reopened.attach(first["id"], resume_from=None)
        check(await reopened.wait_for(first["id"], "FROM_FIRST"), "earlier scrollback is repainted")
        check(await reopened.wait_for(first["id"], "LATER_OUTPUT"), "output produced while away is there too")
        check(
            any(c.get("t") == "attached" and c.get("cold") for c in reopened.ctrl),
            "the server marks the attach as cold so the client resets first",
        )

        print("\n6) a reconnect resumes at the byte offset (warm attach)", flush=True)
        warm = Client(http, base)
        await warm.open()
        await warm.attach(first["id"], resume_from=warm_offset)
        check(await warm.wait_for(first["id"], "LATER_OUTPUT"), "only-missed output arrives")
        check("FROM_FIRST" not in warm.text.get(first["id"], ""), "already-seen bytes are not resent")

        print("\n7) the same shell process is still there", flush=True)
        await warm.type(first["id"], "echo mark=$MARK\n")
        check(await warm.wait_for(first["id"], "mark=still_here"), "shell state survived every disconnect")

        print("\n8) closing a session is explicit and propagates", flush=True)
        check(await warm.kill(second["id"]) == 200, "kill returns ok")
        await asyncio.sleep(0.3)
        remaining = await warm.sessions()
        check(len(remaining) == 1 and remaining[0]["id"] == first["id"], "only the killed session went away")
        check(
            any(c.get("t") == "sessions" and len(c.get("list", [])) == 1 for c in warm.ctrl),
            "other tabs are told the list changed",
        )
        check(await warm.kill("nope") == 404, "killing an unknown session is a 404")

        print("\n9) profiles include the shell and any ssh hosts", flush=True)
        async with http.get(f"{base}/api/profiles?token={TOKEN}") as response:
            profiles = (await response.json())["profiles"]
        check(any(p["kind"] == "shell" for p in profiles), f"a shell profile is offered ({len(profiles)} total)")

        await warm.close()
        await reopened.close()

    print("\n10) a slow client is resynced, not backlogged", flush=True)
    overflow_check()


async def main() -> int:
    port = free_port()
    app = server.build_app(TOKEN, ["/bin/sh"], "/tmp")
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", port)
    await site.start()
    try:
        await scenarios(f"http://127.0.0.1:{port}")
    finally:
        await runner.cleanup()

    failed = [label for ok, label in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed", flush=True)
    for label in failed:
        print(f"  FAILED: {label}", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
