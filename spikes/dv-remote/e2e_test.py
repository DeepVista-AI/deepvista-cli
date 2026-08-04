"""End-to-end check of the relay + agent + viewer path.

Run it:

    cd spikes/dv-remote
    uv run --with websockets --with psutil python e2e_test.py

It boots a relay and an agent as real subprocesses and asserts the claims the
architecture rests on:

1. keystrokes reach the PTY and output comes back, on a real controlling tty;
2. the session survives every viewer disconnecting;
3. a reconnecting viewer resumes at its byte offset — it gets what it missed
   and *only* what it missed;
4. several viewers can watch one session at once;
5. resize reaches the real tty (``stty size`` proves it);
6. a viewer asking for bytes the ring buffer already dropped is told there is a
   gap, rather than handed a silently truncated stream;
7. the agent process never listens on an inbound port — one outbound socket;
8. killing the relay does not kill the session: the machine redials and the
   same shell process is still there, with its state intact.
"""

import asyncio
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import psutil
from viewer import Viewer

HERE = Path(__file__).parent
TOKEN = "test-token"
RELAY = "ws://127.0.0.1:{port}"

results: list[tuple[bool, str]] = []


def check(ok: bool, label: str) -> None:
    results.append((bool(ok), label))
    print(f"  {'PASS' if ok else 'FAIL'}  {label}", flush=True)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_for_port(port: int, timeout: float = 10.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.05)
    raise TimeoutError(f"nothing listening on {port}")


async def tunnel_drop(port: int, restart_relay) -> None:
    """The claim that makes this usable on mobile: losing the tunnel is not losing the session."""
    relay = RELAY.format(port=port)
    print("\n8) the session survives the tunnel dropping", flush=True)
    async with Viewer(relay, "mac-01", "s2", TOKEN) as v1:
        await v1.send("MARKER_VAR=survived_the_drop\n")
        await v1.send("echo before=$MARKER_VAR\n")
        check(await v1.wait_for("before=survived_the_drop"), "state set in the live shell")
        offset = v1.offset

    restart_relay()  # the relay dies and comes back; the machine had to redial
    await asyncio.sleep(6)  # agent reconnect backoff

    async with Viewer(relay, "mac-01", "s2", TOKEN, resume_from=offset) as v2:
        await v2.send("echo after=$MARKER_VAR\n")
        # Only the *same* shell process still knows MARKER_VAR — a respawned
        # session would print "after=".
        check(await v2.wait_for("after=survived_the_drop", timeout=8), "same shell process after the tunnel dropped")


async def scenarios(port: int, agent_pid: int) -> None:
    relay = RELAY.format(port=port)
    open_viewer = lambda **kw: Viewer(relay, "mac-01", "s1", TOKEN, **kw)  # noqa: E731

    print("\n1) input reaches the PTY, output comes back", flush=True)
    async with open_viewer() as v1:
        await v1.send("echo HELLO_FROM_PTY\n")
        check(await v1.wait_for("HELLO_FROM_PTY"), "command output relayed to viewer")
        check("job control turned off" not in v1.text(), "child got a controlling tty (job control on)")

        print("\n2) session outlives the viewer", flush=True)
        # Schedule output that lands ~1.5s from now, then detach immediately so
        # it is produced with nobody attached. printf splits the marker so the
        # echoed command line cannot be mistaken for the output itself.
        await v1.send("(sleep 1.5; printf 'AWAY%s\\n' _OK) &\n")
        offset = v1.offset  # captured now: everything after this we are meant to miss

    await asyncio.sleep(2.5)  # fully detached; the PTY keeps running

    print("\n3) reconnect resumes at the byte offset", flush=True)
    async with open_viewer(resume_from=offset) as v2:
        check(await v2.wait_for("AWAY_OK"), "output produced while detached is replayed")
        check("HELLO_FROM_PTY" not in v2.text(), "already-seen bytes are not resent")
        check(v2.offset > offset, f"offset advanced {offset} -> {v2.offset}")
        check(v2.gaps == [], "no gap reported (scrollback covered the range)")

        print("\n4) two viewers on one session", flush=True)
        async with open_viewer(resume_from=v2.offset) as v3:
            await v2.send("echo BOTH_SEE_THIS\n")
            check(await v2.wait_for("BOTH_SEE_THIS"), "first viewer sees it")
            check(await v3.wait_for("BOTH_SEE_THIS"), "second viewer sees it")

        print("\n5) resize reaches the tty", flush=True)
        await v2.resize(40, 100)
        await asyncio.sleep(0.2)
        await v2.send("stty size\n")
        check(await v2.wait_for("40 100"), "stty size reports the new window")

        print("\n6) scrollback overflow is reported, not hidden", flush=True)
        await v2.send("tr '\\0' 'x' < /dev/zero | head -c 400000; echo DONE_FLOOD\n")
        check(await v2.wait_for("DONE_FLOOD", timeout=20), "400 KB flood delivered")
        await asyncio.sleep(0.3)

    async with open_viewer(resume_from=1) as v4:
        await asyncio.sleep(0.5)
        check(bool(v4.gaps), f"gap signalled to the resuming viewer: {v4.gaps[:1]}")
        check(v4.offset > 100_000, f"resumed at the oldest byte still held ({v4.offset})")

    print("\n7) the agent opens no inbound port", flush=True)
    sockets = psutil.Process(agent_pid).net_connections(kind="inet")
    listening = [c for c in sockets if c.status == psutil.CONN_LISTEN]
    check(not listening, f"no listening sockets on the agent process (found {len(listening)})")
    outbound = [c for c in sockets if c.status == psutil.CONN_ESTABLISHED]
    check(len(outbound) == 1, f"exactly one outbound tunnel connection (found {len(outbound)})")


def main() -> int:
    port = free_port()
    env = {**os.environ, "DVR_TOKEN": TOKEN}
    relay_procs: list[subprocess.Popen] = []

    def start_relay() -> subprocess.Popen:
        proc = subprocess.Popen([sys.executable, "relay.py", "--port", str(port)], cwd=HERE, env=env)
        relay_procs.append(proc)
        wait_for_port(port)
        return proc

    def restart_relay() -> None:
        proc = relay_procs[-1]
        proc.terminate()
        proc.wait(timeout=5)
        time.sleep(0.3)
        start_relay()

    start_relay()
    try:
        agent_proc = subprocess.Popen(
            [
                sys.executable,
                "agent.py",
                "--machine",
                "mac-01",
                "--relay",
                RELAY.format(port=port),
                "--token",
                TOKEN,
                "--command",
                "/bin/sh",
            ],
            cwd=HERE,
            env=env,
        )
        try:
            time.sleep(1.0)  # let the tunnel come up
            asyncio.run(scenarios(port, agent_proc.pid))
            asyncio.run(tunnel_drop(port, restart_relay))
        finally:
            agent_proc.terminate()
            agent_proc.wait(timeout=5)
    finally:
        for proc in relay_procs:
            if proc.poll() is None:
                proc.terminate()
                proc.wait(timeout=5)

    failed = [label for ok, label in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed", flush=True)
    for label in failed:
        print(f"  FAILED: {label}", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
