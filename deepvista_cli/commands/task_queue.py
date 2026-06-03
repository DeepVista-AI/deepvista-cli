"""deepvista task_queue — pull-based execution of queued CLI commands (DV-936).

The web app enqueues DeepVista CLI commands onto a managed agent's
`task_queue`; this command group lets the agent's machine poll and run them:

  deepvista task_queue run    — claim pending tasks and execute them
  deepvista task_queue list   — show this machine's queue
  deepvista task_queue setup  — install a crontab entry that polls periodically

Safety: only commands whose first token is `deepvista` are executed
(shlex-parsed, shell=False). The backend enforces the same allowlist at
enqueue time; the check here guards against tampered queue rows.
"""

from __future__ import annotations

import json as _json
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import click

from deepvista_cli.client.http import DeepVistaClient
from deepvista_cli.client.origin import detect_agent_tool
from deepvista_cli.commands.agents import AGENTS_DIR, _load_agent_id
from deepvista_cli.config import CONFIG_DIR
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _client(ctx: click.Context) -> DeepVistaClient:
    return ctx.obj._client


def _output(ctx: click.Context, data: object, **kwargs: object) -> None:
    format_output(data, ctx.obj.output_format, **kwargs)  # type: ignore[arg-type]


def _resolve_machine_agent_id(agent_type: str | None, agent_role: str | None) -> str | None:
    """Find the registered agent this machine's queue belongs to.

    Resolution order: explicit --type/--role, then the detected host tool,
    then the most recently registered agent of any type on this machine.
    """
    if agent_type:
        return _load_agent_id(agent_type, agent_role)

    try:
        detected, _ = detect_agent_tool()
    except Exception:
        detected = None
    if detected:
        agent_id = _load_agent_id(detected, agent_role)
        if agent_id:
            return agent_id

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
            agent_id = _json.loads(path.read_text()).get("agent_id")
        except (OSError, _json.JSONDecodeError):
            continue
        if agent_id:
            return agent_id
    return None


def _require_machine_agent_id(agent_type: str | None, agent_role: str | None) -> str:
    agent_id = _resolve_machine_agent_id(agent_type, agent_role)
    if not agent_id:
        output_error(3, "No registered agent on this machine", "Run 'deepvista agents register' first.")
        raise SystemExit(3)
    return agent_id


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
# Command group
# ---------------------------------------------------------------------------


@click.group("task_queue")
def task_queue_group() -> None:
    """Run CLI commands queued for this machine's agent."""


@task_queue_group.command("run")
@click.option("--type", "agent_type", default=None, help="Resolve agent by type from local storage.")
@click.option("--role", "agent_role", default=None, help="Resolve agent by role (with --type).")
@click.pass_context
def task_queue_run(ctx: click.Context, agent_type: str | None, agent_role: str | None) -> None:
    """Claim pending tasks for this machine's agent and execute them.

    Returns immediately when the queue is empty, so it's cheap as a cron
    tick. Each claimed task runs sequentially via subprocess and its result
    (status, exit code, output tail) is reported back to the backend.
    """
    agent_id = _require_machine_agent_id(agent_type, agent_role)

    data = _client(ctx).post(f"/agents/{agent_id}/task-queue/claim")
    if not data.get("success"):
        output_error(1, "Failed to claim tasks", data.get("error", "Unknown error"))
        raise SystemExit(1)

    tasks = data.get("tasks") or []
    if not tasks:
        _output(ctx, {"agent_id": agent_id, "tasks_run": 0}, title="Task Queue")
        return

    results = [_execute_task(ctx, agent_id, task) for task in tasks]
    failed = sum(1 for r in results if r["status"] == "failed")
    _output(
        ctx,
        {"agent_id": agent_id, "tasks_run": len(results), "failed": failed, "results": results},
        title="Task Queue",
    )


@task_queue_group.command("list")
@click.option("--type", "agent_type", default=None, help="Resolve agent by type from local storage.")
@click.option("--role", "agent_role", default=None, help="Resolve agent by role (with --type).")
@click.pass_context
def task_queue_list(ctx: click.Context, agent_type: str | None, agent_role: str | None) -> None:
    """Show the task queue for this machine's agent.

    Read-only.
    """
    agent_id = _require_machine_agent_id(agent_type, agent_role)
    data = _client(ctx).get(f"/agents/{agent_id}/task-queue")
    if data.get("error"):
        output_error(1, "Failed to list tasks", data["error"])
        raise SystemExit(1)
    tasks = data.get("tasks", [])
    _output(
        ctx,
        {"agent_id": agent_id, "tasks": tasks, "count": len(tasks)},
        columns=TASK_COLUMNS,
        title="Task Queue",
    )


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
    return f"*/{interval} * * * * {binary}{profile_flag} task_queue run >> {CRON_LOG_PATH} 2>&1 {CRON_MARKER}"


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
    """Install a crontab entry that runs `deepvista task_queue run` periodically.

    Idempotent — re-running replaces any existing entry. Use --remove to
    uninstall. Crontab only (macOS/Linux); on Windows, schedule
    `deepvista task_queue run` with Task Scheduler instead.

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
