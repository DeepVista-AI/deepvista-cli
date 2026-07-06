"""deepvista tasks — pull-based execution of work dispatched to this Machine (DV-936/DV-1247).

The web app dispatches work onto a managed agent's queue — task cards (plain
prompts run headless via `claude -p`) and queued CLI commands; this command
group lets the agent's machine poll and run them:

  deepvista tasks run      — poll for pending tasks and execute them
  deepvista tasks list     — show this machine's queue
  deepvista tasks complete — report a workflow task's outcome (host agent)
  deepvista tasks setup    — install a crontab entry that polls periodically

Polling (DV-1079): `run` polls in the foreground by default (--poll-interval,
bounded by --total-time when given); --run-once does a single claim/execute
pass, which is what the cron entry installed by `setup` uses. A PID lock file
allows only one `tasks run` per machine at a time, so a foreground
poller and cron ticks never double-claim.

Workflow tasks (DV-955): webhook-queued `deepvista skill run` entries can't
be subprocess-executed — a workflow needs the surrounding host agent (Claude
Code etc.) to drive its phases. `tasks run --host` claims them and
emits their run packets to stdout for the host agent; headless runs (cron)
claim command-only so workflow tasks stay pending until a host run. The
host agent reports the outcome via `tasks complete` after
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
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import click

from deepvista_cli.auth.tokens import get_valid_token
from deepvista_cli.client.http import DeepVistaClient
from deepvista_cli.client.origin import detect_agent_tool
from deepvista_cli.commands.agents import (
    AGENTS_DIR,
    _load_agent_id,
    resolve_or_register_machine,
)
from deepvista_cli.commands.project import _projects
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

# Marker comment identifying crontab entries owned by `tasks setup`.
# The literal value is unchanged so `setup` still finds and replaces cron
# entries installed by older versions (when this group was named `task_queue`).
CRON_MARKER = "# deepvista-task-queue"

CRON_LOG_PATH = CONFIG_DIR / "task_queue.log"

# Seconds between polls when `run` is left in its default polling mode.
DEFAULT_POLL_INTERVAL_SECONDS = 10

# Idle polls between heartbeat lines in default (non-verbose) mode (~5 min at 10s).
IDLE_HEARTBEAT_POLLS = 30

# Single-instance lock for `tasks run` (DV-1079) — holds the owner PID.
RUN_LOCK_PATH = CONFIG_DIR / "task_queue.run.lock"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _StaleAgentError(Exception):
    """Raised when a local agent registration is invalid on the server."""

    def __init__(self, agent_id: str, *, recoverable: bool = True) -> None:
        super().__init__(agent_id)
        self.agent_id = agent_id
        self.recoverable = recoverable


def _client(ctx: click.Context) -> DeepVistaClient:
    return ctx.obj._client


def _output(ctx: click.Context, data: object, **kwargs: object) -> None:
    format_output(data, ctx.obj.output_format, **kwargs)  # type: ignore[arg-type]


def _resolve_machine_agent_id(
    agent_type: str | None,
    project_id: str | None = None,
) -> tuple[str, str | None] | None:
    """Find the registered agent this machine's queue belongs to.

    Resolution order: explicit --type/--project, then the detected host
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
        agent_id = _load_agent_id(agent_type, project_id)
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
        agent_id = _load_agent_id(detected, project_id)
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
    project_id: str | None = None,
) -> tuple[str, str | None]:
    result = _resolve_machine_agent_id(agent_type, project_id)
    if not result:
        output_error(
            3,
            "No registered agent on this machine",
            "Run `deepvista tasks run` to auto-register, or `deepvista agents sync`.",
        )
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
    workflow and reports the outcome via ``tasks complete``. Only an
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
    """Take the machine-wide single-instance lock for `tasks run` (DV-1079).

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

# Default cap for a task-card run. 10 minutes covers most local CLI operations;
# callers can override per-task via the ``timeout_seconds`` frontmatter field.
TASK_RUN_TIMEOUT_SECONDS = 600

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


# DV-1428: minimum gap between live-activity reports (note POST + phase dvNote
# update) so a chatty run's tool-call stream can't hammer the backend — one
# write per interval is plenty for a human watching the Mermaid diagram.
ACTIVITY_REPORT_MIN_INTERVAL_SECONDS = 3.0

# Tool-input keys worth surfacing as a one-line activity summary, in priority
# order (first match wins). Best-effort — arbitrary tools fall back to no arg
# summary rather than guessing at their shape.
_ACTIVITY_SUMMARY_KEYS = ("command", "file_path", "path", "pattern", "query", "url", "description")


def _summarize_tool_input(tool_input: dict) -> str:
    """One-line, length-capped summary of a tool call's args for live progress."""
    for key in _ACTIVITY_SUMMARY_KEYS:
        value = tool_input.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:80]
    return ""


def _summarize_stream_event(event: dict) -> str | None:
    """Extract a short "what's happening now" line from a stream-json event (DV-1428).

    Fed by `claude -p --output-format stream-json --verbose`: assistant
    messages carry `tool_use` (a tool call starting) and `text` (the agent's
    running commentary) content blocks; everything else (system/hook noise,
    user tool_result echoes) has nothing worth surfacing. Returns None when
    the event doesn't map to a displayable activity line.
    """
    if event.get("type") != "assistant":
        return None
    for block in (event.get("message") or {}).get("content") or []:
        block_type = block.get("type")
        if block_type == "tool_use":
            name = block.get("name") or "tool"
            arg_summary = _summarize_tool_input(block.get("input") or {})
            return f"🔧 {name}: {arg_summary}" if arg_summary else f"🔧 {name}"
        if block_type == "text":
            text = " ".join((block.get("text") or "").split())
            if text:
                return f"💬 {text[:100]}"
    return None


def _run_task_card(ctx: click.Context, agent_id: str, project_id: str | None, task: dict) -> dict:
    """Run one claimed task card via `claude -p` and report the result back.

    The prompt is handed to Claude Code as ``/deepvista <prompt>`` so the run
    boots with the DeepVista skill context (knowledge base, notes, the CLI).
    Runs stream incrementally (``--output-format stream-json``, DV-1428) so
    tool-call activity can be reported live — via the task's note trail (the
    channel DV-1376's chat "Wait for Local Agent" panel streams from) and, for
    workflow-dispatched tasks, the Mermaid diagram's dvNote annotation on the
    active phase. The final ``result`` event's text becomes the run's output
    (a linked output card is created backend-side when non-empty); the exit
    code decides completed vs. failed.
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
    # Inject task_id into the prompt so the local Claude Code agent can call
    # `deepvista tasks note <task_id> "<note>"` to write intermediate progress
    # notes that the web agent polling the card can see in real-time.
    task_context = (
        f"[Task ID: {task_id}. "
        f"After completing each significant step — or if you need human input to continue — "
        f'run: deepvista tasks note {task_id} "<brief note>" '
        f"so the delegating agent can track your progress.]\n\n"
    )
    argv = [
        _claude_binary(),
        "-p",
        f"/deepvista {task_context}{prompt}",
        "--permission-mode",
        permission_mode,
        "--output-format",
        "stream-json",
        "--verbose",
    ]

    # DV-1277: expose the originating chat + this task to the headless run so the
    # session card the Claude Code plugin writes (`deepvista session init`) can
    # cross-reference them. The run record shares the same task_id, so a run and
    # its session both resolve back to the web chat that triggered the task.
    run_env = {**os.environ, "DEEPVISTA_TASK_ID": task_id}
    source_chat_id = str(task.get("source_chat_id") or "").strip()
    if source_chat_id:
        run_env["DEEPVISTA_SOURCE_CHAT_ID"] = source_chat_id

    short_id = task_id[:8]
    title = task.get("title") or ""
    prompt_preview = (prompt[:120] + "…") if len(prompt) > 120 else prompt
    task_label = f"{title!r} — {prompt_preview}" if title else prompt_preview
    created_at_raw = task.get("created_at") or ""
    workflow_name = (
        task.get("workflow_name")
        or task.get("skill_name")
        or task.get("source_workflow_name")
        or task.get("triggered_by")
        or ""
    )
    click.echo(f"  ▶ running task {short_id}… via claude -p (project {project_id or '?'})", err=True)
    meta_parts = []
    if created_at_raw:
        display_ts = created_at_raw[:19].replace("T", " ") if "T" in created_at_raw else created_at_raw
        meta_parts.append(f"added {display_ts}")
    if workflow_name:
        meta_parts.append(f"workflow: {workflow_name}")
    if meta_parts:
        click.echo(f"    {' · '.join(meta_parts)}", err=True)
    click.echo(f"    prompt: {task_label}", err=True)

    # Per-task timeout: the enqueuing agent can override the default via
    # the ``timeout_seconds`` frontmatter field (e.g. for long research tasks).
    task_timeout = int(task.get("timeout_seconds") or 0) or TASK_RUN_TIMEOUT_SECONDS

    skill_id = str(task.get("skill_id") or "").strip()
    phase_label = str(task.get("phase_label") or "").strip()

    _done = threading.Event()
    _start = time.monotonic()
    _activity_text = [task_label]  # 1-item list so nested closures can mutate it
    _last_reported = [float("-inf")]  # -inf guarantees the first report always fires

    def _report_activity(text: str, *, force: bool = False) -> None:
        """Push live progress to the task's note trail + (workflow tasks
        only) the Mermaid diagram's dvNote annotation (DV-1428). Throttled —
        one write per ``ACTIVITY_REPORT_MIN_INTERVAL_SECONDS`` is plenty for a
        human watching the diagram, and the note-append endpoint shouldn't see
        one write per tool call on a chatty run."""
        _activity_text[0] = text
        now = time.monotonic()
        if not force and now - _last_reported[0] < ACTIVITY_REPORT_MIN_INTERVAL_SECONDS:
            return
        _last_reported[0] = now
        try:
            _client(ctx).post(f"/agents/{agent_id}/tasks/{task_id}/note", {"note": text}, extra_headers=headers)
        except Exception as exc:
            click.echo(f"  [warn] progress note failed: {exc}", err=True)
        if skill_id and phase_label:
            _update_phase_note(ctx, skill_id, phase_label, text)

    _last_logged_activity = [""]
    _last_logged_elapsed = [0]

    def _progress() -> None:
        while not _done.wait(10):
            elapsed = int(time.monotonic() - _start)
            activity = _activity_text[0]
            activity_changed = activity != _last_logged_activity[0]
            milestone = elapsed in (10, 30, 60) or (elapsed > 60 and elapsed - _last_logged_elapsed[0] >= 60)
            if not activity_changed and not milestone:
                continue
            _last_logged_activity[0] = activity
            _last_logged_elapsed[0] = elapsed
            summary = activity if len(activity) <= 60 else activity[:57] + "…"
            click.echo(f"    … {elapsed}s  {summary}", err=True)
            _report_activity(f"⏳ still running ({elapsed}s) — {activity}", force=True)

    _t = threading.Thread(target=_progress, daemon=True)
    _t.start()

    status = "failed"
    exit_code: int | None = None
    output = ""
    timed_out = threading.Event()
    try:
        proc = subprocess.Popen(  # noqa: S603 — argv built from a fixed binary + literal flags
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=cwd,
            env=run_env,
            bufsize=1,
        )

        def _watchdog() -> None:
            if not _done.wait(task_timeout):
                timed_out.set()
                proc.kill()

        threading.Thread(target=_watchdog, daemon=True).start()

        result_text = ""
        result_is_error: bool | None = None
        tail_lines: list[str] = []
        assert proc.stdout is not None
        for raw_line in proc.stdout:
            line = raw_line.strip()
            if not line:
                continue
            tail_lines.append(line)
            try:
                event = _json.loads(line)
            except ValueError:
                continue
            summary = _summarize_stream_event(event)
            if summary:
                _report_activity(summary)
            if event.get("type") == "result":
                result_text = str(event.get("result") or "")
                result_is_error = bool(event.get("is_error"))

        proc.wait()
        stderr_text = (proc.stderr.read() or "").strip() if proc.stderr else ""

        if timed_out.is_set():
            status, exit_code, output = "failed", None, f"claude run timed out after {task_timeout}s"
        else:
            exit_code = proc.returncode
            status = "completed" if exit_code == 0 and result_is_error is not True else "failed"
            output = result_text.strip() or stderr_text or "\n".join(tail_lines[-40:])
    except FileNotFoundError:
        status, exit_code, output = (
            "failed",
            None,
            "Claude Code binary not found. Install it or set DEEPVISTA_CLAUDE_BIN.",
        )
    except OSError as exc:
        status, exit_code, output = "failed", None, str(exc)
    finally:
        _done.set()
        _t.join()

    elapsed = int(time.monotonic() - _start)
    icon = "✓" if status == "completed" else "✗"
    click.echo(f"  {icon} task {short_id}… {status} (exit {exit_code}, {elapsed}s)", err=True)

    _client(ctx).post(
        f"/agents/{agent_id}/tasks/{task_id}/result",
        {"status": status, "exit_code": exit_code, "output": output, "output_title": task.get("title")},
        extra_headers=headers,
    )
    result: dict = {"task_id": task_id, "title": task.get("title"), "status": status, "exit_code": exit_code}
    if created_at_raw:
        result["created_at"] = created_at_raw
    if workflow_name:
        result["workflow"] = workflow_name

    # Update the workflow phase dvNote annotation so the diagram reflects the
    # task result before resuming — the annotation is visible immediately in the UI.
    if skill_id and phase_label:
        status_icon = "✅" if status == "completed" else "❌"
        short_output = (output or "")[:120]
        if len(output or "") > 120:
            short_output += "…"
        note = f"{status_icon} Task {short_id} {status}."
        if short_output:
            note += f" {short_output}"
        _update_phase_note(ctx, skill_id, phase_label, note)

    # Resume the triggering workflow run so the server can continue from where
    # it dispatched this task. ``skill_id`` is stamped on the task at enqueue
    # time; without it the parent run stays paused and never completes.
    if skill_id:
        click.echo(f"  ↩ resuming workflow {skill_id[:8]}… via deepvista skill run", err=True)
        _resume_workflow(ctx, skill_id)

    return result


def _update_phase_note(ctx: click.Context, skill_id: str, phase_label: str, note_text: str) -> None:
    """Call ``POST /workflow_phase`` with action='note' to update the dvNote annotation."""
    try:
        _client(ctx).post(
            "/workflow_phase",
            {"card_id": skill_id, "phase_label": phase_label, "action": "note", "note_text": note_text},
        )
    except Exception as exc:
        click.echo(f"  [warn] phase note update failed: {exc}", err=True)


def _resume_workflow(ctx: click.Context, skill_id: str) -> None:
    """Run ``deepvista skill run --mode host <skill_id>`` to resume the parent workflow."""
    profile_flag = []
    profile = getattr(ctx.obj, "profile", None)
    if profile and profile != "default":
        profile_flag = ["--profile", profile]
    argv = [_deepvista_binary(), *profile_flag, "skill", "run", "--mode", "host", skill_id]
    try:
        subprocess.run(  # noqa: S603 — argv built from validated binary + literal args
            argv,
            timeout=TASK_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired:
        click.echo(f"  [warn] skill resume timed out for {skill_id[:8]}…", err=True)
    except OSError as exc:
        click.echo(f"  [warn] skill resume failed: {exc}", err=True)


# Signals that an agent/machine no longer exists server-side. The backend returns
# error_code AGENT_NOT_FOUND for both "Agent not found" (task queue) and "Machine
# not found" (task cards), and project_not_found when the whole project is gone.
# Any of these means the local registration is stale — prune it once and stop
# polling for it, instead of re-emitting the claim-failure block on every poll
# (DV-1429: a stale `deepvista-cli` agent spammed the loop forever).
_AGENT_GONE_CODES = {"agent_not_found", "project_not_found"}
_AGENT_GONE_MESSAGES = {"agent not found", "machine not found"}


def _agent_is_gone(data: dict, status_code: int) -> bool:
    """True when a claim response says this agent/machine is gone server-side."""
    if status_code == 404:
        return True
    code = str(data.get("error_code") or "").lower()
    message = str(data.get("error") or "").lower()
    return code in _AGENT_GONE_CODES or message in _AGENT_GONE_MESSAGES


def _prune_stale_agent(agent_id: str, reason: str) -> None:
    """Delete the local registration file for a stale agent_id and log it once."""
    for aid, _, path in _iter_agent_files():
        if aid == agent_id:
            try:
                path.unlink()
            except OSError:
                pass
            break
    click.echo(f"  removed stale agent {agent_id} ({reason})", err=True)


def _claim_and_run_task_cards(ctx: click.Context, agent_id: str, project_id: str | None) -> list[dict]:
    """Claim this Machine's pending task cards in ``project_id`` and run each headless.

    Raises ``_StaleAgentError`` when the server reports the agent/machine is gone
    (AGENT_NOT_FOUND / project_not_found / 404) and the local registration file has
    been deleted, so the caller drops this agent_id from the live poll list and
    stops re-emitting the claim-failure block every poll (DV-1429).
    """
    headers = {"X-Project-Id": project_id} if project_id else None
    data = _client(ctx).post_nofatal(f"/agents/{agent_id}/tasks/claim", None, extra_headers=headers)
    status_code = data.get("_status_code", 200) if isinstance(data, dict) else 200
    if isinstance(data, dict) and (data.get("error") or status_code >= 400 or not data.get("success", True)):
        if _agent_is_gone(data, status_code):
            code = str(data.get("error_code") or "").lower()
            reason = (
                f"project {project_id} no longer accessible"
                if code == "project_not_found"
                else str(data.get("error") or "not found on server")
            )
            _prune_stale_agent(agent_id, reason)
            raise _StaleAgentError(agent_id, recoverable=code != "project_not_found")
        detail = data.get("error") or data.get("detail") or "unknown"
        click.echo(
            f"  [warn] could not claim task cards for agent {agent_id}: {detail}",
            err=True,
        )
        return []
    tasks = data.get("tasks") or []
    return [_run_task_card(ctx, agent_id, project_id, task) for task in tasks]


# ---------------------------------------------------------------------------
# Command group
# ---------------------------------------------------------------------------


@click.group("tasks")
def tasks_group() -> None:
    """Run tasks dispatched to this Machine (DV-1247).

    `tasks run` polls for work and executes it: **task cards** (plain prompts
    enqueued from the web chat) are run headless via `claude -p`; queued CLI
    commands and host-driven workflow runs are handled as before.
    """


def _detect_host_agent() -> bool:
    """True when an AI agent host (Claude Code, OpenClaw, …) drives this CLI."""
    try:
        detected, _ = detect_agent_tool()
    except Exception:
        return False
    return bool(detected) and detected != "deepvista-cli"


def _iter_agent_files() -> list[tuple[str, str | None, Path]]:
    """Return (agent_id, project_id, path) for every locally registered agent, newest-first.

    Deduplicates by agent_id so a registration file collision never causes
    double-claiming.
    """
    if not AGENTS_DIR.exists():
        return []
    seen: set[str] = set()
    candidates: list[tuple[float, Path]] = []
    for path in AGENTS_DIR.glob("*.json"):
        try:
            candidates.append((path.stat().st_mtime, path))
        except OSError:
            continue
    result: list[tuple[str, str | None, Path]] = []
    for _, path in sorted(candidates, reverse=True):
        try:
            data = _json.loads(path.read_text())
        except (OSError, _json.JSONDecodeError):
            continue
        aid = data.get("agent_id")
        if not aid or aid in seen:
            continue
        seen.add(aid)
        result.append((aid, data.get("project_id"), path))
    return result


def _find_registered_agent_for_project(project_id: str) -> str | None:
    """Return a locally registered agent_id for ``project_id``, any type."""
    for agent_id, proj_id, _ in _iter_agent_files():
        if proj_id == project_id:
            return agent_id
    return None


def _prune_agent_registrations_for_gone_projects(accessible_project_ids: set[str]) -> None:
    """Delete local agent files whose ``project_id`` is absent from GET /projects."""
    for agent_id, proj_id, path in _iter_agent_files():
        if not proj_id or proj_id in accessible_project_ids:
            continue
        try:
            path.unlink()
            click.echo(
                f"  removed stale agent {agent_id} (project {proj_id} no longer accessible)",
                err=True,
            )
        except OSError:
            pass


def _append_scoped_local_agents(
    seen_agent_ids: set[str],
    result: list[tuple[str, str | None]],
    *,
    scope_project_ids: set[str] | None = None,
) -> None:
    """Append locally registered agents not yet in *result* (legacy globals in all-project mode)."""
    for agent_id, proj_id, _path in _iter_agent_files():
        if agent_id in seen_agent_ids:
            continue
        if scope_project_ids is not None and (not proj_id or proj_id not in scope_project_ids):
            continue
        seen_agent_ids.add(agent_id)
        result.append((agent_id, proj_id))


def _resolve_working_project(ctx: click.Context, project_override: str | None = None) -> str | None:
    """Return the project ``tasks run`` should scope to.

    Resolution order: per-command ``--project`` → global working project
    (``project use`` / global ``--project`` / ``DEEPVISTA_PROJECT_ID``) →
    backend default via ``GET /projects/me``.
    """
    if project_override:
        return project_override
    profile_project = getattr(ctx.obj, "project_id", None)
    if profile_project:
        return profile_project
    try:
        data = _client(ctx).get("/projects/me")
    except SystemExit:
        return None
    if isinstance(data, dict):
        pid = data.get("id")
        return str(pid) if pid else None
    return None


def _ensure_agents_for_projects(
    ctx: click.Context,
    *,
    project_ids: set[str] | None = None,
) -> tuple[list[tuple[str, str | None]], dict[str, str]]:
    """Ensure local agent registrations exist for the given project(s).

    When ``project_ids`` is ``None``, every accessible project is covered
    (legacy all-projects mode).  Otherwise only the listed projects are
    registered and returned.

    For each project, ``resolve_or_register_machine`` validates the local cache
    against the server and registers (or adopts) a managed agent when needed.

    Stale local registrations whose project_id no longer appears in the API
    response are deleted before lookups so they are not reused; agents with
    no project_id (legacy global registrations) are kept only in all-projects
    mode.

    Returns ``((agent_id, project_id), project_names)`` where ``project_names``
    maps project_id → human-readable name.
    """
    try:
        detected, _ = detect_agent_tool()
    except Exception:
        detected = None
    agent_type = detected or "deepvista-cli"

    projects = _projects(ctx)
    accessible_project_ids: set[str] = set()
    for project in projects:
        if project_id := project.get("id"):
            accessible_project_ids.add(str(project_id))
    _prune_agent_registrations_for_gone_projects(accessible_project_ids)

    # Build project_id → name map from the API response.
    project_names: dict[str, str] = {}
    seen_agent_ids: set[str] = set()
    result: list[tuple[str, str | None]] = []

    for project in projects:
        project_id = project.get("id")
        if not project_id:
            continue
        if project_ids is not None and project_id not in project_ids:
            continue

        project_name = project.get("name") or project.get("title") or ""
        project_names[project_id] = project_name

        agent_id = resolve_or_register_machine(
            ctx,
            project_id,
            agent_type=agent_type,
            project_name=project_name or None,
        )
        if not agent_id:
            continue
        if agent_id not in seen_agent_ids:
            seen_agent_ids.add(agent_id)
            result.append((agent_id, project_id))

    _append_scoped_local_agents(seen_agent_ids, result, scope_project_ids=project_ids)

    return result, project_names


def _agent_type_label(agent_id: str) -> str:
    """Return the agent_type stored in the local registration file for this agent."""
    if not AGENTS_DIR.exists():
        return ""
    for path in AGENTS_DIR.glob("*.json"):
        try:
            data = _json.loads(path.read_text())
            if data.get("agent_id") == agent_id:
                return data.get("agent_type", "")
        except (OSError, _json.JSONDecodeError):
            continue
    return ""


def _project_display(project_id: str | None, project_names: dict[str, str]) -> str:
    """Format a project ID as 'Name (short-id)' when a name is known, else just the ID."""
    if not project_id:
        return "unknown"
    name = project_names.get(project_id, "")
    short = project_id[:8] + "…"
    return f"{name}  ({short})" if name else project_id


def _format_uptime(seconds: float) -> str:
    """Compact human duration for poll status lines."""
    total = int(seconds)
    if total < 60:
        return f"{total}s"
    minutes, secs = divmod(total, 60)
    if minutes < 60:
        return f"{minutes}m {secs}s" if secs else f"{minutes}m"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes}m"


def _styled_dim(text: str) -> str:
    """Dim text when stderr is a TTY (poll status lines go to stdout but color follows stderr)."""
    if sys.stderr.isatty():
        return click.style(text, dim=True)
    return text


def _should_emit_poll_json(
    ctx: click.Context,
    *,
    run_once: bool,
    total_time: int | None,
    has_work: bool,
    is_final_summary: bool,
    verbose: bool,
) -> bool:
    """Whether to emit structured output for a poll pass.

    Cron (--run-once) and bounded runs (--total-time) keep JSON for scripting.
    Continuous foreground polling skips per-task JSON when stdout is a TTY so
    operators are not drowned in duplicate blobs after every task.
    """
    if run_once or is_final_summary:
        return True
    if total_time is not None and has_work:
        return True
    if verbose and has_work:
        return True
    if has_work and sys.stdout.isatty():
        return False
    return has_work


class _PollStatus:
    """Human-friendly poll loop logging with quiet idle by default."""

    def __init__(self, poll_interval: int, *, verbose: bool, quiet: bool) -> None:
        self.poll_interval = poll_interval
        self.verbose = verbose
        self.quiet = quiet
        self.idle_streak = 0
        self.started = time.monotonic()
        self.tasks_ok = 0
        self.tasks_failed = 0

    def on_idle(self, poll_num: int) -> None:
        if self.quiet:
            return
        self.idle_streak += 1
        if self.verbose:
            ts = time.strftime("%H:%M:%S")
            next_ts = time.strftime("%H:%M:%S", time.localtime(time.time() + self.poll_interval))
            click.echo(
                f"[{ts}] idle · poll #{poll_num} · next in {self.poll_interval}s (at {next_ts})",
            )
        elif self.idle_streak == 1:
            click.echo(
                _styled_dim(
                    f"listening · poll #{poll_num} · every {self.poll_interval}s · Ctrl+C to stop",
                ),
            )
        elif self.idle_streak % IDLE_HEARTBEAT_POLLS == 0:
            uptime = _format_uptime(time.monotonic() - self.started)
            click.echo(
                _styled_dim(
                    f"… {uptime} idle ({self.idle_streak} polls) · {self.tasks_ok} done · {self.tasks_failed} failed …",
                ),
            )

    def on_work(self, poll_num: int, detail: str) -> None:
        if self.quiet:
            return
        self.idle_streak = 0
        ts = time.strftime("%H:%M:%S")
        if self.verbose:
            click.echo(f"[{ts}] poll #{poll_num} → {detail}")
        else:
            click.echo(f"[{ts}] {detail}")

    def record_results(self, results: list[dict]) -> None:
        for result in results:
            if result.get("status") == "failed":
                self.tasks_failed += 1
            else:
                self.tasks_ok += 1

    def on_tasks_finished(self, results: list[dict]) -> None:
        if self.quiet or self.verbose or not results:
            return
        failed = sum(1 for r in results if r.get("status") == "failed")
        ok = len(results) - failed
        uptime = _format_uptime(time.monotonic() - self.started)
        parts = [f"listening · {ok} task(s) done"]
        if failed:
            parts.append(f"{failed} failed")
        parts.append(f"uptime {uptime}")
        click.echo(_styled_dim(" · ".join(parts)))

    def on_shutdown(self, polls: int) -> None:
        if self.quiet:
            return
        uptime = _format_uptime(time.monotonic() - self.started)
        click.echo(
            _styled_dim(
                f"stopped · {polls} polls · {self.tasks_ok + self.tasks_failed} task(s) "
                f"({self.tasks_ok} ok, {self.tasks_failed} failed) · uptime {uptime}",
            ),
        )


def _print_run_header(
    ctx: click.Context,
    agents: list[tuple[str, str | None]],
    project_names: dict[str, str],
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
        agent_type = _agent_type_label(agent_id)
        click.echo(f"agent    : {agent_id}" + (f"  [{agent_type}]" if agent_type else ""))
        click.echo(f"project  : {_project_display(project_id, project_names)}")
    else:
        click.echo(f"agents   : {len(agents)} (all registered on this machine)")
        for agent_id, project_id in agents:
            agent_type = _agent_type_label(agent_id)
            proj = _project_display(project_id, project_names)
            type_tag = f"  [{agent_type}]" if agent_type else ""
            click.echo(f"  {agent_id[:8]}…{type_tag}  →  {proj}")
    click.echo(f"profile  : {profile}  ({api_url})")
    click.echo(f"mode     : {mode}")
    click.echo(f"host     : {'yes (workflow tasks included)' if host_mode else 'no (command tasks only)'}")
    click.echo("")


def _claim_and_run(ctx: click.Context, agent_id: str, host_mode: bool) -> tuple[list[dict], list[dict]]:
    """One claim/execute pass; returns (command task results, workflow tasks)."""
    data = _client(ctx).post_nofatal(
        f"/agents/{agent_id}/task-queue/claim",
        None if host_mode else {"command_only": True},
    )
    status_code = data.get("_status_code", 200) if isinstance(data, dict) else 200
    if isinstance(data, dict) and _agent_is_gone(data, status_code):
        code = str(data.get("error_code") or "").lower()
        _prune_stale_agent(agent_id, str(data.get("error") or "not found on server"))
        raise _StaleAgentError(agent_id, recoverable=code != "project_not_found")
    if status_code >= 400 or not data.get("success", True):
        error = data.get("error", "Unknown error") if isinstance(data, dict) else "Unknown error"
        if isinstance(error, dict):
            error = error.get("detail") or error.get("message") or "unknown"
        output_error(1, "Failed to claim tasks", error)
        raise SystemExit(1)

    tasks = data.get("tasks") or []
    command_tasks = [t for t in tasks if not _is_workflow_task(t)]
    # Workflow tasks only reach this list in host mode (headless claims are
    # command_only) — the guard below covers a backend that predates the
    # filter, so a cron tick never swallows a packet nobody will read.
    workflow_tasks = [t for t in tasks if _is_workflow_task(t)] if host_mode else []

    results = [_execute_task(ctx, agent_id, task) for task in command_tasks]
    return results, workflow_tasks


def _with_agent_recovery[T](
    ctx: click.Context,
    agent_id: str,
    project_id: str | None,
    operation: str,
    fn: Callable[[str], T],
) -> tuple[T | None, str, bool]:
    """Run ``fn(agent_id)``; on a recoverable stale error, re-register and retry once."""
    try:
        return fn(agent_id), agent_id, False
    except _StaleAgentError as exc:
        if not exc.recoverable or not project_id:
            return None, agent_id, True
        new_id = resolve_or_register_machine(ctx, project_id, quiet=True)
        if not new_id:
            return None, agent_id, True
        click.echo(f"  re-registered agent {new_id} for project {project_id} ({operation})", err=True)
        try:
            return fn(new_id), new_id, False
        except _StaleAgentError:
            return None, new_id, True


def _claim_and_run_all(
    ctx: click.Context,
    agents: list[tuple[str, str | None]],
    host_mode: bool,
) -> tuple[list[dict], list[tuple[str, dict]], set[str], dict[str, str]]:
    """Claim and execute tasks for all agents in one poll pass.

    Returns ``(command_results, [(agent_id, workflow_task)], pruned_agent_ids,
    replacements)`` where ``replacements`` maps a stale agent_id to its
    re-registered successor.
    """
    all_results: list[dict] = []
    all_workflow_tasks: list[tuple[str, dict]] = []
    pruned: set[str] = set()
    replacements: dict[str, str] = {}
    for agent_id, project_id in agents:
        card_results, active_id, failed = _with_agent_recovery(
            ctx,
            agent_id,
            project_id,
            "task cards",
            lambda aid: _claim_and_run_task_cards(ctx, aid, project_id),
        )
        if failed:
            pruned.add(agent_id)
            if active_id != agent_id:
                pruned.add(active_id)
            continue
        if active_id != agent_id:
            replacements[agent_id] = active_id
        all_results.extend(card_results or [])

        try:
            queue_out, queue_agent_id, queue_failed = _with_agent_recovery(
                ctx,
                active_id,
                project_id,
                "task queue",
                lambda aid: _claim_and_run(ctx, aid, host_mode),
            )
        except SystemExit:
            click.echo(f"  [warn] failed to claim tasks for agent {active_id} — skipping", err=True)
            continue
        if queue_failed or queue_out is None:
            pruned.add(agent_id)
            if queue_agent_id != agent_id:
                pruned.add(queue_agent_id)
            continue
        queue_results, wf_tasks = queue_out
        if queue_agent_id != agent_id:
            replacements[agent_id] = queue_agent_id
        active_id = queue_agent_id

        all_results.extend(queue_results)
        all_workflow_tasks.extend((active_id, t) for t in wf_tasks)
    return all_results, all_workflow_tasks, pruned, replacements


@tasks_group.command("run")
@click.option("--type", "agent_type", default=None, help="Resolve agent by type from local storage.")
@click.option(
    "--project",
    "project_id",
    default=None,
    help="Scope to this project (overrides the working project for this call only).",
)
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
@click.option(
    "--verbose",
    "-v",
    is_flag=True,
    default=False,
    help="Log every poll (including idle ticks and sleep schedule).",
)
@click.option(
    "--quiet",
    "-q",
    is_flag=True,
    default=False,
    help="Suppress poll status lines; keep structured output and task execution logs.",
)
@click.pass_context
def tasks_run(
    ctx: click.Context,
    agent_type: str | None,
    project_id: str | None,
    host_mode: bool,
    run_once: bool,
    poll_interval: int,
    total_time: int | None,
    verbose: bool,
    quiet: bool,
) -> None:
    """Poll the task queue for the current project and execute claimed tasks (DV-1079).

    Scopes to the working project (``project use``, global ``--project``, or
    ``DEEPVISTA_PROJECT_ID``), falling back to your backend default project.
    Override per-invocation with ``--project``. Pass ``--type`` to resolve a
    specific local agent registration instead.

    Default mode polls in the foreground — claim, execute, sleep
    --poll-interval, repeat — until --total-time elapses (or forever when
    unset). --run-once does a single pass and exits; the cron entry installed
    by `tasks setup` uses it.

    Only one `tasks run` may be active per machine — concurrent
    invocations exit with an error instead of double-claiming the queue.

    Plain command tasks run sequentially via subprocess and their results
    are reported back. Workflow tasks (webhook-queued skill runs) are only
    claimed in host mode: their run packets are printed for the surrounding
    agent to drive — polling stops at that point so the host agent can act —
    and the entries stay ``running`` until the agent calls
    ``tasks complete``.
    """
    if not _acquire_run_lock():
        output_error(
            2,
            "Another `tasks run` is already active on this machine",
            f"Stop it first or wait for it to finish (lock: {RUN_LOCK_PATH}, pid: {_read_lock_pid()}).",
        )
        raise SystemExit(2)

    project_names: dict[str, str] = {}
    working_project = _resolve_working_project(ctx, project_id)
    if agent_type:
        # Explicit agent filter — single-agent mode (backward-compatible).
        if working_project:
            agent_id = resolve_or_register_machine(ctx, working_project, agent_type=agent_type)
            if not agent_id:
                output_error(
                    3,
                    f"No registered agent for project {working_project}",
                    "Run 'deepvista tasks run' (auto-registers) or check project access.",
                )
                raise SystemExit(3)
            agents = [(agent_id, working_project)]
        else:
            agent_id, resolved_project_id = _require_machine_agent_id(agent_type, working_project)
            agents = [(agent_id, resolved_project_id)]
    else:
        if not working_project:
            output_error(
                3,
                "No working project to poll",
                "Run `deepvista project use <id>` or pass `--project <id>`.",
            )
            raise SystemExit(3)
        agents, project_names = _ensure_agents_for_projects(ctx, project_ids={working_project})
        if not agents:
            output_error(
                3,
                f"No registered agent for project {working_project}",
                "Run 'deepvista tasks run' (auto-registers) or check project access.",
            )
            raise SystemExit(3)

    host_mode = host_mode or _detect_host_agent()

    _print_run_header(ctx, agents, project_names, host_mode, run_once, poll_interval, total_time)

    poll_status: _PollStatus | None = None
    if not run_once:
        poll_status = _PollStatus(poll_interval, verbose=verbose, quiet=quiet)

    started = time.monotonic()
    polls = 0
    total_results: list[dict] = []
    try:
        while True:
            polls += 1
            results, workflow_tasks, pruned, replacements = _claim_and_run_all(ctx, agents, host_mode)
            if pruned:
                agents = [(aid, pid) for aid, pid in agents if aid not in pruned]
            if replacements:
                agents = [(replacements.get(aid, aid), pid) for aid, pid in agents]
            total_results.extend(results)
            if poll_status is not None:
                poll_status.record_results(results)

            has_work = bool(results or workflow_tasks)
            if has_work:
                failed = sum(1 for r in results if r["status"] == "failed")
                task_count = len(results) + len(workflow_tasks)
                detail = f"{task_count} task(s) claimed"
                if workflow_tasks:
                    detail += f" ({len(workflow_tasks)} workflow)"
                if failed:
                    detail += f", {failed} failed"
                if poll_status is not None:
                    poll_status.on_work(polls, detail)
                elif not quiet:
                    ts = time.strftime("%H:%M:%S")
                    click.echo(f"[{ts}] poll #{polls} → {detail}")
            elif poll_status is not None:
                poll_status.on_idle(polls)
            elif verbose and not quiet:
                ts = time.strftime("%H:%M:%S")
                next_ts = time.strftime("%H:%M:%S", time.localtime(time.time() + poll_interval))
                click.echo(
                    f"[{ts}] idle · poll #{polls} · next in {poll_interval}s (at {next_ts})",
                )

            emit_json = _should_emit_poll_json(
                ctx,
                run_once=run_once,
                total_time=total_time,
                has_work=has_work,
                is_final_summary=False,
                verbose=verbose,
            )
            if emit_json:
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

            if poll_status is not None and results:
                poll_status.on_tasks_finished(results)

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
                if poll_status is not None:
                    poll_status.on_shutdown(polls)
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
            if verbose and not quiet:
                next_ts = time.strftime("%H:%M:%S", time.localtime(time.time() + poll_interval))
                click.echo(f"  sleeping {poll_interval}s — next poll at {next_ts}")
            time.sleep(poll_interval)
    except KeyboardInterrupt:
        if poll_status is not None:
            poll_status.on_shutdown(polls)
        raise SystemExit(130) from None
    finally:
        _release_run_lock()


TASK_CARD_COLUMNS = ["id", "status", "title", "agent_id", "created_at"]


@tasks_group.command("list")
@click.option("--type", "agent_type", default=None, help="Resolve agent by type from local storage.")
@click.option("--project", "project_id", default=None, help="Restrict to the agent registered for this project ID.")
@click.option(
    "--status", "status_filter", default=None, help="Filter task cards by status (pending/running/completed/failed)."
)
@click.pass_context
def tasks_list(
    ctx: click.Context,
    agent_type: str | None,
    project_id: str | None,
    status_filter: str | None,
) -> None:
    """Show the tasks dispatched to this Machine (DV-1247).

    Lists **task cards** (web-chat prompts) claimable by this Machine in its
    project. Read-only.
    """
    agent_id, resolved_project_id = _require_machine_agent_id(agent_type, project_id)
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


def _task_timestamp(task: dict) -> datetime | None:
    """Best-effort last-activity timestamp for a task-queue entry (DV-1429)."""
    for key in ("completed_at", "updated_at", "started_at", "created_at"):
        raw = task.get(key)
        if not raw:
            continue
        try:
            ts = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except ValueError:
            continue
        return ts if ts.tzinfo else ts.replace(tzinfo=UTC)
    return None


@tasks_group.command("clean")
@click.argument("task_ids", nargs=-1)
@click.option(
    "--status",
    "statuses",
    multiple=True,
    type=click.Choice(["completed", "failed", "cancelled", "wont_fix"]),
    help="Terminal status(es) to delete (repeatable). Default: completed + failed.",
)
@click.option(
    "--older-than",
    "older_than_days",
    type=int,
    default=None,
    help="Only delete tasks last updated more than N days ago.",
)
@click.option("--type", "agent_type", default=None, help="Resolve agent by type from local storage.")
@click.option("--project", "project_id", default=None, help="Restrict to the agent registered for this project ID.")
@click.option("--dry-run", is_flag=True, default=False, help="Preview what would be deleted without deleting.")
@click.pass_context
def tasks_clean(
    ctx: click.Context,
    task_ids: tuple[str, ...],
    statuses: tuple[str, ...],
    older_than_days: int | None,
    agent_type: str | None,
    project_id: str | None,
    dry_run: bool,
) -> None:
    """Delete terminated entries from this Machine's task queue (DV-1429).

    With explicit TASK_IDS, deletes exactly those. Otherwise deletes queue entries
    in a terminal state (default: completed + failed), optionally limited to those
    last updated more than --older-than days ago. Inspect first with
    `deepvista tasks list`; preview with --dry-run.

    > [!CAUTION] Destructive — deleted tasks cannot be recovered. Confirm with the user.
    """
    agent_id, resolved_project_id = _require_machine_agent_id(agent_type, project_id)
    headers = {"X-Project-Id": resolved_project_id} if resolved_project_id else None
    client = _client(ctx)

    if task_ids:
        target_ids = list(dict.fromkeys(task_ids))  # dedupe, preserve order
    else:
        wanted = {s.lower() for s in statuses} or {"completed", "failed"}
        data = client.get(f"/agents/{agent_id}/task-queue", extra_headers=headers)
        if isinstance(data, dict) and data.get("error"):
            output_error(1, "Failed to list task queue", data["error"])
            raise SystemExit(1)
        queue = (data.get("tasks") if isinstance(data, dict) else None) or []
        cutoff = datetime.now(UTC) - timedelta(days=older_than_days) if older_than_days is not None else None
        target_ids = []
        for task in queue:
            if str(task.get("status") or "").lower() not in wanted:
                continue
            if cutoff is not None:
                ts = _task_timestamp(task)
                if ts is None or ts >= cutoff:
                    continue
            if task.get("id"):
                target_ids.append(task["id"])

    if not target_ids:
        click.echo("  nothing to clean.", err=True)
        _output(ctx, {"agent_id": agent_id, "deleted": [], "count": 0}, title="Tasks Cleaned")
        return

    if dry_run:
        _output(
            ctx,
            {"dry_run": True, "agent_id": agent_id, "would_delete": target_ids, "count": len(target_ids)},
            title="Dry Run: Clean Tasks",
        )
        return

    deleted: list[str] = []
    failed: list[dict] = []
    for tid in target_ids:
        try:
            resp = client.delete(f"/agents/{agent_id}/task-queue/{tid}")
        except SystemExit:
            failed.append({"id": tid, "error": "delete request failed"})
            continue
        if isinstance(resp, dict) and not resp.get("success", True):
            failed.append({"id": tid, "error": resp.get("error", "unknown")})
        else:
            deleted.append(tid)

    _output(
        ctx,
        {"agent_id": agent_id, "deleted": deleted, "failed": failed, "count": len(deleted)},
        title="Tasks Cleaned",
    )
    if failed:
        raise SystemExit(1)


@tasks_group.command("note")
@click.argument("task_id")
@click.argument("note")
@click.option("--type", "agent_type", default=None, help="Resolve agent by type from local storage.")
@click.option("--project", "project_id", default=None, help="Restrict to the agent registered for this project ID.")
@click.pass_context
def tasks_note(
    ctx: click.Context,
    task_id: str,
    note: str,
    agent_type: str | None,
    project_id: str | None,
) -> None:
    """Append a progress note to a running task card's run log (DV-1247).

    Called by the local Claude Code agent after completing a step or when human
    input is required. The web agent polling the task card sees these notes in
    the description and can relay them to the user in real-time.

    Example (from inside a headless claude -p run):
        deepvista tasks note <task-id> "Step 1 done: found 3 failing tests"
        deepvista tasks note <task-id> "Needs human: please approve the PR at github.com/…"
    """
    agent_id, resolved_project_id = _require_machine_agent_id(agent_type, project_id)
    headers = {"X-Project-Id": resolved_project_id} if resolved_project_id else None
    data = _client(ctx).post(
        f"/agents/{agent_id}/tasks/{task_id}/note",
        {"note": note},
        extra_headers=headers,
    )
    if not data.get("success"):
        output_error(1, "Failed to append task note", data.get("error", "Unknown error"))
        raise SystemExit(1)
    click.echo(f"  ✎ note appended to task {task_id[:8]}…", err=True)


@tasks_group.command("complete")
@click.argument("task_id")
@click.option(
    "--status",
    type=click.Choice(["completed", "failed"]),
    required=True,
    help="Terminal outcome of the workflow task.",
)
@click.option("--note", default=None, help="Short outcome note stored as the task's output tail.")
@click.option("--type", "agent_type", default=None, help="Resolve agent by type from local storage.")
@click.option("--project", "project_id", default=None, help="Restrict to the agent registered for this project ID.")
@click.pass_context
def tasks_complete(
    ctx: click.Context,
    task_id: str,
    status: str,
    note: str | None,
    agent_type: str | None,
    project_id: str | None,
) -> None:
    """Report the terminal outcome of a claimed workflow task (DV-955).

    Called by the host agent after driving a webhook-queued workflow run to
    its end (`deepvista skill complete`) — or to its failure. Plain command
    tasks report automatically; this is only needed for workflow tasks,
    which stay ``running`` until someone reports them.
    """
    agent_id, _ = _require_machine_agent_id(agent_type, project_id)
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


@tasks_group.command("setup")
@click.option(
    "--interval",
    default=5,
    show_default=True,
    type=click.IntRange(1, 1440),
    help="Poll interval in minutes.",
)
@click.option("--remove", is_flag=True, default=False, help="Uninstall the cron entry instead.")
@click.pass_context
def tasks_setup(ctx: click.Context, interval: int, remove: bool) -> None:
    """Install a crontab entry that runs `deepvista tasks run --run-once` periodically.

    An alternative to leaving a foreground `tasks run` polling: cron
    fires a single claim/execute pass per tick. The run lock keeps a tick
    from overlapping a foreground poller. Idempotent — re-running replaces
    any existing entry (including ones installed by older versions under the
    legacy `task_queue` name). Use --remove to uninstall. Crontab only
    (macOS/Linux); on Windows, schedule `deepvista tasks run
    --run-once` with Task Scheduler instead.

    Cron runs are headless: they execute plain command tasks only and
    leave workflow tasks (webhook-queued skill runs) pending. Drive those
    from an agent session with `deepvista tasks run --host`.

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
