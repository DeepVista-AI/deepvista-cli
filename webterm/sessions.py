"""Persistent terminal sessions living in the server process.

A session is a PTY plus enough buffered output to redraw a browser that has been
away. Sessions are owned by this process, not by any client, so closing every
tab — or the whole browser — does not end them. What kills a session is the
child exiting, an explicit kill, or the server stopping.

The buffer is addressed by *absolute byte offset*, which is what makes the two
different reconnect cases both cheap:

* **warm reconnect** (network blip, tab hidden): the client says "I had up to
  N", and gets exactly the bytes after N;
* **cold attach** (new browser, restored tab): the client asks for a tail, and
  gets the last ~N KB of the raw stream — escape codes and all, so xterm.js
  repaints colours and cursor position correctly without a separate screen
  serialiser.
"""

from __future__ import annotations

import asyncio
import contextlib
import fcntl
import os
import pty
import signal
import struct
import subprocess
import termios
import time
import uuid
from collections.abc import Callable

RING_BYTES = 1024 * 1024  # scrollback held per session for resume
COLD_TAIL_BYTES = 128 * 1024  # what a brand-new client gets painted on attach
READ_CHUNK = 65536

Listener = Callable[[str, int, bytes], None]  # (session_id, offset, data)


def _set_winsize(fd: int, rows: int, cols: int) -> None:
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))


def _claim_controlling_tty() -> None:
    """Runs in the forked child: adopt the PTY slave as its controlling terminal.

    Without this the shell reports "can't access tty; job control turned off"
    and ^C / ^Z / fg never work.
    """
    with contextlib.suppress(OSError, AttributeError):
        fcntl.ioctl(0, termios.TIOCSCTTY, 0)


class Session:
    def __init__(self, name: str, command: list[str], cwd: str, rows: int, cols: int) -> None:
        self.id = uuid.uuid4().hex[:12]
        self.name = name
        self.command = command
        self.cwd = cwd
        self.rows = rows
        self.cols = cols
        self.created_at = time.time()
        self.exit_code: int | None = None
        self.ring = bytearray()
        self.total = 0
        self.listeners: set[Listener] = set()

        master, slave = pty.openpty()
        self.master = master
        _set_winsize(master, rows, cols)
        self.proc = subprocess.Popen(
            command,
            stdin=slave,
            stdout=slave,
            stderr=slave,
            cwd=cwd,
            start_new_session=True,
            preexec_fn=_claim_controlling_tty,  # noqa: PLW1509 - single-threaded child setup
            env={
                **os.environ,
                "TERM": "xterm-256color",
                "COLORTERM": "truecolor",
                "LINES": str(rows),
                "COLUMNS": str(cols),
            },
        )
        os.close(slave)
        os.set_blocking(master, False)
        asyncio.get_running_loop().add_reader(master, self._drain)

    # ---- output buffer -------------------------------------------------

    @property
    def base_offset(self) -> int:
        return self.total - len(self.ring)

    @property
    def alive(self) -> bool:
        return self.exit_code is None

    def _drain(self) -> None:
        try:
            data = os.read(self.master, READ_CHUNK)
        except (BlockingIOError, InterruptedError):
            return
        except OSError:  # EIO: the child hung up
            data = b""
        if not data:
            self._reap()
            return
        offset = self.total
        self.ring += data
        self.total += len(data)
        if len(self.ring) > RING_BYTES:
            del self.ring[: len(self.ring) - RING_BYTES]
        for listener in list(self.listeners):
            listener(self.id, offset, data)

    def slice_from(self, offset: int) -> tuple[int, bytes, bool]:
        """Return (start_offset, bytes, truncated) for everything after `offset`."""
        if offset >= self.total:
            return self.total, b"", False
        if offset < self.base_offset:
            return self.base_offset, bytes(self.ring), True
        return offset, bytes(self.ring[offset - self.base_offset :]), False

    def cold_tail(self) -> tuple[int, bytes]:
        """The last COLD_TAIL_BYTES of raw stream, for painting a fresh client."""
        tail = self.ring[-COLD_TAIL_BYTES:]
        return self.total - len(tail), bytes(tail)

    # ---- input / control -----------------------------------------------

    def write(self, data: bytes) -> None:
        if self.alive:
            with contextlib.suppress(OSError):
                os.write(self.master, data)

    def resize(self, rows: int, cols: int) -> None:
        if rows <= 0 or cols <= 0 or (rows, cols) == (self.rows, self.cols):
            return
        self.rows, self.cols = rows, cols
        if self.alive:
            with contextlib.suppress(OSError):
                _set_winsize(self.master, rows, cols)

    def _reap(self) -> None:
        with contextlib.suppress(ValueError, OSError):
            asyncio.get_running_loop().remove_reader(self.master)
        with contextlib.suppress(Exception):
            self.exit_code = self.proc.wait(timeout=1)
        if self.exit_code is None:
            self.exit_code = -1
        with contextlib.suppress(OSError):
            os.close(self.master)

    def kill(self) -> None:
        with contextlib.suppress(ProcessLookupError, PermissionError, OSError):
            os.killpg(os.getpgid(self.proc.pid), signal.SIGHUP)
        if self.alive:
            self._reap()

    def meta(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "command": " ".join(self.command),
            "cwd": self.cwd,
            "rows": self.rows,
            "cols": self.cols,
            "created_at": self.created_at,
            "offset": self.total,
            "alive": self.alive,
            "exit_code": self.exit_code,
            "viewers": len(self.listeners),
        }


class SessionStore:
    def __init__(self, default_command: list[str], default_cwd: str) -> None:
        self.default_command = default_command
        self.default_cwd = default_cwd
        self.sessions: dict[str, Session] = {}

    def create(
        self,
        name: str | None = None,
        command: list[str] | None = None,
        cwd: str | None = None,
        rows: int = 24,
        cols: int = 80,
    ) -> Session:
        session = Session(
            name=name or f"session {len(self.sessions) + 1}",
            command=command or self.default_command,
            cwd=cwd or self.default_cwd,
            rows=rows,
            cols=cols,
        )
        self.sessions[session.id] = session
        return session

    def get(self, session_id: str) -> Session | None:
        return self.sessions.get(session_id)

    def list(self) -> list[dict]:
        return [s.meta() for s in sorted(self.sessions.values(), key=lambda s: s.created_at)]

    def close(self, session_id: str) -> bool:
        session = self.sessions.pop(session_id, None)
        if session is None:
            return False
        session.kill()
        return True

    def shutdown(self) -> None:
        for session in list(self.sessions.values()):
            session.kill()
        self.sessions.clear()
