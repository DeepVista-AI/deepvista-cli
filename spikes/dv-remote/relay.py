"""Rendezvous relay: bridges viewer WebSockets to machine WebSockets.

Deliberately dumb. It knows which machines are online and which viewers are
attached to which session, and it copies frames between them. It holds no
scrollback, so it cannot replay a session and — in the encrypted variant — has
no way to read one. Everything expensive (PTY, buffer, replay) lives on the
machine.

Both sides dial *out* to this process, which is why no inbound port is ever
opened on the developer's laptop.

    uv run --with websockets python relay.py --port 8787
"""

import argparse
import asyncio
import contextlib
import os
from collections import defaultdict
from urllib.parse import parse_qs, urlparse

import wire
from websockets.asyncio.server import ServerConnection, serve
from websockets.exceptions import ConnectionClosed

TOKEN = os.environ.get("DVR_TOKEN", "dev-token")


class Machine:
    """One connected machine agent and the viewers currently watching it."""

    def __init__(self, machine_id: str, ws: ServerConnection) -> None:
        self.machine_id = machine_id
        self.ws = ws
        self.viewers: dict[str, set[ServerConnection]] = defaultdict(set)

    async def broadcast(self, session_id: str, frame: bytes | str) -> None:
        dead = []
        for viewer in self.viewers.get(session_id, set()):
            try:
                await viewer.send(frame)
            except ConnectionClosed:
                dead.append(viewer)
        for viewer in dead:
            self.viewers[session_id].discard(viewer)


MACHINES: dict[str, Machine] = {}


def _query(path: str) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(urlparse(path).query).items()}


async def handle_machine(ws: ServerConnection, params: dict[str, str]) -> None:
    machine_id = params.get("machine", "")
    if not machine_id:
        await ws.close(4400, "machine id required")
        return
    machine = Machine(machine_id, ws)
    MACHINES[machine_id] = machine
    print(f"[relay] machine online: {machine_id}", flush=True)
    try:
        async for frame in ws:
            # Machine -> viewers. Data frames are routed by their session id;
            # control frames carry it as a JSON field.
            if isinstance(frame, bytes):
                _, session_id, _, _ = wire.decode_data(frame)
            else:
                session_id = str(wire.decode_ctrl(frame).get("session", ""))
            await machine.broadcast(session_id, frame)
    except ConnectionClosed:
        pass
    finally:
        if MACHINES.get(machine_id) is machine:
            del MACHINES[machine_id]
        print(f"[relay] machine offline: {machine_id}", flush=True)


async def handle_viewer(ws: ServerConnection, params: dict[str, str]) -> None:
    machine = MACHINES.get(params.get("machine", ""))
    if machine is None:
        await ws.close(4404, "machine offline")
        return
    session_id = params.get("session", "default")
    resume_from = int(params.get("from", "0"))
    machine.viewers[session_id].add(ws)
    # Ask the machine to attach us. It creates the session on first attach and
    # replays whatever we missed starting at `from`.
    await machine.ws.send(wire.encode_ctrl(t="attach", session=session_id, **{"from": resume_from}))
    print(f"[relay] viewer attached: {machine.machine_id}/{session_id} from={resume_from}", flush=True)
    try:
        async for frame in ws:
            await machine.ws.send(frame)  # viewer input / resize, verbatim
    except ConnectionClosed:
        pass
    finally:
        machine.viewers[session_id].discard(ws)
        print(f"[relay] viewer detached: {machine.machine_id}/{session_id}", flush=True)


async def router(ws: ServerConnection) -> None:
    path = ws.request.path if ws.request else "/"
    params = _query(path)
    if params.get("token") != TOKEN:
        await ws.close(4401, "bad token")
        return
    route = urlparse(path).path
    if route == "/agent":
        await handle_machine(ws, params)
    elif route == "/view":
        await handle_viewer(ws, params)
    else:
        await ws.close(4404, "no such route")


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8787)
    args = ap.parse_args()
    async with serve(router, args.host, args.port):
        print(f"[relay] listening on ws://{args.host}:{args.port}", flush=True)
        await asyncio.Future()


if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(main())
