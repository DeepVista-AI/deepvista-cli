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

from deepvista_cli.client.http import DeepVistaClient
from deepvista_cli.client.origin import detect_agent_tool
from deepvista_cli.commands.agents import AGENTS_DIR, _load_agent_id
from deepvista_cli.commands.skill import emit_host_run_packet
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

# Seconds between polls when `run` is left in its default polling mode.
DEFAULT_POLL_INTERVAL_SECONDS = 60

# Single-instance lock for `task_queue run` (DV-1079) — holds the owner PID.
RUN_LOCK_PATH = CONFIG_DIR / "task_queue.run.lock"


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
# Command group
# ---------------------------------------------------------------------------


@click.group("task_queue")
def task_queue_group() -> None:
    """Run CLI commands queued for this machine's agent."""


def _detect_host_agent() -> bool:
    """True when an AI agent host (Claude Code, OpenClaw, …) drives this CLI."""
    try:
        detected, _ = detect_agent_tool()
    except Exception:
        return False
    return bool(detected) and detected != "deepvista-cli"


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


@task_queue_group.command("run")
@click.option("--type", "agent_type", default=None, help="Resolve agent by type from local storage.")
@click.option("--role", "agent_role", default=None, help="Resolve agent by role (with --type).")
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
    host_mode: bool,
    run_once: bool,
    poll_interval: int,
    total_time: int | None,
) -> None:
    """Poll this machine's agent queue and execute claimed tasks (DV-1079).

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
    agent_id = _require_machine_agent_id(agent_type, agent_role)
    host_mode = host_mode or _detect_host_agent()

    if not _acquire_run_lock():
        output_error(
            2,
            "Another `task_queue run` is already active on this machine",
            f"Stop it first or wait for it to finish (lock: {RUN_LOCK_PATH}, pid: {_read_lock_pid()}).",
        )
        raise SystemExit(2)

    started = time.monotonic()
    polls = 0
    total_results: list[dict] = []
    try:
        while True:
            polls += 1
            results, workflow_tasks = _claim_and_run(ctx, agent_id, host_mode)
            total_results.extend(results)

            # A polling loop stays quiet on empty passes; --run-once always
            # reports so cron logs show every tick.
            if run_once or results or workflow_tasks:
                _output(
                    ctx,
                    {
                        "agent_id": agent_id,
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
            for task in workflow_tasks:
                _emit_workflow_task(ctx, agent_id, task)

            if run_once:
                return
            if workflow_tasks:
                # The host agent has packets to drive; blocking it inside the
                # poll loop would deadlock the run. Hand control back.
                return
            if total_time is not None and (time.monotonic() - started) + poll_interval > total_time:
                _output(
                    ctx,
                    {
                        "agent_id": agent_id,
                        "polls": polls,
                        "tasks_run": len(total_results),
                        "failed": sum(1 for r in total_results if r["status"] == "failed"),
                    },
                    title="Task Queue (polling finished)",
                )
                return
            time.sleep(poll_interval)
    finally:
        _release_run_lock()


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
@click.pass_context
def task_queue_complete(
    ctx: click.Context,
    task_id: str,
    status: str,
    note: str | None,
    agent_type: str | None,
    agent_role: str | None,
) -> None:
    """Report the terminal outcome of a claimed workflow task (DV-955).

    Called by the host agent after driving a webhook-queued workflow run to
    its end (`deepvista skill complete`) — or to its failure. Plain command
    tasks report automatically; this is only needed for workflow tasks,
    which stay ``running`` until someone reports them.
    """
    agent_id = _require_machine_agent_id(agent_type, agent_role)
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
    return (
        f"*/{interval} * * * * {binary}{profile_flag} task_queue run --run-once >> {CRON_LOG_PATH} 2>&1 {CRON_MARKER}"
    )


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
