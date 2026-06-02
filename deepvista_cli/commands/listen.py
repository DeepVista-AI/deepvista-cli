"""deepvista listen — workflow execution daemon (DV-921).

Holds an SSE control channel open to the DeepVista backend and dispatches
workflow runs to a local ``claude`` subprocess. The web UI's "Run on my
connected machine" entry hits this daemon: each ``dispatch`` frame arriving
on ``GET /listener/stream`` is materialised on disk, executed by Claude
Code, and streamed back to the server as ``POST /workflow-runs/{id}/events``
frames (ack → running → progress/phase/output → result).

Transport: SSE control channel down, HTTP event POSTs up. The CLI is sync
everywhere else; the async pieces live ONLY in this module so the rest of
the codebase keeps its simple ``DeepVistaClient`` story. See DV-921 for the
full design (Redis pub/sub → SSE bridge re-used; daemon advertises
capabilities through the existing ``managed_agents`` plumbing).

Subcommands:
  start   — register as a daemon, open the control channel, run dispatch loop
  status  — report online + active runs, last heartbeat
  stop    — graceful SIGTERM of a running daemon

WIP scaffolding. The control-channel and subprocess pieces are gated by
``--stub`` flags / TODOs where the live backend route is not yet wired up
(server-side work tracked in DV-921 PR A).
"""

from __future__ import annotations

import asyncio
import json as _json
import os
import signal
import time
from pathlib import Path
from typing import Any

import click

from deepvista_cli.client.http import DeepVistaClient
from deepvista_cli.commands.agents import (
    DEFAULT_AGENT_ROLE,
    _build_config_snapshot,
    _ensure_agent_registered,
)
from deepvista_cli.config import CONFIG_DIR
from deepvista_cli.output.formatter import format_output, output_error

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Daemons register under the existing managed-agent tooling. The role is
# distinct from the user's regular ``deepvista-cli`` agent so a single
# machine can host both an interactive CLI and a background listener.
LISTEN_AGENT_TYPE = "deepvista-cli"
LISTEN_AGENT_ROLE = "daemon"

LISTEN_STATE_DIR = CONFIG_DIR / "listen"
DAEMON_STATE_PATH = LISTEN_STATE_DIR / "daemon.json"
RUNS_DIR = LISTEN_STATE_DIR / "runs"

# SSE control channel path (server-side route lands in DV-921 PR A).
CONTROL_CHANNEL_PATH = "/listener/stream"
EVENTS_PATH_TEMPLATE = "/workflow-runs/{run_id}/events"

# How often the daemon POSTs a heartbeat sync to keep last_heartbeat_at fresh.
HEARTBEAT_INTERVAL_SECONDS = 30


# ---------------------------------------------------------------------------
# Daemon state file (pidfile + agent_id + start time)
# ---------------------------------------------------------------------------


def _write_daemon_state(state: dict[str, Any]) -> None:
    LISTEN_STATE_DIR.mkdir(parents=True, exist_ok=True)
    DAEMON_STATE_PATH.write_text(_json.dumps(state, indent=2))
    os.chmod(DAEMON_STATE_PATH, 0o600)


def _read_daemon_state() -> dict[str, Any]:
    if not DAEMON_STATE_PATH.exists():
        return {}
    try:
        return _json.loads(DAEMON_STATE_PATH.read_text())
    except (_json.JSONDecodeError, OSError):
        return {}


def _clear_daemon_state() -> None:
    DAEMON_STATE_PATH.unlink(missing_ok=True)


def _pid_alive(pid: int) -> bool:
    """``kill -0`` style liveness check — no signal actually sent."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Process exists but is owned by someone else — treat as alive.
        return True
    return True


# ---------------------------------------------------------------------------
# Client helper (mirrors commands/agents.py shape)
# ---------------------------------------------------------------------------


def _client(ctx: click.Context) -> DeepVistaClient:
    return ctx.obj._client


# ---------------------------------------------------------------------------
# Async control-channel client — ISOLATED to this module
# ---------------------------------------------------------------------------
#
# The rest of the CLI is sync; daemon mode needs to multiplex an inbound
# SSE stream with many in-flight subprocesses, so we drop into asyncio
# locally. ``httpx.AsyncClient`` is the only async dep — keeps the wheel
# small and avoids pulling in ``websockets`` for a transport we don't use.


async def _stream_control_channel(
    api_url: str,
    auth_headers: dict[str, str],
    agent_id: str,
):
    """Yield decoded control frames from ``GET /listener/stream``.

    The server publishes Redis events keyed on this daemon's ``agent_id``
    (see DV-921 architecture diagram); we forward the agent id so the
    backend can scope the subscription. Each SSE ``data: <json>`` line
    becomes one frame.

    TODO(DV-921): wire to the real route once PR A lands. For now this
    will 404 on staging — handled by the caller, which falls back to
    idle-heartbeat mode and logs the missing endpoint.
    """
    import httpx  # local import — keeps top-level import time unchanged

    params = {"agent_id": agent_id}
    headers = {**auth_headers, "Accept": "text/event-stream"}

    # SSE is long-lived: ``read=None`` is required so the stream can idle
    # between dispatch frames. Every other phase keeps an explicit cap so
    # a stuck connect / write doesn't wedge the daemon (bandit B113).
    timeout = httpx.Timeout(connect=10.0, read=None, write=10.0, pool=10.0)
    async with httpx.AsyncClient(base_url=api_url, timeout=timeout) as client:
        async with client.stream("GET", CONTROL_CHANNEL_PATH, params=params, headers=headers) as resp:
            if resp.status_code >= 400:
                body = await resp.aread()
                raise RuntimeError(
                    f"control channel rejected ({resp.status_code}): {body.decode(errors='replace')[:200]}"
                )

            buffer = ""
            async for chunk in resp.aiter_text():
                buffer += chunk
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    line = line.strip()
                    if not line.startswith("data: "):
                        continue
                    data_str = line[6:]
                    if data_str == "[DONE]":
                        return
                    try:
                        yield _json.loads(data_str)
                    except _json.JSONDecodeError:
                        # Server-side bug or partial frame — skip rather
                        # than tear down the channel.
                        continue


async def _post_event(
    api_url: str,
    auth_headers: dict[str, str],
    run_id: str,
    frame: dict[str, Any],
) -> None:
    """POST one event frame back to the server's audit + relay endpoint."""
    import httpx

    path = EVENTS_PATH_TEMPLATE.format(run_id=run_id)
    async with httpx.AsyncClient(base_url=api_url, timeout=30.0) as client:
        # Best-effort: a transient failure here must not kill the dispatch
        # loop. The server's audit table is the source of truth, but a
        # dropped progress frame is recoverable on reconnect.
        try:
            await client.post(path, json=frame, headers=auth_headers)
        except httpx.HTTPError:
            return


# ---------------------------------------------------------------------------
# Run workspace + subprocess launch
# ---------------------------------------------------------------------------


def _run_workspace(run_id: str) -> Path:
    """Per-run scratch dir holding skill markdown, inputs, transcript."""
    path = RUNS_DIR / run_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def _materialise_dispatch(frame: dict[str, Any]) -> tuple[Path, Path, Path]:
    """Write the skill + inputs to disk so ``claude`` can pick them up.

    Returns ``(workspace, skill_path, inputs_path)``.
    """
    run_id = frame["run_id"]
    workspace = _run_workspace(run_id)
    skill_md = frame.get("skill_markdown") or ""
    inputs = frame.get("inputs") or {}

    skill_path = workspace / "SKILL.md"
    skill_path.write_text(skill_md, encoding="utf-8")

    inputs_path = workspace / "inputs.json"
    inputs_path.write_text(_json.dumps(inputs, indent=2), encoding="utf-8")
    return workspace, skill_path, inputs_path


async def _launch_claude(workspace: Path, skill_path: Path, inputs_path: Path) -> asyncio.subprocess.Process:
    """Spawn ``claude`` as a subprocess to execute the dispatched skill.

    TODO(DV-921): pin down the exact ``claude`` invocation — likely
    ``claude --print --output-format stream-json --append-system-prompt …``
    once the skill-runner contract in DV-919 settles. The transcript path
    is forwarded so the daemon can tail it for ``output`` frames.
    """
    transcript = workspace / "transcript.jsonl"
    transcript.touch()
    args = [
        "claude",
        "--print",
        "--output-format",
        "stream-json",
        "--input",
        str(inputs_path),
        str(skill_path),
    ]
    return await asyncio.create_subprocess_exec(
        *args,
        cwd=str(workspace),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={**os.environ, "DEEPVISTA_RUN_TRANSCRIPT": str(transcript)},
    )


async def _tail_and_relay(
    proc: asyncio.subprocess.Process,
    api_url: str,
    auth_headers: dict[str, str],
    run_id: str,
) -> dict[str, Any]:
    """Read JSONL transcript lines off the subprocess and POST event frames.

    Each Claude Code stream-json line is wrapped in an ``output`` frame and
    relayed to the server. The terminal ``result`` frame is constructed
    from the subprocess exit code so the UI can flip status to
    ``succeeded`` / ``failed``.
    """
    assert proc.stdout is not None  # for type-checkers; PIPE was requested

    seq = 0
    async for raw in proc.stdout:
        seq += 1
        line = raw.decode(errors="replace").rstrip("\n")
        if not line:
            continue
        try:
            payload = _json.loads(line)
        except _json.JSONDecodeError:
            payload = {"raw": line}
        await _post_event(
            api_url,
            auth_headers,
            run_id,
            {"type": "output", "seq": seq, "payload": payload},
        )

    rc = await proc.wait()
    return {
        "type": "result",
        "seq": seq + 1,
        "payload": {
            "exit_code": rc,
            "status": "succeeded" if rc == 0 else "failed",
        },
    }


# ---------------------------------------------------------------------------
# Per-run dispatch handler (one task per dispatched run)
# ---------------------------------------------------------------------------


async def _handle_dispatch(
    frame: dict[str, Any],
    api_url: str,
    auth_headers: dict[str, str],
    active_runs: dict[str, dict[str, Any]],
) -> None:
    run_id = frame.get("run_id")
    if not run_id:
        return

    active_runs[run_id] = {"started_at": time.time(), "status": "dispatched"}

    # 1. ack — server flips status to ``dispatched``.
    await _post_event(api_url, auth_headers, run_id, {"type": "ack"})

    # 2. Materialise the workflow on disk + launch claude.
    try:
        workspace, skill_path, inputs_path = _materialise_dispatch(frame)
        proc = await _launch_claude(workspace, skill_path, inputs_path)
    except FileNotFoundError as exc:
        # ``claude`` binary missing on this machine — surface to the UI
        # rather than dying silently.
        await _post_event(
            api_url,
            auth_headers,
            run_id,
            {"type": "error", "payload": {"message": "claude binary not found", "detail": str(exc)}},
        )
        active_runs.pop(run_id, None)
        return

    active_runs[run_id]["status"] = "running"
    active_runs[run_id]["pid"] = proc.pid
    await _post_event(api_url, auth_headers, run_id, {"type": "running", "payload": {"pid": proc.pid}})

    # 3. Tail transcript → output/result frames.
    terminal = await _tail_and_relay(proc, api_url, auth_headers, run_id)
    await _post_event(api_url, auth_headers, run_id, terminal)
    active_runs.pop(run_id, None)

    # 4. TODO(DV-921): wire ``deepvista session init/tick/finalize`` here
    # so the run transcript is persisted as a session card alongside the
    # workflow_run audit log. The session_id can be derived from ``run_id``
    # so resume after disconnect lands on the same card.


# ---------------------------------------------------------------------------
# Dispatch loop
# ---------------------------------------------------------------------------


async def _dispatch_loop(
    api_url: str,
    auth_headers: dict[str, str],
    agent_id: str,
) -> None:
    """Hold the SSE control channel open and fan-out runs as they arrive.

    Reconnect with exponential backoff if the channel drops. Cancel
    propagates from the SIGTERM handler installed by ``start``.
    """
    active_runs: dict[str, dict[str, Any]] = {}
    backoff = 1.0

    while True:
        try:
            async for frame in _stream_control_channel(api_url, auth_headers, agent_id):
                backoff = 1.0  # reset on a successful frame
                ftype = frame.get("type")
                if ftype == "dispatch":
                    asyncio.create_task(_handle_dispatch(frame, api_url, auth_headers, active_runs))
                elif ftype == "control":
                    run_id = frame.get("run_id")
                    if frame.get("action") == "cancel" and run_id in active_runs:
                        pid = active_runs[run_id].get("pid")
                        if pid:
                            try:
                                os.kill(pid, signal.SIGTERM)
                            except ProcessLookupError:
                                pass
                elif ftype == "ping":
                    # Server liveness probe — no-op; httpx already kept
                    # the connection warm for us.
                    continue
        except asyncio.CancelledError:
            # SIGTERM — drain in-flight runs and bail. The runs themselves
            # are responsible for posting their own terminal frames.
            raise
        except Exception as exc:  # noqa: BLE001 — keep daemon alive on any error
            click.echo(
                _json.dumps({"warning": "control channel error", "detail": str(exc)}),
                err=True,
            )
            await asyncio.sleep(min(backoff, 30.0))
            backoff = min(backoff * 2, 30.0)


async def _heartbeat_loop(
    api_url: str,
    auth_headers: dict[str, str],
    agent_id: str,
) -> None:
    """POST a periodic sync to keep ``last_heartbeat_at`` fresh on the server.

    Also writes ``last_heartbeat_at`` to the local daemon state file so
    ``listen status`` can report it without a network round-trip.
    """
    import httpx

    while True:
        await asyncio.sleep(HEARTBEAT_INTERVAL_SECONDS)
        now = time.time()
        try:
            async with httpx.AsyncClient(base_url=api_url, timeout=10.0) as client:
                await client.post(
                    f"/agents/{agent_id}/sync",
                    json={"status": "online", "sync_type": "heartbeat"},
                    headers=auth_headers,
                )
        except httpx.HTTPError:
            pass  # best-effort — a dropped heartbeat is not fatal
        # Update the local state file so `listen status` can report freshness.
        state = _read_daemon_state()
        if state:
            state["last_heartbeat_at"] = now
            _write_daemon_state(state)


# ---------------------------------------------------------------------------
# Click group
# ---------------------------------------------------------------------------


@click.group("listen")
def listen_group() -> None:
    """Run the workflow execution daemon (DV-921).

    The daemon holds an SSE control channel open to DeepVista and executes
    workflow runs dispatched from the web UI's "Run on my connected
    machine" entry. See DV-921 for the full design.
    """


# ---------------------------------------------------------------------------
# start
# ---------------------------------------------------------------------------


@listen_group.command("start")
@click.option(
    "--role",
    "agent_role",
    default=LISTEN_AGENT_ROLE,
    show_default=True,
    help="Functional role this daemon owns (free-text, e.g. engineering).",
)
@click.option(
    "--tools",
    default=None,
    help="Comma-separated list of extra tool names to advertise (e.g. gws,psql,fs). "
    "Merged into the capability snapshot so the UI knows which tools are available.",
)
@click.option(
    "--name",
    default=None,
    help="Display name for this daemon (defaults to hostname-derived label).",
)
@click.option(
    "--cwd",
    default=None,
    type=click.Path(exists=True, file_okay=False, resolve_path=True),
    help="Working directory dispatched runs execute in. Defaults to cwd.",
)
@click.option(
    "--stub",
    is_flag=True,
    default=False,
    help="Register + advertise capabilities, then exit (skip the dispatch loop). "
    "Use until the backend control-channel route is live.",
)
@click.pass_context
def listen_start(
    ctx: click.Context,
    agent_role: str,
    tools: str | None,
    name: str | None,
    cwd: str | None,
    stub: bool,
) -> None:
    """Register as a daemon, advertise capabilities, hold the control channel.

    Mirrors ``agents register`` for the identity/capability snapshot half
    so the UI's online + capable machine picker just works. The dispatch
    loop is async-isolated to this module.

    > [!CAUTION] This is a long-running, write command.
    """
    # 1. Ensure registered as a managed agent. Re-uses the existing
    # _ensure_agent_registered + _build_config_snapshot plumbing so the
    # daemon shows up under the same online/capable lookup the rest of
    # the agents picker uses.
    agent_id = _ensure_agent_registered(ctx, LISTEN_AGENT_TYPE)

    # 2. Push a fresh capability snapshot so the UI sees the right
    # tools/skills before the first dispatch arrives. The advertised role
    # disambiguates this daemon from the user's interactive CLI.
    config_patch = _build_config_snapshot(LISTEN_AGENT_TYPE)
    config_patch["agent_role"] = agent_role
    if cwd:
        config_patch["working_directory"] = cwd
    # Parse the comma-separated --tools list and include in the listener block
    # so the UI's capability picker can show which tools this machine can run.
    extra_tools = [t.strip() for t in tools.split(",") if t.strip()] if tools else []
    config_patch["listener"] = {"version": 1, "transport": "sse", "tools": extra_tools}

    _client(ctx).post(
        f"/agents/{agent_id}/sync",
        {"status": "online", "sync_type": "manual", "config_patch": config_patch},
    )

    # 3. Persist daemon state so `status` / `stop` can find us.
    now = time.time()
    state: dict[str, Any] = {
        "agent_id": agent_id,
        "agent_role": agent_role,
        "pid": os.getpid(),
        "started_at": now,
        "last_heartbeat_at": now,
        "api_url": ctx.obj.api_url,
    }
    if name:
        state["name"] = name
    if cwd:
        state["cwd"] = cwd
    if extra_tools:
        state["tools"] = extra_tools
    _write_daemon_state(state)

    if stub:
        out: dict[str, Any] = {
            "daemon": "registered",
            "agent_id": agent_id,
            "agent_role": agent_role,
            "stub": True,
            "note": "TODO(DV-921): dispatch loop disabled by --stub.",
        }
        if extra_tools:
            out["tools"] = extra_tools
        format_output(
            out,
            ctx.obj.output_format,
            title="Listen (stub mode)",
            entity_type="agent",
            base_url=ctx.obj.auth_url,
        )
        return

    # 4. Drop into the async dispatch loop. SIGTERM / SIGINT cancel the
    # top-level task; ``finally`` clears the daemon state file.
    auth_headers = _client(ctx)._auth_headers()
    try:
        asyncio.run(_run_until_signaled(ctx.obj.api_url, auth_headers, agent_id))
    finally:
        _clear_daemon_state()


async def _run_until_signaled(api_url: str, auth_headers: dict[str, str], agent_id: str) -> None:
    """Run the dispatch + heartbeat loops until SIGTERM / SIGINT cancels them."""
    loop = asyncio.get_running_loop()
    tasks = [
        asyncio.create_task(_dispatch_loop(api_url, auth_headers, agent_id)),
        asyncio.create_task(_heartbeat_loop(api_url, auth_headers, agent_id)),
    ]

    def _cancel(*_: Any) -> None:
        for t in tasks:
            t.cancel()

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _cancel)
        except NotImplementedError:
            # Windows — fall back to default behaviour (KeyboardInterrupt).
            signal.signal(sig, _cancel)

    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        return


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


@listen_group.command("status")
@click.pass_context
def listen_status(ctx: click.Context) -> None:
    """Report daemon liveness, registered agent_id, and active run count.

    Read-only. Returns ``offline`` (with exit 0) when no daemon is
    recorded locally — the absence of state is itself the answer.
    """
    state = _read_daemon_state()
    if not state:
        format_output(
            {"online": False, "reason": "no daemon state file"},
            ctx.obj.output_format,
            title="Listen status",
            entity_type="agent",
            base_url=ctx.obj.auth_url,
        )
        return

    pid = int(state.get("pid", 0))
    alive = _pid_alive(pid)
    # Count run workspaces that look in-flight (no terminal marker on disk
    # yet). The dispatch loop owns the authoritative active_runs dict in
    # memory; on the wire we approximate via the workspace dir so a
    # restarted CLI can still answer the question.
    active = []
    if RUNS_DIR.exists():
        for child in RUNS_DIR.iterdir():
            if child.is_dir() and not (child / ".finalized").exists():
                active.append(child.name)

    status_data: dict[str, Any] = {
        "online": alive,
        "pid": pid,
        "agent_id": state.get("agent_id"),
        "agent_role": state.get("agent_role"),
        "started_at": state.get("started_at"),
        "last_heartbeat_at": state.get("last_heartbeat_at"),
        "active_runs": active,
        "active_count": len(active),
    }
    if state.get("tools"):
        status_data["tools"] = state["tools"]
    format_output(
        status_data,
        ctx.obj.output_format,
        title="Listen status",
        entity_type="agent",
        base_url=ctx.obj.auth_url,
    )


# ---------------------------------------------------------------------------
# stop
# ---------------------------------------------------------------------------


@listen_group.command("stop")
@click.option(
    "--timeout",
    type=click.FloatRange(0.1, 60.0),
    default=10.0,
    show_default=True,
    help="Seconds to wait for graceful shutdown before giving up.",
)
@click.pass_context
def listen_stop(ctx: click.Context, timeout: float) -> None:
    """Send SIGTERM to a running daemon and wait for it to exit.

    > [!CAUTION] Terminates the daemon process.
    """
    state = _read_daemon_state()
    if not state:
        output_error(3, "No daemon running", "Nothing recorded in the local state file.")
        return

    pid = int(state.get("pid", 0))
    if not _pid_alive(pid):
        _clear_daemon_state()
        format_output(
            {"stopped": True, "pid": pid, "note": "process was already gone — cleared state file"},
            ctx.obj.output_format,
            title="Listen stop",
            entity_type="agent",
            base_url=ctx.obj.auth_url,
        )
        return

    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        _clear_daemon_state()
        format_output(
            {"stopped": True, "pid": pid},
            ctx.obj.output_format,
            title="Listen stop",
            entity_type="agent",
            base_url=ctx.obj.auth_url,
        )
        return

    deadline = time.time() + timeout
    while time.time() < deadline:
        if not _pid_alive(pid):
            _clear_daemon_state()
            format_output(
                {"stopped": True, "pid": pid},
                ctx.obj.output_format,
                title="Listen stop",
                entity_type="agent",
                base_url=ctx.obj.auth_url,
            )
            return
        time.sleep(0.2)

    output_error(
        1,
        "Daemon did not exit in time",
        f"pid={pid} still alive after {timeout}s; left state file in place.",
    )


# ---------------------------------------------------------------------------
# Public surface for ``main.py`` registration
# ---------------------------------------------------------------------------

__all__ = [
    "DEFAULT_AGENT_ROLE",  # re-export for tests
    "LISTEN_AGENT_ROLE",
    "LISTEN_AGENT_TYPE",
    "listen_group",
]
