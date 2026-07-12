"""deepvista tasks — pull-based execution of work dispatched to this Machine (DV-1247).

The web app dispatches work as **task cards** — plain prompts run headless via
``claude -p "/deepvista <prompt>"``. This command group lets the Machine poll
and run them:

  deepvista tasks run      — poll for pending tasks and execute them
  deepvista tasks list     — show this machine's task cards
  deepvista tasks clean    — delete terminated task cards
  deepvista tasks setup    — install a crontab entry that polls periodically

Polling (DV-1079): ``run`` polls in the foreground by default (--poll-interval,
bounded by --total-time when given); --run-once does a single claim/execute
pass, which is what the cron entry installed by ``setup`` uses. A PID lock file
allows only one ``tasks run`` per machine at a time. Headless runs execute
concurrently up to --max-parallel (default 5).
"""

from __future__ import annotations

import json as _json
import os
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

import click

from deepvista_cli.auth.tokens import get_valid_token
from deepvista_cli.client.http import DeepVistaClient
from deepvista_cli.client.origin import detect_agent_tool
from deepvista_cli.commands.agents import (
    AGENTS_DIR,
    MACHINES_DIR,
    _load_machine_id,
    resolve_or_register_machine,
)
from deepvista_cli.commands.project import _projects
from deepvista_cli.config import CONFIG_DIR, credentials_path
from deepvista_cli.output.formatter import format_output, output_error

# Reported output is truncated to a tail (mirrors the backend cap on task cards).
OUTPUT_TAIL_MAX_CHARS = 2000

# Subprocess budget for workflow resume after a task card completes.
TASK_TIMEOUT_SECONDS = 600

# Marker comment identifying crontab entries owned by `tasks setup`.
# The literal value is unchanged so `setup` still finds and replaces cron
# entries installed by older versions (when this group was named `task_queue`).
CRON_MARKER = "# deepvista-task-queue"

CRON_LOG_PATH = CONFIG_DIR / "task_queue.log"

# Seconds between polls when `run` is left in its default polling mode.
DEFAULT_POLL_INTERVAL_SECONDS = 10

# Max concurrent headless task runs per `tasks run` poller.
DEFAULT_MAX_PARALLEL_TASKS = 5

# Idle polls between heartbeat lines in default (non-verbose) mode (~5 min at 10s).
IDLE_HEARTBEAT_POLLS = 30

# Single-instance lock for `tasks run` (DV-1079) — holds the owner PID.
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
    project_id: str | None = None,
) -> tuple[str, str | None] | None:
    """Find this Machine's registered agent_id for ``project_id``.

    Identity is ``(project_id, fingerprint)``. ``agent_type`` is soft metadata.
    """
    _ = agent_type
    if not project_id:
        return None
    agent_id = _load_machine_id(project_id)
    if not agent_id:
        return None
    return (agent_id, project_id)


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
    binary = shutil.which("deepvista")
    if binary:
        return binary
    if sys.argv and Path(sys.argv[0]).name == "deepvista":
        return str(Path(sys.argv[0]).resolve())
    return "deepvista"


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


def _refresh_agents_for_poll(
    ctx: click.Context,
    agents: list[tuple[str, str | None]],
    project_names: dict[str, str],
    *,
    agent_type: str | None = None,
) -> list[tuple[str, str | None]]:
    """Re-validate registration and sync online before each claim pass."""
    refreshed: list[tuple[str, str | None]] = []
    seen: set[str] = set()
    for _agent_id, project_id in agents:
        if not project_id:
            if _agent_id not in seen:
                seen.add(_agent_id)
                refreshed.append((_agent_id, project_id))
            continue
        new_id = resolve_or_register_machine(
            ctx,
            project_id,
            agent_type=agent_type,
            project_name=project_names.get(project_id),
            quiet=True,
        )
        if new_id and new_id not in seen:
            seen.add(new_id)
            refreshed.append((new_id, project_id))
    return refreshed or agents


def _claim_task_cards(ctx: click.Context, agent_id: str, project_id: str | None) -> list[dict]:
    """Claim pending task cards for this Machine without executing them.

    Failures are non-fatal: log a warning and retry on the next poll. Never
    delete the local registration from a failed claim — backends often return
    404 while the machine is merely offline, and pruning mid-poll empties the
    agent list so later passes never claim again.
    """
    headers = {"X-Project-Id": project_id} if project_id else None
    data = _client(ctx).post_nofatal(f"/agents/{agent_id}/tasks/claim", None, extra_headers=headers)
    status_code = data.get("_status_code", 200) if isinstance(data, dict) else 200
    if isinstance(data, dict) and (data.get("error") or status_code >= 400 or not data.get("success", True)):
        detail = data.get("error") or data.get("detail") or "unknown"
        click.echo(
            f"  [warn] could not claim task cards for agent {agent_id}: {detail}",
            err=True,
        )
        return []
    return list(data.get("tasks") or [])


@click.group("tasks")
def tasks_group() -> None:
    """Run task cards dispatched to this Machine (DV-1247).

    ``tasks run`` polls for pending task cards and executes each headless via
    ``claude -p "/deepvista <prompt>"``.
    """


def _iter_agent_files() -> list[tuple[str, str | None, Path]]:
    """Return (agent_id, project_id, path) for local Machine registrations, newest-first.

    Prefers ``MACHINES_DIR`` (fingerprint-keyed). Falls back to legacy
    ``AGENTS_DIR``. Deduplicates by agent_id.
    """
    seen: set[str] = set()
    candidates: list[tuple[float, Path]] = []
    for directory in (MACHINES_DIR, AGENTS_DIR):
        if not directory.exists():
            continue
        for path in directory.glob("*.json"):
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
    """Return this Machine's agent_id registered for ``project_id``."""
    return _load_machine_id(project_id)


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
    """Ensure this Machine is registered for each claim-scope project.

    Identity is ``(project_id, fingerprint)`` — registering for a second
    project creates (or reuses) that project's Machine row.

    Returns ``((agent_id, project_id), project_names)``.
    """
    try:
        detected, _ = detect_agent_tool()
    except Exception:
        detected = None
    agent_type = detected or "deepvista-cli"

    projects = _projects(ctx)
    project_names: dict[str, str] = {}
    scoped: list[tuple[str, str]] = []

    for project in projects:
        project_id = project.get("id")
        if not project_id:
            continue
        if project_ids is not None and project_id not in project_ids:
            continue
        project_name = project.get("name") or project.get("title") or ""
        project_names[project_id] = project_name
        scoped.append((project_id, project_name))

    if not scoped and project_ids:
        for pid in project_ids:
            project_names[pid] = ""
            scoped.append((pid, ""))

    result: list[tuple[str, str | None]] = []
    seen: set[str] = set()
    for project_id, project_name in scoped:
        agent_id = resolve_or_register_machine(
            ctx,
            project_id,
            agent_type=agent_type,
            project_name=project_name or None,
        )
        if not agent_id:
            continue
        key = f"{agent_id}:{project_id}"
        if key not in seen:
            seen.add(key)
            result.append((agent_id, project_id))

    return result, project_names


def _agent_type_label(agent_id: str) -> str:
    """Return last_seen_tool / agent_type from the local Machine cache."""
    for directory in (MACHINES_DIR, AGENTS_DIR):
        if not directory.exists():
            continue
        for path in directory.glob("*.json"):
            try:
                data = _json.loads(path.read_text())
                if data.get("agent_id") == agent_id:
                    return data.get("last_seen_tool") or data.get("agent_type", "")
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
    run_once: bool,
    poll_interval: int,
    total_time: int | None,
    max_parallel: int,
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
    click.echo(f"parallel : up to {max_parallel} concurrent headless run(s)")
    click.echo("")


class _TaskExecutor:
    """Bounded worker pool for concurrent headless task execution."""

    def __init__(self, max_workers: int) -> None:
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="deepvista-task")
        self._futures: list[Future[dict]] = []

    def submit(self, fn: Callable[[], dict]) -> None:
        self._futures.append(self._executor.submit(fn))

    def drain_completed(self) -> list[dict]:
        still_pending: list[Future[dict]] = []
        done: list[dict] = []
        for fut in self._futures:
            if fut.done():
                try:
                    done.append(fut.result())
                except Exception as exc:
                    done.append({"status": "failed", "error": str(exc)})
            else:
                still_pending.append(fut)
        self._futures = still_pending
        return done

    def wait_all(self) -> list[dict]:
        results: list[dict] = []
        for fut in self._futures:
            try:
                results.append(fut.result())
            except Exception as exc:
                results.append({"status": "failed", "error": str(exc)})
        self._futures = []
        return results

    @property
    def in_flight(self) -> int:
        return len(self._futures)

    def shutdown(self) -> None:
        self._executor.shutdown(wait=True, cancel_futures=False)


def _claim_and_submit_all(
    ctx: click.Context,
    agents: list[tuple[str, str | None]],
    executor: _TaskExecutor,
) -> int:
    """Claim pending task cards for all agents and submit runs to the executor."""
    submitted = 0
    for agent_id, project_id in agents:
        for task in _claim_task_cards(ctx, agent_id, project_id):
            executor.submit(
                lambda t=task, a=agent_id, p=project_id: _run_task_card(ctx, a, p, t),
            )
            submitted += 1
    return submitted


@tasks_group.command("run")
@click.option("--type", "agent_type", default=None, help="Resolve agent by type from local storage.")
@click.option(
    "--project",
    "project_id",
    default=None,
    help="Scope to this project (overrides the working project for this call only).",
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
@click.option(
    "--max-parallel",
    default=DEFAULT_MAX_PARALLEL_TASKS,
    show_default=True,
    type=click.IntRange(1, 20),
    help="Max concurrent headless task-card runs.",
)
@click.pass_context
def tasks_run(
    ctx: click.Context,
    agent_type: str | None,
    project_id: str | None,
    run_once: bool,
    poll_interval: int,
    total_time: int | None,
    verbose: bool,
    quiet: bool,
    max_parallel: int,
) -> None:
    """Poll for pending task cards and execute them headless (DV-1247).

    Scopes to the working project (``project use``, global ``--project``, or
    ``DEEPVISTA_PROJECT_ID``), falling back to your backend default project.
    Override per-invocation with ``--project``. Pass ``--type`` to resolve a
    specific local agent registration instead.

    Default mode polls in the foreground — claim, execute, sleep
    --poll-interval, repeat — until --total-time elapses (or forever when
    unset). --run-once does a single pass and exits; the cron entry installed
    by ``tasks setup`` uses it.

    Only one ``tasks run`` may be active per machine — concurrent
    invocations exit with an error instead of double-claiming work.
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
    agents: list[tuple[str, str | None]]
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

    _print_run_header(ctx, agents, project_names, run_once, poll_interval, total_time, max_parallel)

    poll_status: _PollStatus | None = None
    if not run_once:
        poll_status = _PollStatus(poll_interval, verbose=verbose, quiet=quiet)

    started = time.monotonic()
    polls = 0
    total_results: list[dict] = []
    executor = _TaskExecutor(max_workers=max_parallel)
    try:
        while True:
            polls += 1
            agents = _refresh_agents_for_poll(
                ctx,
                agents,
                project_names,
                agent_type=agent_type,
            )
            submitted = _claim_and_submit_all(ctx, agents, executor)

            results = executor.drain_completed()
            total_results.extend(results)
            if poll_status is not None:
                poll_status.record_results(results)

            has_work = bool(submitted or results)
            if has_work:
                failed = sum(1 for r in results if r.get("status") == "failed")
                detail = f"{submitted} task(s) claimed"
                if executor.in_flight:
                    detail += f" ({executor.in_flight} running)"
                if failed:
                    detail += f", {failed} finished failed"
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
            if emit_json and not run_once:
                agent_ids = agents[0][0] if len(agents) == 1 else [a[0] for a in agents]
                _output(
                    ctx,
                    {
                        "agent_id": agent_ids,
                        "tasks_run": len(results),
                        "tasks_in_flight": executor.in_flight,
                        "failed": sum(1 for r in results if r.get("status") == "failed"),
                        "results": results,
                    },
                    title="Tasks",
                )

            if poll_status is not None and results:
                poll_status.on_tasks_finished(results)

            if run_once:
                total_results.extend(executor.wait_all())
                agent_ids = agents[0][0] if len(agents) == 1 else [a[0] for a in agents]
                _output(
                    ctx,
                    {
                        "agent_id": agent_ids,
                        "tasks_run": len(total_results),
                        "failed": sum(1 for r in total_results if r.get("status") == "failed"),
                        "results": total_results,
                    },
                    title="Tasks",
                )
                return
            if total_time is not None and (time.monotonic() - started) + poll_interval > total_time:
                if poll_status is not None:
                    poll_status.on_shutdown(polls)
                total_results.extend(executor.wait_all())
                agent_ids = agents[0][0] if len(agents) == 1 else [a[0] for a in agents]
                _output(
                    ctx,
                    {
                        "agent_id": agent_ids,
                        "polls": polls,
                        "tasks_run": len(total_results),
                        "failed": sum(1 for r in total_results if r.get("status") == "failed"),
                    },
                    title="Tasks (polling finished)",
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
        executor.shutdown()
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
    working = _resolve_working_project(ctx, project_id)
    agent_id, resolved_project_id = _require_machine_agent_id(agent_type, working)
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
    """Best-effort last-activity timestamp for a task card (DV-1429)."""
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
    """Delete terminated task cards for this Machine (DV-1429).

    With explicit TASK_IDS, deletes exactly those. Otherwise deletes task cards
    in a terminal state (default: completed + failed), optionally limited to those
    last updated more than --older-than days ago. Inspect first with
    ``deepvista tasks list``; preview with --dry-run.

    > [!CAUTION] Destructive — deleted tasks cannot be recovered. Confirm with the user.
    """
    working = _resolve_working_project(ctx, project_id)
    agent_id, resolved_project_id = _require_machine_agent_id(agent_type, working)
    headers = {"X-Project-Id": resolved_project_id} if resolved_project_id else None
    client = _client(ctx)

    if task_ids:
        target_ids = list(dict.fromkeys(task_ids))  # dedupe, preserve order
    else:
        wanted = {s.lower() for s in statuses} or {"completed", "failed"}
        data = client.get(f"/agents/{agent_id}/tasks", extra_headers=headers)
        if isinstance(data, dict) and data.get("error"):
            output_error(1, "Failed to list tasks", data["error"])
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
            resp = client.delete(f"/agents/{agent_id}/tasks/{tid}")
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
    working = _resolve_working_project(ctx, project_id)
    agent_id, resolved_project_id = _require_machine_agent_id(agent_type, working)
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

    Each cron tick runs the same headless task-card execution as a foreground
    `tasks run` poll (one pass per tick via ``--run-once``).

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
        _output(ctx, {"removed": False, "message": "No tasks cron entry installed."}, title="Tasks Setup")
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
