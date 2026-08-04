"""Machine agent: owns the PTYs, dials out to the relay, replays on resume.

Everything that matters happens here, on the developer's machine:

* the child process (a shell, ``claude``, ``codex``, ...) is spawned under a PTY
  and keeps running whether or not anyone is watching;
* output is appended to a bounded ring buffer tagged with absolute byte
  offsets, so a viewer that reconnects gets exactly the bytes it missed;
* the only network socket is the outbound WebSocket to the relay.

    uv run --with websockets python agent.py --machine mac-01 --relay ws://127.0.0.1:8787
"""

import argparse
import asyncio
import contextlib
import fcntl
import os
import pty
import signal
import struct
import subprocess
import termios

import wire
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

RING_BYTES = 256 * 1024  # scrollback kept for resume; a real build persists this
READ_CHUNK = 65536


class Session:
    """A live PTY plus the scrollback needed to answer a resume request."""

    def __init__(self, session_id: str, command: list[str], rows: int, cols: int) -> None:
        self.id = session_id
        self.ring = bytearray()
        self.total = 0  # absolute bytes ever written by the child
        master, slave = pty.openpty()
        self.master = master
        _set_winsize(master, rows, cols)
        self.proc = subprocess.Popen(  # noqa: S603 - spawning the user's own shell is the point
            command,
            stdin=slave,
            stdout=slave,
            stderr=slave,
            start_new_session=True,
            # start_new_session gives the child its own session but not a
            # controlling terminal; without TIOCSCTTY the shell reports
            # "can't access tty; job control turned off" and ^C/^Z never work.
            # Interactive agents care about this, so claim the tty explicitly.
            preexec_fn=_claim_controlling_tty,  # noqa: PLW1509 - single-threaded child setup
            env={**os.environ, "TERM": "xterm-256color"},
        )
        os.close(slave)
        os.set_blocking(master, False)

    @property
    def base_offset(self) -> int:
        """Absolute offset of the first byte still held in the ring."""
        return self.total - len(self.ring)

    def append(self, data: bytes) -> int:
        """Record `data` and return the absolute offset it starts at."""
        offset = self.total
        self.ring += data
        self.total += len(data)
        if len(self.ring) > RING_BYTES:
            del self.ring[: len(self.ring) - RING_BYTES]
        return offset

    def slice_from(self, offset: int) -> tuple[bytes, int, bool]:
        """Bytes from `offset` onward, their true start offset, and whether we truncated."""
        if offset >= self.total:
            return b"", self.total, False
        if offset < self.base_offset:
            return bytes(self.ring), self.base_offset, True
        return bytes(self.ring[offset - self.base_offset :]), offset, False

    def close(self) -> None:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(os.getpgid(self.proc.pid), signal.SIGTERM)
        with contextlib.suppress(OSError):
            os.close(self.master)


def _claim_controlling_tty() -> None:
    """Runs in the forked child: make its stdin (the PTY slave) the controlling tty."""
    with contextlib.suppress(OSError, AttributeError):
        fcntl.ioctl(0, termios.TIOCSCTTY, 0)


def _set_winsize(fd: int, rows: int, cols: int) -> None:
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))


class Agent:
    def __init__(self, machine_id: str, relay: str, token: str, command: list[str]) -> None:
        self.machine_id = machine_id
        self.url = f"{relay}/agent?machine={machine_id}&token={token}"
        self.command = command
        self.sessions: dict[str, Session] = {}
        self.ws = None

    async def run(self) -> None:
        # Reconnect forever: a flaky mobile-era network is the normal case, and
        # sessions must outlive the tunnel, not the other way round.
        backoff = 0.5
        while True:
            try:
                async with connect(self.url, max_size=None) as ws:
                    self.ws = ws
                    print(f"[agent] tunnel up: {self.url}", flush=True)
                    backoff = 0.5
                    await self._serve(ws)
            except (OSError, ConnectionClosed) as exc:
                print(f"[agent] tunnel down ({exc.__class__.__name__}), retrying in {backoff}s", flush=True)
            self.ws = None
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 10)

    async def _serve(self, ws) -> None:
        async for frame in ws:
            if isinstance(frame, bytes):
                kind, session_id, _, payload = wire.decode_data(frame)
                if kind == wire.INPUT:
                    session = self.sessions.get(session_id)
                    if session:
                        os.write(session.master, payload)
                continue
            msg = wire.decode_ctrl(frame)
            if msg.get("t") == "attach":
                await self._attach(ws, str(msg.get("session", "default")), int(msg.get("from", 0)))
            elif msg.get("t") == "resize":
                session = self.sessions.get(str(msg.get("session", "")))
                if session:
                    _set_winsize(session.master, int(msg["rows"]), int(msg["cols"]))

    async def _attach(self, ws, session_id: str, resume_from: int) -> None:
        session = self.sessions.get(session_id)
        if session is None:
            session = Session(session_id, self.command, rows=24, cols=80)
            self.sessions[session_id] = session
            asyncio.get_running_loop().add_reader(session.master, self._on_readable, session)
            print(f"[agent] session started: {session_id} pid={session.proc.pid}", flush=True)

        data, start, truncated = session.slice_from(resume_from)
        if truncated:
            await ws.send(wire.encode_ctrl(t="gap", session=session_id, **{"from": resume_from, "resumed_at": start}))
        await ws.send(wire.encode_ctrl(t="attached", session=session_id, offset=session.total))
        if data:
            await ws.send(wire.encode_data(wire.OUTPUT, session_id, start, data))

    def _on_readable(self, session: Session) -> None:
        try:
            data = os.read(session.master, READ_CHUNK)
        except (BlockingIOError, InterruptedError):
            return
        except OSError:  # EIO — the child hung up
            data = b""
        if not data:
            self._end(session)
            return
        offset = session.append(data)
        if self.ws is not None:
            # Fire-and-forget: if the tunnel is down the bytes are already in the
            # ring buffer, and the next attach will replay them.
            asyncio.ensure_future(self._send(wire.encode_data(wire.OUTPUT, session.id, offset, data)))

    async def _send(self, frame: bytes | str) -> None:
        ws = self.ws
        if ws is None:
            return
        with contextlib.suppress(ConnectionClosed):
            await ws.send(frame)

    def _end(self, session: Session) -> None:
        with contextlib.suppress(ValueError, OSError):
            asyncio.get_running_loop().remove_reader(session.master)
        session.close()
        self.sessions.pop(session.id, None)
        print(f"[agent] session ended: {session.id}", flush=True)
        asyncio.ensure_future(self._send(wire.encode_ctrl(t="exit", session=session.id)))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--machine", default="mac-01")
    ap.add_argument("--relay", default="ws://127.0.0.1:8787")
    ap.add_argument("--token", default=os.environ.get("DVR_TOKEN", "dev-token"))
    ap.add_argument("--command", default=os.environ.get("SHELL", "/bin/sh"))
    args = ap.parse_args()
    agent = Agent(args.machine, args.relay, args.token, [args.command])
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(agent.run())


if __name__ == "__main__":
    main()
