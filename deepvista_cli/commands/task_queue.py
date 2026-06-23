"""deepvista task_queue — pull-based execution of queued CLI commands (DV-936).

The web app enqueues DeepVista CLI commands onto a managed agent's
`task_queue`; this command group lets the agent's machine poll and run them:

  deepvista task_queue run      — poll for pending tasks and execute them
  deepvista task_queue list     — show this machine's queue
  deepvista task_queue complete — report a workflow task's outcome (host agent)
  deepvista task_queue setup    — install a crontab entry that polls periodically

Polling (DV-1079): `run` polls in the foreground by default (--poll-interval,
bounded by --total-time when given); --run-once does a single claim/execute
pass, which is what the cron entry installed by `setup` uses. A PID lock file
allows only one `task_queue run` per machine at a time, so a foreground
poller and cron ticks never double-claim.

Workflow tasks (DV-955): webhook-queued `deepvista skill run` entries can't
be subprocess-executed — a workflow needs the surrounding host agent (Claude
Code etc.) to drive its phases. `task_queue run --host` claims them and
emits their run packets to stdout for the host agent; headless runs (cron)
claim command-only so workflow tasks stay pending until a host run. The
host agent reports the outcome via `task_queue complete` after
`skill complete`.

Safety: only commands whose first token is `deepvista` are executed
(shlex-parsed, shell=False). The backend enforces the same allowlist at
enqueue time; the check here guards against tampered queue rows.
"""

from __future__ import annotations

import json as _json
import os
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

import click

from deepvista_cli.auth.tokens import get_valid_token
from deepvista_cli.client.http import DeepVistaClient
from deepvista_cli.client.origin import detect_agent_tool
from deepvista_cli.commands.agents import (
    AGENTS_DIR,
    DEFAULT_AGENT_ROLE,
    _build_config_snapshot,
    _default_agent_name,
    _install_hooks,
    _load_agent_id,
    _save_agent_id,
)
from deepvista_cli.commands.skill import emit_host_run_packet
from deepvista_cli.config import CONFIG_DIR, credentials_path
from deepvista_cli.output.formatter import format_output, output_error

TASK_COLUMNS = ["id", "status", "command", "created_at", "finished_at", "exit_code"]

# Only the DeepVista CLI itself may be invoked from the queue.
ALLOWED_COMMAND_BINARY = "deepvista"

# Per-task execution budget; a hung task must not wedge the cron tick forever.
TASK_TIMEOUT_SECONDS = 600

# Reported output is truncated to a tail (mirrors the backend cap).
OUTPUT_TAIL_MAX_CHARS = 2000

# Marker comment identifying crontab entries owned by `task_queue setup`.
CRON_MARKER = "# deepvista-task-queue"

CRON_LOG_PATH = CONFIG_DIR / "task_queue.log"

# Seconds between polls when `run` is left in its default polling mode.
DEFAULT_POLL_INTERVAL_SECONDS = 10

# Single-instance lock for `task_queue run` (DV-1079) — holds the owner PID.
RUN_LOCK_PATH = CONFIG_DIR / "task_queue.run.lock"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _client(ctx: click.Context) -> DeepVistaClient:
    return ctx.obj._client


def _output(ctx: click.Context, data: object, **kwargs: object) -> None:
    format_output(data, ctx.obj.output_format, **kwargs)  # type: ignore[arg-type]


def _resolve_machine_agent_id(
    agent_type: str | None,
    agent_role: str | None,
    project_id: str | None = None,
) -> tuple[str, str | None] | None:
    """Find the registered agent this machine's queue belongs to.

    Resolution order: explicit --type/--role/--project, then the detected host
    tool, then the most recently registered agent of any type on this machine.

    Returns ``(agent_id, project_id)`` so callers can surface the project in
    banners without a second file read, or ``None`` when nothing is found.
    """

    def _read(path: Path) -> tuple[str, str | None] | None:
        try:
            data = _json.loads(path.read_text())
            aid = data.get("agent_id")
            return (aid, data.get("project_id")) if aid else None
        except (OSError, _json.JSONDecodeError):
            return None

    if agent_type:
        agent_id = _load_agent_id(agent_type, agent_role, project_id)
        if not agent_id:
            return None
        # Re-read the file to get project_id alongside the agent_id.
        for path in AGENTS_DIR.glob(f"{agent_type}__*.json"):
            result = _read(path)
            if result and result[0] == agent_id:
                return result
        return (agent_id, project_id)

    try:
        detected, _ = detect_agent_tool()
    except Exception:
        detected = None
    if detected:
        agent_id = _load_agent_id(detected, agent_role, project_id)
        if agent_id:
            for path in AGENTS_DIR.glob(f"{detected}__*.json"):
                result = _read(path)
                if result and result[0] == agent_id:
                    return result
            return (agent_id, project_id)

    # Cron runs outside any agent host — fall back to the newest registration.
    candidates: list[tuple[float, Path]] = []
    if AGENTS_DIR.exists():
        for path in AGENTS_DIR.glob("*.json"):
            try:
                candidates.append((path.stat().st_mtime, path))
            except OSError:
                continue
    candidates.sort(reverse=True)
    for _, path in candidates:
        try:
            data = _json.loads(path.read_text())
        except (OSError, _json.JSONDecodeError):
            continue
        if project_id and data.get("project_id") and data["project_id"] != project_id:
            continue
        aid = data.get("agent_id")
        if aid:
            return (aid, data.get("project_id"))
    return None


def _require_machine_agent_id(
    agent_type: str | None,
    agent_role: str | None,
    project_id: str | None = None,
) -> tuple[str, str | None]:
    result = _resolve_machine_agent_id(agent_type, agent_role, project_id)
    if not result:
        output_error(3, "No registered agent on this machine", "Run 'deepvista agents register' first.")
        raise SystemExit(3)
    return result


def _deepvista_binary() -> str:
    """Absolute path to the `deepvista` entry point (cron has a minimal PATH)."""
    binary = shutil.which(ALLOWED_COMMAND_BINARY)
    if binary:
        return binary
    if sys.argv and Path(sys.argv[0]).name == ALLOWED_COMMAND_BINARY:
        return str(Path(sys.argv[0]).resolve())
    return ALLOWED_COMMAND_BINARY


def _validate_command(command: str) -> str | None:
    """Return an error message when `command` is not an allowed CLI invocation."""
    try:
        tokens = shlex.split(command)
    except ValueError as exc:
        return f"Command is not shell-parseable: {exc}"
    if not tokens:
        return "Command is empty"
    if tokens[0] != ALLOWED_COMMAND_BINARY:
        return f"Only '{ALLOWED_COMMAND_BINARY}' commands can run from the task queue"
    return None


def _is_workflow_task(task: dict) -> bool:
    """True when the task is a webhook-queued workflow run (DV-955).

    Primary signal is the advisory ``source: "webhook"`` key the backend
    stamps at enqueue time; the command-shape fallback covers queues
    written before that key existed.
    """
    if task.get("source") == "webhook":
        return True
    try:
        tokens = shlex.split(str(task.get("command", "")))
    except ValueError:
        return False
    return tokens[:3] == [ALLOWED_COMMAND_BINARY, "skill", "run"] and "--webhook" in tokens


def _parse_workflow_command(command: str) -> dict | None:
    """Extract skill_id / --input / --best-effort from a queued skill-run command.

    The webhook composes these commands with a fixed shape
    (``deepvista skill run --mode host <id> --input <json> --webhook
    [--best-effort]``); parse defensively anyway since queue rows are data.
    Returns None when the command isn't a recognizable skill run.
    """
    try:
        tokens = shlex.split(command)
    except ValueError:
        return None
    if tokens[:3] != [ALLOWED_COMMAND_BINARY, "skill", "run"]:
        return None

    value_opts = {"--mode", "--input"}
    values: dict[str, str] = {}
    skill_id: str | None = None
    i = 3
    while i < len(tokens):
        token = tokens[i]
        if token in value_opts:
            if i + 1 < len(tokens):
                values[token] = tokens[i + 1]
            i += 2
        elif token.startswith("--"):
            i += 1
        elif skill_id is None:
            skill_id = token
            i += 1
        else:
            i += 1

    if not skill_id:
        return None
    return {
        "skill_id": skill_id,
        "user_input": values.get("--input"),
        "best_effort": "--best-effort" in tokens,
    }


def _emit_workflow_task(ctx: click.Context, agent_id: str, task: dict) -> dict:
    """Print a claimed workflow task's run packet for the host agent (DV-955).

    The task is left ``running`` on purpose — the host agent drives the
    workflow and reports the outcome via ``task_queue complete``. Only an
    unparseable/unloadable task is failed here, since no agent could ever
    pick it up.
    """
    task_id = str(task.get("id", ""))
    command = str(task.get("command", ""))

    parsed = _parse_workflow_command(command)
    if parsed is None:
        _client(ctx).post(
            f"/agents/{agent_id}/task-queue/{task_id}/result",
            {"status": "failed", "exit_code": None, "output_tail": "Unparseable workflow task command"},
        )
        return {"task_id": task_id, "command": command, "status": "failed", "exit_code": None}

    click.echo()
    click.echo(f"=== DEEPVISTA WORKFLOW TASK {task_id} (skill {parsed['skill_id']}) ===")
    click.echo()
    try:
        emit_host_run_packet(
            ctx,
            parsed["skill_id"],
            parsed["user_input"],
            "host",
            webhook=True,
            best_effort=parsed["best_effort"],
            task_id=task_id,
        )
    except SystemExit:
        # Skill gone / empty / phaseless — no host agent can ever run this
        # task, so fail it instead of leaving it stuck in `running`.
        _client(ctx).post(
            f"/agents/{agent_id}/task-queue/{task_id}/result",
            {"status": "failed", "exit_code": None, "output_tail": "Skill not found or not runnable"},
        )
        return {"task_id": task_id, "command": command, "status": "failed", "exit_code": None}
    return {"task_id": task_id, "command": command, "status": "running", "exit_code": None}


def _pid_alive(pid: int) -> bool:
    """Best-effort liveness probe for a PID (signal 0, no actual signal sent)."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Exists but owned by someone else — still alive.
        return True
    except OSError:
        return False
    return True


def _read_lock_pid() -> int | None:
    try:
        return int(RUN_LOCK_PATH.read_text().strip())
    except (OSError, ValueError):
        return None


def _acquire_run_lock() -> bool:
    """Take the machine-wide single-instance lock for `task_queue run` (DV-1079).

    Overlapping pollers would double-claim the queue, so only one `run` may
    be active at a time — a foreground poller and a cron tick included. A
    lock whose owner PID is dead (crash, reboot) is stale and reclaimed.
    """
    pid = _read_lock_pid()
    if pid is not None and pid != os.getpid() and _pid_alive(pid):
        return False
    RUN_LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    RUN_LOCK_PATH.write_text(str(os.getpid()))
    return True


def _release_run_lock() -> None:
    if _read_lock_pid() != os.getpid():
        return
    try:
        RUN_LOCK_PATH.unlink()
    except OSError:
        pass


def _execute_task(ctx: click.Context, agent_id: str, task: dict) -> dict:
    """Run one claimed task and report its terminal result to the backend."""
    task_id = str(task.get("id", ""))
    command = str(task.get("command", ""))

    validation_error = _validate_command(command)
    if validation_error:
        status, exit_code, output_tail = "failed", None, validation_error
    else:
        argv = shlex.split(command)
        argv[0] = _deepvista_binary()
        try:
            proc = subprocess.run(  # noqa: S603 — argv is allowlist-validated, shell=False
                argv,
                capture_output=True,
                text=True,
                timeout=TASK_TIMEOUT_SECONDS,
            )
            exit_code = proc.returncode
            status = "completed" if exit_code == 0 else "failed"
            output_tail = ((proc.stdout or "") + (proc.stderr or ""))[-OUTPUT_TAIL_MAX_CHARS:]
        except subprocess.TimeoutExpired:
            status, exit_code, output_tail = "failed", None, f"Timed out after {TASK_TIMEOUT_SECONDS}s"
        except OSError as exc:
            status, exit_code, output_tail = "failed", None, str(exc)

    _client(ctx).post(
        f"/agents/{agent_id}/task-queue/{task_id}/result",
        {"status": status, "exit_code": exit_code, "output_tail": output_tail},
    )
    return {"task_id": task_id, "command": command, "status": status, "exit_code": exit_code}


# ---------------------------------------------------------------------------
# Task cards (DV-1247) — plain prompts dispatched from the web chat, run
# headlessly via `claude -p "/deepvista <prompt>"`.
# ---------------------------------------------------------------------------

# A task prompt may legitimately drive a long Claude Code session (research,
# multi-tool work), so it gets a more generous budget than a queued CLI command.
TASK_RUN_TIMEOUT_SECONDS = 1800

# Headless permission posture for unattended task runs. ``bypassPermissions``
# skips every approval prompt — appropriate for a Machine the user has
# deliberately set polling. Override per-machine with the env var.
DEFAULT_TASK_PERMISSION_MODE = "bypassPermissions"


def _claude_binary() -> str:
    """Resolve the Claude Code binary (override with DEEPVISTA_CLAUDE_BIN).

    The override doubles as the test seam: point it at a stub script to drive
    the whole claim -> run -> report loop without a real Claude Code install.
    """
    override = os.environ.get("DEEPVISTA_CLAUDE_BIN", "").strip()
    if override:
        return override
    return shutil.which("claude") or "claude"


def _run_task_card(ctx: click.Context, agent_id: str, project_id: str | None, task: dict) -> dict:
    """Run one claimed task card via `claude -p` and report the result back.

    The prompt is handed to Claude Code as ``/deepvista <prompt>`` so the run
    boots with the DeepVista skill context (knowledge base, notes, the CLI).
    stdout becomes the run's output (a linked output card is created backend-side
    when non-empty); the exit code decides completed vs. failed.
    """
    task_id = str(task.get("id", ""))
    prompt = str(task.get("prompt", "")).strip()
    headers = {"X-Project-Id": project_id} if project_id else None

    if not prompt:
        _client(ctx).post(
            f"/agents/{agent_id}/tasks/{task_id}/result",
            {"status": "failed", "exit_code": None, "output": "Task has an empty prompt."},
            extra_headers=headers,
        )
        return {"task_id": task_id, "status": "failed", "title": task.get("title")}

    permission_mode = os.environ.get("DEEPVISTA_TASK_PERMISSION_MODE", DEFAULT_TASK_PERMISSION_MODE)
    cwd = os.environ.get("DEEPVISTA_TASK_CWD") or os.getcwd()
    argv = [_claude_binary(), "-p", f"/deepvista {prompt}", "--permission-mode", permission_mode]

    click.echo(f"  ▶ running task {task_id} via claude -p (project {project_id or '?'})", err=True)
    try:
        proc = subprocess.run(  # noqa: S603 — argv built from a fixed binary + literal flags
            argv,
            capture_output=True,
            text=True,
            timeout=TASK_RUN_TIMEOUT_SECONDS,
            cwd=cwd,
        )
        exit_code = proc.returncode
        status = "completed" if exit_code == 0 else "failed"
        output = (proc.stdout or "").strip()
        if not output and proc.stderr:
            output = proc.stderr.strip()
    except subprocess.TimeoutExpired:
        status, exit_code, output = "failed", None, f"claude run timed out after {TASK_RUN_TIMEOUT_SECONDS}s"
    except FileNotFoundError:
        status, exit_code, output = (
            "failed",
            None,
            "Claude Code binary not found. Install it or set DEEPVISTA_CLAUDE_BIN.",
        )
    except OSError as exc:
        status, exit_code, output = "failed", None, str(exc)

    _client(ctx).post(
        f"/agents/{agent_id}/tasks/{task_id}/result",
        {"status": status, "exit_code": exit_code, "output": output, "output_title": task.get("title")},
        extra_headers=headers,
    )
    return {"task_id": task_id, "title": task.get("title"), "status": status, "exit_code": exit_code}


def _claim_and_run_task_cards(ctx: click.Context, agent_id: str, project_id: str | None) -> list[dict]:
    """Claim this Machine's pending task cards in ``project_id`` and run each headless."""
    headers = {"X-Project-Id": project_id} if project_id else None
    data = _client(ctx).post(f"/agents/{agent_id}/tasks/claim", None, extra_headers=headers)
    if not data.get("success", True):
        click.echo(
            f"  [warn] could not claim task cards for agent {agent_id}: {data.get('error', 'unknown')}",
            err=True,
        )
        return []
    tasks = data.get("tasks") or []
    return [_run_task_card(ctx, agent_id, project_id, task) for task in tasks]


# ---------------------------------------------------------------------------
# Command group
# ---------------------------------------------------------------------------


@click.group("tasks")
def task_queue_group() -> None:
    """Run tasks dispatched to this Machine (DV-1247).

    `tasks run` polls for work and executes it: **task cards** (plain prompts
    enqueued from the web chat) are run headless via `claude -p`; queued CLI
    commands and host-driven workflow runs are handled as before. Registered as
    `tasks`; `task_queue` remains as a deprecated alias for existing cron jobs.
    """


def _detect_host_agent() -> bool:
    """True when an AI agent host (Claude Code, OpenClaw, …) drives this CLI."""
    try:
        detected, _ = detect_agent_tool()
    except Exception:
        return False
    return bool(detected) and detected != "deepvista-cli"


def _list_all_machine_agents() -> list[tuple[str, str | None]]:
    """Return (agent_id, project_id) for every locally registered agent.

    Deduplicates by agent_id so a registration file collision never causes
    double-claiming.
    """
    seen: set[str] = set()
    results: list[tuple[str, str | None]] = []
    if not AGENTS_DIR.exists():
        return results
    candidates: list[tuple[float, Path]] = []
    for path in AGENTS_DIR.glob("*.json"):
        try:
            candidates.append((path.stat().st_mtime, path))
        except OSError:
            continue
    candidates.sort(reverse=True)
    for _, path in candidates:
        try:
            data = _json.loads(path.read_text())
        except (OSError, _json.JSONDecodeError):
            continue
        aid = data.get("agent_id")
        if not aid or aid in seen:
            continue
        seen.add(aid)
        results.append((aid, data.get("project_id")))
    return results


def _ensure_agents_for_all_projects(ctx: click.Context) -> list[tuple[str, str | None]]:
    """Fetch all projects and ensure a local agent is registered for each one.

    For projects that already have a local registration the existing agent_id
    is reused; for new projects a fresh agent is registered on-the-fly using
    the detected host agent type (or ``deepvista-cli`` as a fallback).  Any
    locally registered agents whose project no longer appears in the API
    response are appended at the end so nothing is silently dropped.

    Returns ``(agent_id, project_id)`` for every project, deduped by agent_id.
    On network failure falls back to the local-only list so offline/cron runs
    still work.
    """
    try:
        detected, _ = detect_agent_tool()
    except Exception:
        detected = None
    agent_type = detected or "deepvista-cli"

    try:
        projects_raw = _client(ctx).get("/projects")
    except SystemExit:
        click.echo("  [warn] could not fetch projects — using locally registered agents only", err=True)
        return _list_all_machine_agents()

    # Backend returns a JSON array directly for GET /projects.
    projects: list[dict] = projects_raw if isinstance(projects_raw, list) else projects_raw.get("projects", [])

    seen_agent_ids: set[str] = set()
    result: list[tuple[str, str | None]] = []

    for project in projects:
        project_id = project.get("id")
        if not project_id:
            continue

        # Reuse an existing local registration for this project.
        existing_id = _load_agent_id(agent_type, DEFAULT_AGENT_ROLE, project_id)
        if existing_id:
            if existing_id not in seen_agent_ids:
                seen_agent_ids.add(existing_id)
                result.append((existing_id, project_id))
            continue

        # No local record — register a new agent for this project.
        try:
            config = _build_config_snapshot(agent_type)
            data = _client(ctx).post(
                "/agents",
                {
                    "name": _default_agent_name(agent_type),
                    "agent_type": agent_type,
                    "agent_role": DEFAULT_AGENT_ROLE,
                    "config": config,
                },
                extra_headers={"X-Project-Id": project_id},
            )
            agent = data.get("agent")
            if not agent or not agent.get("id"):
                click.echo(
                    f"  [warn] could not register agent for project {project_id}: {data.get('error', 'unknown')}",
                    err=True,
                )
                continue
            agent_id: str = agent["id"]
            agent_role_saved = agent.get("agent_role", DEFAULT_AGENT_ROLE)
            _save_agent_id(agent_type, agent_id, agent_role_saved, project_id)

            # Mirror what `agents register` does: install hooks + initial sync.
            profile = getattr(ctx.obj, "profile", "default")
            _install_hooks(agent_type, profile)
            try:
                _client(ctx).post(
                    f"/agents/{agent_id}/sync",
                    {"status": "online", "sync_type": "manual", "config_patch": config},
                    extra_headers={"X-Project-Id": project_id},
                )
            except SystemExit:
                pass  # sync failure is non-fatal

            click.echo(f"  registered agent {agent_id} for project {project_id}", err=True)
        except SystemExit:
            click.echo(f"  [warn] could not register agent for project {project_id} — skipping", err=True)
            continue

        if agent_id not in seen_agent_ids:
            seen_agent_ids.add(agent_id)
            result.append((agent_id, project_id))

    # Append any locally registered agents whose project wasn't in the API
    # response (e.g. old registrations, shared projects that were later removed).
    for agent_id, proj_id in _list_all_machine_agents():
        if agent_id not in seen_agent_ids:
            seen_agent_ids.add(agent_id)
            result.append((agent_id, proj_id))

    return result


def _print_run_header(
    ctx: click.Context,
    agents: list[tuple[str, str | None]],
    host_mode: bool,
    run_once: bool,
    poll_interval: int,
    total_time: int | None,
) -> None:
    """Print a startup banner summarising the account, agents, and polling config."""
    tokens = get_valid_token(credentials_path(getattr(ctx.obj, "profile", "default")))
    account = (tokens.email or tokens.user_id or "unknown") if tokens else "not authenticated"
    profile = getattr(ctx.obj, "profile", "default")
    api_url = getattr(ctx.obj, "api_url", "")

    if run_once:
        mode = "single pass (--run-once)"
    elif total_time:
        mode = f"every {poll_interval}s for up to {total_time}s"
    else:
        mode = f"every {poll_interval}s until interrupted"

    click.echo(f"account  : {account}")
    if len(agents) == 1:
        agent_id, project_id = agents[0]
        click.echo(f"agent    : {agent_id}")
        click.echo(f"project  : {project_id or '(unknown — re-register to capture)'}")
    else:
        click.echo(f"agents   : {len(agents)} (all registered on this machine)")
        for agent_id, project_id in agents:
            click.echo(f"  {agent_id}  project={project_id or 'unknown'}")
    click.echo(f"profile  : {profile}  ({api_url})")
    click.echo(f"mode     : {mode}")
    click.echo(f"host     : {'yes (workflow tasks included)' if host_mode else 'no (command tasks only)'}")
    click.echo("")


def _claim_and_run(ctx: click.Context, agent_id: str, host_mode: bool) -> tuple[list[dict], list[dict]]:
    """One claim/execute pass; returns (command task results, workflow tasks)."""
    data = _client(ctx).post(
        f"/agents/{agent_id}/task-queue/claim",
        None if host_mode else {"command_only": True},
    )
    if not data.get("success"):
        output_error(1, "Failed to claim tasks", data.get("error", "Unknown error"))
        raise SystemExit(1)

    tasks = data.get("tasks") or []
    command_tasks = [t for t in tasks if not _is_workflow_task(t)]
    # Workflow tasks only reach this list in host mode (headless claims are
    # command_only) — the guard below covers a backend that predates the
    # filter, so a cron tick never swallows a packet nobody will read.
    workflow_tasks = [t for t in tasks if _is_workflow_task(t)] if host_mode else []

    results = [_execute_task(ctx, agent_id, task) for task in command_tasks]
    return results, workflow_tasks


def _claim_and_run_all(
    ctx: click.Context,
    agents: list[tuple[str, str | None]],
    host_mode: bool,
) -> tuple[list[dict], list[tuple[str, dict]]]:
    """Claim and execute tasks for all agents in one poll pass.

    Returns ``(command_results, [(agent_id, workflow_task)])``.
    Per-agent claim failures are logged and skipped so a single stale
    registration does not prevent the others from being serviced.
    """
    all_results: list[dict] = []
    all_workflow_tasks: list[tuple[str, dict]] = []
    for agent_id, project_id in agents:
        # DV-1247: task cards (plain prompts run via `claude -p`) — independent
        # of host mode; a Machine runs them headless without a host agent.
        try:
            all_results.extend(_claim_and_run_task_cards(ctx, agent_id, project_id))
        except SystemExit:
            click.echo(f"  [warn] failed to claim task cards for agent {agent_id} — skipping", err=True)

        # DV-936 / DV-955: queued CLI commands + host-driven workflow runs.
        try:
            results, wf_tasks = _claim_and_run(ctx, agent_id, host_mode)
        except SystemExit:
            click.echo(f"  [warn] failed to claim tasks for agent {agent_id} — skipping", err=True)
            continue
        all_results.extend(results)
        all_workflow_tasks.extend((agent_id, t) for t in wf_tasks)
    return all_results, all_workflow_tasks


@task_queue_group.command("run")
@click.option("--type", "agent_type", default=None, help="Resolve agent by type from local storage.")
@click.option("--role", "agent_role", default=None, help="Resolve agent by role (with --type).")
@click.option("--project", "project_id", default=None, help="Restrict to the agent registered for this project ID.")
@click.option(
    "--host",
    "host_mode",
    is_flag=True,
    default=False,
    help=(
        "Claim workflow tasks too and emit their run packets for the host "
        "agent to drive (DV-955). Auto-enabled when an agent host is "
        "detected; headless runs claim command tasks only."
    ),
)
@click.option(
    "--run-once",
    "--run_once",
    "run_once",
    is_flag=True,
    default=False,
    help="Do a single claim/execute pass and exit (what the `setup` cron entry uses).",
)
@click.option(
    "--poll-interval",
    default=DEFAULT_POLL_INTERVAL_SECONDS,
    show_default=True,
    type=click.IntRange(1, 3600),
    help="Seconds to wait between polls.",
)
@click.option(
    "--total-time",
    default=None,
    type=click.IntRange(1),
    help="Stop polling after this many seconds (default: poll until interrupted).",
)
@click.pass_context
def task_queue_run(
    ctx: click.Context,
    agent_type: str | None,
    agent_role: str | None,
    project_id: str | None,
    host_mode: bool,
    run_once: bool,
    poll_interval: int,
    total_time: int | None,
) -> None:
    """Poll task queues for all registered agents and execute claimed tasks (DV-1079).

    By default (no --type/--role/--project filter) polls EVERY agent registered
    on this machine, so tasks across all projects are serviced in one run.
    Pass --type/--role/--project to restrict to a single matching agent.

    Default mode polls in the foreground — claim, execute, sleep
    --poll-interval, repeat — until --total-time elapses (or forever when
    unset), which keeps every registered agent on this machine picking up
    work without a cron job. --run-once does a single pass and exits; the
    cron entry installed by `task_queue setup` uses it.

    Only one `task_queue run` may be active per machine — concurrent
    invocations exit with an error instead of double-claiming the queue.

    Plain command tasks run sequentially via subprocess and their results
    are reported back. Workflow tasks (webhook-queued skill runs) are only
    claimed in host mode: their run packets are printed for the surrounding
    agent to drive — polling stops at that point so the host agent can act —
    and the entries stay ``running`` until the agent calls
    ``task_queue complete``.
    """
    if not _acquire_run_lock():
        output_error(
            2,
            "Another `task_queue run` is already active on this machine",
            f"Stop it first or wait for it to finish (lock: {RUN_LOCK_PATH}, pid: {_read_lock_pid()}).",
        )
        raise SystemExit(2)

    if agent_type or agent_role or project_id:
        # Explicit filter — single-agent mode (backward-compatible).
        agent_id, resolved_project_id = _require_machine_agent_id(agent_type, agent_role, project_id)
        agents = [(agent_id, resolved_project_id)]
    else:
        # No filter — auto-register for every project the user has access to,
        # then poll all of them so nothing is missed.
        agents = _ensure_agents_for_all_projects(ctx)
        if not agents:
            output_error(3, "No projects or registered agents found", "Run 'deepvista auth login' then retry.")
            raise SystemExit(3)

    host_mode = host_mode or _detect_host_agent()

    _print_run_header(ctx, agents, host_mode, run_once, poll_interval, total_time)

    started = time.monotonic()
    polls = 0
    total_results: list[dict] = []
    try:
        while True:
            polls += 1
            ts = time.strftime("%H:%M:%S")
            results, workflow_tasks = _claim_and_run_all(ctx, agents, host_mode)
            total_results.extend(results)

            # Print a per-poll status line so the operator can see the poller
            # is alive and whether new events arrived.
            if results or workflow_tasks:
                failed = sum(1 for r in results if r["status"] == "failed")
                task_count = len(results) + len(workflow_tasks)
                detail = f"{task_count} task(s) claimed"
                if workflow_tasks:
                    detail += f" ({len(workflow_tasks)} workflow)"
                if failed:
                    detail += f", {failed} failed"
                click.echo(f"[{ts}] poll #{polls} → {detail}")
            else:
                click.echo(f"[{ts}] poll #{polls} → no new tasks")

            # Emit structured output for non-empty passes (and always for
            # --run-once so cron logs capture every tick).
            if run_once or results or workflow_tasks:
                agent_ids = agents[0][0] if len(agents) == 1 else [a[0] for a in agents]
                _output(
                    ctx,
                    {
                        "agent_id": agent_ids,
                        "tasks_run": len(results),
                        "failed": sum(1 for r in results if r["status"] == "failed"),
                        "results": results,
                        "workflow_tasks": len(workflow_tasks),
                    },
                    title="Task Queue",
                )

            # Workflow packets go last so the runtime contract (and its
            # completion instructions) is the freshest thing in the host
            # agent's context.
            for wf_agent_id, task in workflow_tasks:
                _emit_workflow_task(ctx, wf_agent_id, task)

            if run_once:
                return
            if workflow_tasks:
                # The host agent has packets to drive; blocking it inside the
                # poll loop would deadlock the run. Hand control back.
                return
            if total_time is not None and (time.monotonic() - started) + poll_interval > total_time:
                agent_ids = agents[0][0] if len(agents) == 1 else [a[0] for a in agents]
                _output(
                    ctx,
                    {
                        "agent_id": agent_ids,
                        "polls": polls,
                        "tasks_run": len(total_results),
                        "failed": sum(1 for r in total_results if r["status"] == "failed"),
                    },
                    title="Task Queue (polling finished)",
                )
                return
            next_ts = time.strftime("%H:%M:%S", time.localtime(time.time() + poll_interval))
            click.echo(f"  sleeping {poll_interval}s — next poll at {next_ts}")
            time.sleep(poll_interval)
    finally:
        _release_run_lock()


TASK_CARD_COLUMNS = ["id", "status", "title", "agent_id", "created_at"]


@task_queue_group.command("list")
@click.option("--type", "agent_type", default=None, help="Resolve agent by type from local storage.")
@click.option("--role", "agent_role", default=None, help="Resolve agent by role (with --type).")
@click.option("--project", "project_id", default=None, help="Restrict to the agent registered for this project ID.")
@click.option(
    "--status", "status_filter", default=None, help="Filter task cards by status (pending/running/completed/failed)."
)
@click.pass_context
def task_queue_list(
    ctx: click.Context,
    agent_type: str | None,
    agent_role: str | None,
    project_id: str | None,
    status_filter: str | None,
) -> None:
    """Show the tasks dispatched to this Machine (DV-1247).

    Lists **task cards** (web-chat prompts) claimable by this Machine in its
    project. Read-only.
    """
    agent_id, resolved_project_id = _require_machine_agent_id(agent_type, agent_role, project_id)
    headers = {"X-Project-Id": resolved_project_id} if resolved_project_id else None
    params = {"status": status_filter} if status_filter else None
    data = _client(ctx).get(f"/agents/{agent_id}/tasks", params=params, extra_headers=headers)
    if data.get("error"):
        output_error(1, "Failed to list tasks", data["error"])
        raise SystemExit(1)
    tasks = data.get("tasks", [])
    _output(
        ctx,
        {"agent_id": agent_id, "project_id": resolved_project_id, "tasks": tasks, "count": len(tasks)},
        columns=TASK_CARD_COLUMNS,
        title="Tasks",
    )


@task_queue_group.command("complete")
@click.argument("task_id")
@click.option(
    "--status",
    type=click.Choice(["completed", "failed"]),
    required=True,
    help="Terminal outcome of the workflow task.",
)
@click.option("--note", default=None, help="Short outcome note stored as the task's output tail.")
@click.option("--type", "agent_type", default=None, help="Resolve agent by type from local storage.")
@click.option("--role", "agent_role", default=None, help="Resolve agent by role (with --type).")
@click.option("--project", "project_id", default=None, help="Restrict to the agent registered for this project ID.")
@click.pass_context
def task_queue_complete(
    ctx: click.Context,
    task_id: str,
    status: str,
    note: str | None,
    agent_type: str | None,
    agent_role: str | None,
    project_id: str | None,
) -> None:
    """Report the terminal outcome of a claimed workflow task (DV-955).

    Called by the host agent after driving a webhook-queued workflow run to
    its end (`deepvista skill complete`) — or to its failure. Plain command
    tasks report automatically; this is only needed for workflow tasks,
    which stay ``running`` until someone reports them.
    """
    agent_id, _ = _require_machine_agent_id(agent_type, agent_role, project_id)
    data = _client(ctx).post(
        f"/agents/{agent_id}/task-queue/{task_id}/result",
        {"status": status, "exit_code": 0 if status == "completed" else 1, "output_tail": note},
    )
    if not data.get("success"):
        output_error(1, "Failed to report task result", data.get("error", "Unknown error"))
        raise SystemExit(1)
    _output(ctx, {"agent_id": agent_id, "task": data.get("task")}, title="Task Queue")


# ---------------------------------------------------------------------------
# Cron setup
# ---------------------------------------------------------------------------


def _read_crontab() -> list[str]:
    """Current user crontab lines ([] when none exists)."""
    try:
        proc = subprocess.run(  # noqa: S603
            ["crontab", "-l"],  # noqa: S607
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if proc.returncode != 0:
        return []
    return proc.stdout.splitlines()


def _write_crontab(lines: list[str]) -> bool:
    content = "\n".join(lines) + ("\n" if lines else "")
    try:
        proc = subprocess.run(  # noqa: S603
            ["crontab", "-"],  # noqa: S607
            input=content,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return proc.returncode == 0


def _cron_entry(interval: int, profile: str) -> str:
    binary = _deepvista_binary()
    profile_flag = f" --profile {profile}" if profile and profile != "default" else ""
    return f"*/{interval} * * * * {binary}{profile_flag} tasks run --run-once >> {CRON_LOG_PATH} 2>&1 {CRON_MARKER}"


@task_queue_group.command("setup")
@click.option(
    "--interval",
    default=5,
    show_default=True,
    type=click.IntRange(1, 1440),
    help="Poll interval in minutes.",
)
@click.option("--remove", is_flag=True, default=False, help="Uninstall the cron entry instead.")
@click.pass_context
def task_queue_setup(ctx: click.Context, interval: int, remove: bool) -> None:
    """Install a crontab entry that runs `deepvista task_queue run --run-once` periodically.

    An alternative to leaving a foreground `task_queue run` polling: cron
    fires a single claim/execute pass per tick. The run lock keeps a tick
    from overlapping a foreground poller. Idempotent — re-running replaces
    any existing entry. Use --remove to uninstall. Crontab only
    (macOS/Linux); on Windows, schedule `deepvista task_queue run
    --run-once` with Task Scheduler instead.

    Cron runs are headless: they execute plain command tasks only and
    leave workflow tasks (webhook-queued skill runs) pending. Drive those
    from an agent session with `deepvista task_queue run --host`.

    > [!CAUTION] This is a write command — confirm with the user before executing.
    """
    if sys.platform == "win32":
        output_error(1, "Unsupported platform", "Crontab setup is macOS/Linux only.")
        raise SystemExit(1)

    existing = _read_crontab()
    kept = [line for line in existing if CRON_MARKER not in line]
    entry = None if remove else _cron_entry(interval, getattr(ctx.obj, "profile", "default"))
    updated = kept + ([entry] if entry else [])

    if ctx.obj.dry_run:
        _output(
            ctx,
            {
                "dry_run": True,
                "would": "remove cron entry" if remove else "install cron entry",
                "entry": entry,
                "removed_entries": [line for line in existing if CRON_MARKER in line],
            },
            title="Dry Run: Task Queue Setup",
        )
        return

    if remove and len(kept) == len(existing):
        _output(ctx, {"removed": False, "message": "No task-queue cron entry installed."}, title="Task Queue Setup")
        return

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if not _write_crontab(updated):
        output_error(1, "Failed to update crontab", "Is `crontab` available on this machine?")
        raise SystemExit(1)

    if remove:
        _output(ctx, {"removed": True}, title="Task Queue Setup")
    else:
        _output(
            ctx,
            {"installed": True, "interval_minutes": interval, "entry": entry, "log": str(CRON_LOG_PATH)},
            title="Task Queue Setup",
        )
