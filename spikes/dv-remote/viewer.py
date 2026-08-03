"""Headless viewer — the part a browser's xterm.js would do.

Used directly by the end-to-end test; ``python viewer.py`` also gives a crude
interactive client for poking at a session by hand.
"""

import argparse
import asyncio
import contextlib
import sys

import wire
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed


class Viewer:
    """Attaches to one session and accumulates everything it is sent."""

    def __init__(self, relay: str, machine: str, session: str, token: str, resume_from: int = 0) -> None:
        self.url = f"{relay}/view?machine={machine}&session={session}&from={resume_from}&token={token}"
        self.session = session
        self.output = bytearray()
        self.offset = resume_from  # last byte we have, for the next resume
        self.gaps: list[dict] = []
        self.ws = None
        self._pump: asyncio.Task | None = None

    async def __aenter__(self) -> "Viewer":
        self._cm = connect(self.url, max_size=None)
        self.ws = await self._cm.__aenter__()
        self._pump = asyncio.create_task(self._read())
        return self

    async def __aexit__(self, *exc) -> None:
        if self._pump:
            self._pump.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._pump
        await self._cm.__aexit__(*exc)

    async def _read(self) -> None:
        assert self.ws is not None
        with contextlib.suppress(ConnectionClosed, asyncio.CancelledError):
            async for frame in self.ws:
                if isinstance(frame, bytes):
                    kind, _, offset, payload = wire.decode_data(frame)
                    if kind == wire.OUTPUT:
                        self.output += payload
                        self.offset = offset + len(payload)
                else:
                    msg = wire.decode_ctrl(frame)
                    if msg.get("t") == "gap":
                        self.gaps.append(msg)
                    elif msg.get("t") == "attached":
                        self.offset = max(self.offset, 0)

    async def send(self, keys: str) -> None:
        assert self.ws is not None
        await self.ws.send(wire.encode_data(wire.INPUT, self.session, 0, keys.encode()))

    async def resize(self, rows: int, cols: int) -> None:
        assert self.ws is not None
        await self.ws.send(wire.encode_ctrl(t="resize", session=self.session, rows=rows, cols=cols))

    def text(self) -> str:
        return self.output.decode("utf-8", "replace")

    async def wait_for(self, needle: str, timeout: float = 5.0) -> bool:
        """Poll the accumulated output — the assertion primitive for the tests."""
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            if needle in self.text():
                return True
            await asyncio.sleep(0.05)
        return False


async def _interactive(args: argparse.Namespace) -> None:
    async with Viewer(args.relay, args.machine, args.session, args.token, args.resume_from) as viewer:
        loop = asyncio.get_running_loop()
        printed = 0

        async def drain() -> None:
            nonlocal printed
            while True:
                if len(viewer.output) > printed:
                    sys.stdout.write(viewer.output[printed:].decode("utf-8", "replace"))
                    sys.stdout.flush()
                    printed = len(viewer.output)
                await asyncio.sleep(0.05)

        asyncio.create_task(drain())
        while True:
            line = await loop.run_in_executor(None, sys.stdin.readline)
            if not line:
                break
            await viewer.send(line)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--relay", default="ws://127.0.0.1:8787")
    ap.add_argument("--machine", default="mac-01")
    ap.add_argument("--session", default="default")
    ap.add_argument("--token", default="dev-token")
    ap.add_argument("--from", dest="resume_from", type=int, default=0)
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(_interactive(ap.parse_args()))
