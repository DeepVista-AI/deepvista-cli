"""Click-level tests for `deepvista tasks run` / `list` / `complete` / `setup` (DV-936/DV-955/DV-1079)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

from deepvista_cli.commands.tasks import (
    CRON_MARKER,
    _cron_entry,
    _is_workflow_task,
    _parse_workflow_command,
    _validate_command,
)
from deepvista_cli.main import cli

WORKFLOW_COMMAND = (
    "deepvista skill run --mode host 00000000-0000-0000-0000-000000000001 "
    '--input \'{"name": "Ada"}\' --webhook --best-effort'
)


class _StubCtxClient:
    """Minimal stand-in for the real client attached to ctx.obj._client."""

    def __init__(self) -> None:
        self.responses: dict[str, list[Any]] = {}
        self.calls: list[tuple[str, str, dict | None]] = []

    def queue(self, path: str, response: Any) -> None:
        self.responses.setdefault(path, []).append(response)

    def _pop(self, method: str, path: str, body: dict | None = None) -> Any:
        self.calls.append((method, path, body))
        q = self.responses.get(path)
        if not q:
            # DV-1247 task-card endpoints are claimed on every poll pass; tests
            # that don't exercise task cards get an empty default so the legacy
            # task-queue assertions stay focused.
            if "/tasks/claim" in path:
                return {"success": True, "tasks": []}
            if path.endswith("/tasks") or "/tasks/" in path:
                return {"success": True, "tasks": []}
            raise AssertionError(f"no response queued for {method} {path}")
        return q.pop(0)

    def post(self, path: str, body: dict | None = None) -> Any:
        return self._pop("POST", path, body)

    def get(self, path: str, params: dict | None = None) -> Any:
        return self._pop("GET", path, params)


@pytest.fixture()
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect CLI state dirs into a pytest tmp dir."""
    monkeypatch.setenv("DEEPVISTA_CONFIG_DIR", str(tmp_path / ".config" / "deepvista"))
    import importlib

    import deepvista_cli.config as cfg_module

    importlib.reload(cfg_module)
    return tmp_path


def _install_stub_client(monkeypatch: pytest.MonkeyPatch, stub: _StubCtxClient) -> None:
    """Swap the real DeepVistaClient for our stub on the CLI context."""

    def fake_init(self, config):  # type: ignore[no-untyped-def]
        self.config = config

    from deepvista_cli.client import http as http_module

    monkeypatch.setattr(http_module.DeepVistaClient, "__init__", fake_init)
    monkeypatch.setattr(
        http_module.DeepVistaClient,
        "post",
        lambda self, path, body=None, extra_headers=None: stub.post(path, body),
    )
    monkeypatch.setattr(
        http_module.DeepVistaClient,
        "post_nofatal",
        lambda self, path, body=None, extra_headers=None: stub.post(path, body),
    )
    monkeypatch.setattr(
        http_module.DeepVistaClient,
        "get",
        lambda self, path, params=None, extra_headers=None: stub.get(path, params),
    )


DEFAULT_PROJECT_ID = "proj-default"


def _stub_working_project(stub: _StubCtxClient, project_id: str = DEFAULT_PROJECT_ID) -> None:
    """Queue API responses so ``tasks run`` resolves a working project."""
    stub.queue("/projects/me", {"id": project_id, "name": "Default project"})
    stub.queue("/projects", [{"id": project_id, "name": "Default project"}])


def _register_local_agent(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    agent_id: str = "agent-uuid-1",
    project_id: str = DEFAULT_PROJECT_ID,
) -> None:
    """Write a local agent registration file and point the command module at it."""
    agents_dir = tmp_path / ".config" / "deepvista" / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    suffix = f"__{project_id}" if project_id else ""
    (agents_dir / f"deepvista-cli__misc{suffix}.json").write_text(
        json.dumps(
            {
                "agent_id": agent_id,
                "agent_type": "deepvista-cli",
                "agent_role": "misc",
                "project_id": project_id,
            }
        )
    )
    import deepvista_cli.commands.agents as agents_module
    import deepvista_cli.commands.tasks as tq_module

    monkeypatch.setattr(agents_module, "AGENTS_DIR", agents_dir)
    monkeypatch.setattr(tq_module, "AGENTS_DIR", agents_dir)
    # Keep the run lock inside the pytest tmp dir, away from ~/.config.
    monkeypatch.setattr(tq_module, "RUN_LOCK_PATH", tmp_path / ".config" / "deepvista" / "task_queue.run.lock")


class _FakeClock:
    """Deterministic stand-in for the `time` module inside the poll loop."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[int] = []

    def monotonic(self) -> float:
        return self.now

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: int) -> None:
        self.sleeps.append(seconds)
        self.now += seconds

    def strftime(self, fmt: str, t: object = None) -> str:  # type: ignore[override]
        return "00:00:00"

    def localtime(self, secs: float | None = None) -> object:
        import time as _time

        return _time.localtime(0)


def _install_fake_clock(monkeypatch: pytest.MonkeyPatch) -> _FakeClock:
    import deepvista_cli.commands.tasks as tq_module

    clock = _FakeClock()
    monkeypatch.setattr(tq_module, "time", clock)
    return clock


def _parse_json_objects(output: str) -> list[dict]:
    """Parse a stream of (pretty-printed) JSON objects, skipping non-JSON lines.

    Non-JSON text (e.g. the startup banner printed by `tasks run`) is
    silently skipped by advancing to the next ``{`` character before each
    decode attempt.
    """
    decoder = json.JSONDecoder()
    text = output.strip()
    objs: list[dict] = []
    idx = 0
    while idx < len(text):
        brace = text.find("{", idx)
        if brace == -1:
            break
        try:
            obj, end = decoder.raw_decode(text, brace)
            objs.append(obj)
            idx = end
            while idx < len(text) and text[idx].isspace():
                idx += 1
        except json.JSONDecodeError:
            idx = brace + 1
    return objs


def _parse_first_json(output: str) -> dict:
    """Return the first JSON object from output (banner lines are ignored)."""
    objs = _parse_json_objects(output)
    assert objs, f"No JSON object found in output:\n{output}"
    return objs[0]


# ---------------------------------------------------------------------------
# command validation
# ---------------------------------------------------------------------------


def test_validate_command_allows_only_deepvista():
    assert _validate_command("deepvista notes list") is None
    assert _validate_command("rm -rf /") is not None
    assert _validate_command("") is not None
    assert _validate_command('deepvista "unterminated') is not None


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------


def test_run_once_exits_immediately_when_queue_empty(
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub = _StubCtxClient()
    _stub_working_project(stub)
    stub.queue("/agents/agent-uuid-1/task-queue/claim", {"success": True, "tasks": []})
    _install_stub_client(monkeypatch, stub)
    _register_local_agent(monkeypatch, isolated_home)

    result = CliRunner().invoke(cli, ["tasks", "run", "--run-once"])
    assert result.exit_code == 0, result.output
    payload = _parse_first_json(result.output)
    assert payload["tasks_run"] == 0
    non_setup_calls = [c[1] for c in stub.calls if c[1] not in {"/projects", "/projects/me"} and "/tasks" not in c[1]]
    assert non_setup_calls == ["/agents/agent-uuid-1/task-queue/claim"]


def test_run_executes_claimed_task_and_reports_result(
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub = _StubCtxClient()
    _stub_working_project(stub)
    stub.queue(
        "/agents/agent-uuid-1/task-queue/claim",
        {"success": True, "tasks": [{"id": "t-1", "command": "deepvista notes list", "status": "running"}]},
    )
    stub.queue("/agents/agent-uuid-1/task-queue/t-1/result", {"success": True})
    _install_stub_client(monkeypatch, stub)
    _register_local_agent(monkeypatch, isolated_home)

    import deepvista_cli.commands.tasks as tq_module

    class _FakeProc:
        returncode = 0
        stdout = "ok"
        stderr = ""

    executed: list[list[str]] = []

    def fake_run(argv, **kwargs):  # type: ignore[no-untyped-def]
        executed.append(argv)
        return _FakeProc()

    monkeypatch.setattr(tq_module.subprocess, "run", fake_run)

    result = CliRunner().invoke(cli, ["tasks", "run", "--run-once"])
    assert result.exit_code == 0, result.output
    payload = _parse_first_json(result.output)
    assert payload["tasks_run"] == 1
    assert payload["failed"] == 0
    assert payload["results"][0]["status"] == "completed"

    # Executed argv keeps the CLI args, binary resolved to an absolute path or name.
    assert executed[0][1:] == ["notes", "list"]

    # Result was reported to the backend.
    method, path, body = stub.calls[-1]
    assert (method, path) == ("POST", "/agents/agent-uuid-1/task-queue/t-1/result")
    assert body == {"status": "completed", "exit_code": 0, "output_tail": "ok"}


def test_run_executes_task_card_via_claude_and_reports_output(
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DV-1247: a claimed task card runs `claude -p "/deepvista <prompt>"`; stdout
    is reported as the output and the run completes."""
    stub = _StubCtxClient()
    _stub_working_project(stub)
    stub.queue(
        "/agents/agent-uuid-1/tasks/claim",
        {"success": True, "tasks": [{"id": "tc-1", "prompt": "reply hello world", "title": "Say hello"}]},
    )
    stub.queue("/agents/agent-uuid-1/task-queue/claim", {"success": True, "tasks": []})
    stub.queue("/agents/agent-uuid-1/tasks/tc-1/result", {"success": True, "output_card_id": "out-1"})
    _install_stub_client(monkeypatch, stub)
    _register_local_agent(monkeypatch, isolated_home)

    import deepvista_cli.commands.tasks as tq_module

    class _FakeProc:
        returncode = 0
        stdout = "Hello, world!"
        stderr = ""

    executed: list[list[str]] = []

    def fake_run(argv, **kwargs):  # type: ignore[no-untyped-def]
        executed.append(argv)
        return _FakeProc()

    monkeypatch.setattr(tq_module.subprocess, "run", fake_run)

    result = CliRunner().invoke(cli, ["tasks", "run", "--run-once"])
    assert result.exit_code == 0, result.output

    # Claude was invoked headless with the /deepvista-prefixed prompt.
    assert executed, "claude was not launched"
    argv = executed[0]
    assert argv[1] == "-p"
    assert argv[2] == "/deepvista reply hello world"
    assert "--permission-mode" in argv

    # The result (with captured stdout) was reported to the task-card endpoint.
    result_calls = [c for c in stub.calls if c[1] == "/agents/agent-uuid-1/tasks/tc-1/result"]
    assert result_calls, "no result reported"
    _, _, body = result_calls[-1]
    assert body["status"] == "completed"
    assert body["exit_code"] == 0
    assert body["output"] == "Hello, world!"


def test_run_rejects_non_deepvista_command_without_executing(
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub = _StubCtxClient()
    _stub_working_project(stub)
    stub.queue(
        "/agents/agent-uuid-1/task-queue/claim",
        {"success": True, "tasks": [{"id": "t-1", "command": "rm -rf /", "status": "running"}]},
    )
    stub.queue("/agents/agent-uuid-1/task-queue/t-1/result", {"success": True})
    _install_stub_client(monkeypatch, stub)
    _register_local_agent(monkeypatch, isolated_home)

    import deepvista_cli.commands.tasks as tq_module

    def explode(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("subprocess.run must not be called for disallowed commands")

    monkeypatch.setattr(tq_module.subprocess, "run", explode)

    result = CliRunner().invoke(cli, ["tasks", "run", "--run-once"])
    assert result.exit_code == 0, result.output
    payload = _parse_first_json(result.output)
    assert payload["failed"] == 1
    assert payload["results"][0]["status"] == "failed"

    method, path, body = stub.calls[-1]
    assert (method, path) == ("POST", "/agents/agent-uuid-1/task-queue/t-1/result")
    assert body is not None and body["status"] == "failed"


def test_run_errors_when_no_agent_registered(
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub = _StubCtxClient()
    _stub_working_project(stub)
    stub.queue("/agents", {"error": "registration unavailable"})
    _install_stub_client(monkeypatch, stub)
    import deepvista_cli.commands.agents as agents_module
    import deepvista_cli.commands.tasks as tq_module

    empty = isolated_home / ".config" / "deepvista" / "agents"
    monkeypatch.setattr(agents_module, "AGENTS_DIR", empty)
    monkeypatch.setattr(tq_module, "AGENTS_DIR", empty)
    monkeypatch.setattr(tq_module, "RUN_LOCK_PATH", isolated_home / ".config" / "deepvista" / "task_queue.run.lock")

    result = CliRunner().invoke(cli, ["tasks", "run"])
    assert result.exit_code == 3


# ---------------------------------------------------------------------------
# workflow tasks (DV-955)
# ---------------------------------------------------------------------------


def test_is_workflow_task_by_source_and_command_shape():
    assert _is_workflow_task({"source": "webhook", "command": "deepvista notes list"})
    assert _is_workflow_task({"command": WORKFLOW_COMMAND})
    assert not _is_workflow_task({"command": "deepvista notes list"})
    assert not _is_workflow_task({"command": "deepvista skill run abc"})  # no --webhook


def test_parse_workflow_command_extracts_fields():
    parsed = _parse_workflow_command(WORKFLOW_COMMAND)
    assert parsed == {
        "skill_id": "00000000-0000-0000-0000-000000000001",
        "user_input": '{"name": "Ada"}',
        "best_effort": True,
    }
    assert _parse_workflow_command("deepvista notes list") is None
    assert _parse_workflow_command("deepvista skill run --webhook") is None  # no skill id


def test_run_headless_claims_command_only(
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub = _StubCtxClient()
    _stub_working_project(stub)
    stub.queue("/agents/agent-uuid-1/task-queue/claim", {"success": True, "tasks": []})
    _install_stub_client(monkeypatch, stub)
    _register_local_agent(monkeypatch, isolated_home)

    import deepvista_cli.commands.tasks as tq_module

    monkeypatch.setattr(tq_module, "_detect_host_agent", lambda: False)

    result = CliRunner().invoke(cli, ["tasks", "run", "--run-once"])
    assert result.exit_code == 0, result.output
    claim_calls = [(m, p, b) for m, p, b in stub.calls if p == "/agents/agent-uuid-1/task-queue/claim"]
    assert len(claim_calls) == 1
    method, path, body = claim_calls[0]
    assert (method, path) == ("POST", "/agents/agent-uuid-1/task-queue/claim")
    # Headless cron ticks must leave workflow tasks pending for a host run.
    assert body == {"command_only": True}


def test_run_host_emits_workflow_packet_and_leaves_task_running(
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub = _StubCtxClient()
    _stub_working_project(stub)
    stub.queue(
        "/agents/agent-uuid-1/task-queue/claim",
        {
            "success": True,
            "tasks": [{"id": "t-wf", "command": WORKFLOW_COMMAND, "status": "running", "source": "webhook"}],
        },
    )
    _install_stub_client(monkeypatch, stub)
    _register_local_agent(monkeypatch, isolated_home)

    import deepvista_cli.commands.tasks as tq_module

    emitted: list[dict] = []

    def fake_emit(ctx, skill_id, user_input, mode="host", **kwargs):  # type: ignore[no-untyped-def]
        emitted.append({"skill_id": skill_id, "user_input": user_input, **kwargs})

    monkeypatch.setattr(tq_module, "emit_host_run_packet", fake_emit)

    def explode(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("workflow tasks must not be subprocess-executed")

    monkeypatch.setattr(tq_module.subprocess, "run", explode)

    result = CliRunner().invoke(cli, ["tasks", "run", "--host"])
    assert result.exit_code == 0, result.output

    # Claim body None (full claim), packet emitted with task threading.
    assert stub.calls[0][2] is None
    assert emitted == [
        {
            "skill_id": "00000000-0000-0000-0000-000000000001",
            "user_input": '{"name": "Ada"}',
            "webhook": True,
            "best_effort": True,
            "task_id": "t-wf",
        }
    ]
    assert "=== DEEPVISTA WORKFLOW TASK t-wf" in result.output

    # No result report: the task stays `running` until `tasks complete`.
    assert all("/result" not in c[1] for c in stub.calls)


def test_run_host_fails_unparseable_workflow_task(
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub = _StubCtxClient()
    _stub_working_project(stub)
    stub.queue(
        "/agents/agent-uuid-1/task-queue/claim",
        {
            "success": True,
            # source says webhook but the command isn't a skill run — nobody
            # could ever drive this; it must be failed, not left running.
            "tasks": [{"id": "t-bad", "command": "deepvista notes list", "status": "running", "source": "webhook"}],
        },
    )
    stub.queue("/agents/agent-uuid-1/task-queue/t-bad/result", {"success": True})
    _install_stub_client(monkeypatch, stub)
    _register_local_agent(monkeypatch, isolated_home)

    result = CliRunner().invoke(cli, ["tasks", "run", "--host"])
    assert result.exit_code == 0, result.output

    method, path, body = stub.calls[-1]
    assert (method, path) == ("POST", "/agents/agent-uuid-1/task-queue/t-bad/result")
    assert body is not None and body["status"] == "failed"


def test_run_headless_ignores_workflow_tasks_that_slip_through(
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub = _StubCtxClient()
    _stub_working_project(stub)
    stub.queue(
        "/agents/agent-uuid-1/task-queue/claim",
        {
            "success": True,
            "tasks": [{"id": "t-wf", "command": WORKFLOW_COMMAND, "status": "running", "source": "webhook"}],
        },
    )
    _install_stub_client(monkeypatch, stub)
    _register_local_agent(monkeypatch, isolated_home)

    import deepvista_cli.commands.tasks as tq_module

    monkeypatch.setattr(tq_module, "_detect_host_agent", lambda: False)

    def explode(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("workflow tasks must not be subprocess-executed")

    monkeypatch.setattr(tq_module.subprocess, "run", explode)

    result = CliRunner().invoke(cli, ["tasks", "run", "--run-once"])
    assert result.exit_code == 0, result.output
    # No packet for a cron log, no subprocess, no terminal report.
    assert "DEEPVISTA WORKFLOW TASK" not in result.output
    assert all("/result" not in c[1] for c in stub.calls)


# ---------------------------------------------------------------------------
# polling + single-instance lock (DV-1079)
# ---------------------------------------------------------------------------


def test_run_polls_until_total_time(
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub = _StubCtxClient()
    _stub_working_project(stub)
    for _ in range(3):
        stub.queue("/agents/agent-uuid-1/task-queue/claim", {"success": True, "tasks": []})
    _install_stub_client(monkeypatch, stub)
    _register_local_agent(monkeypatch, isolated_home)
    clock = _install_fake_clock(monkeypatch)

    result = CliRunner().invoke(cli, ["tasks", "run", "--poll-interval", "10", "--total-time", "25"])
    assert result.exit_code == 0, result.output

    # Passes at t=0, 10, 20; a fourth pass would start past the 25s budget.
    claim_calls = [c[1] for c in stub.calls if c[1] not in {"/projects", "/projects/me"} and "/tasks" not in c[1]]
    assert claim_calls == ["/agents/agent-uuid-1/task-queue/claim"] * 3
    assert clock.sleeps == [10, 10]

    # Empty passes are quiet; only the final summary is printed.
    payload = _parse_first_json(result.output)
    assert payload == {"agent_id": "agent-uuid-1", "polls": 3, "tasks_run": 0, "failed": 0}


def test_run_polling_executes_tasks_across_passes(
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub = _StubCtxClient()
    _stub_working_project(stub)
    stub.queue(
        "/agents/agent-uuid-1/task-queue/claim",
        {"success": True, "tasks": [{"id": "t-1", "command": "deepvista notes list", "status": "running"}]},
    )
    stub.queue("/agents/agent-uuid-1/task-queue/claim", {"success": True, "tasks": []})
    stub.queue("/agents/agent-uuid-1/task-queue/t-1/result", {"success": True})
    _install_stub_client(monkeypatch, stub)
    _register_local_agent(monkeypatch, isolated_home)
    _install_fake_clock(monkeypatch)

    import deepvista_cli.commands.tasks as tq_module

    class _FakeProc:
        returncode = 0
        stdout = "ok"
        stderr = ""

    monkeypatch.setattr(tq_module.subprocess, "run", lambda argv, **kwargs: _FakeProc())

    result = CliRunner().invoke(cli, ["tasks", "run", "--poll-interval", "30", "--total-time", "45"])
    assert result.exit_code == 0, result.output

    # Pass 1 ran the task (and printed it); pass 2 was empty; summary totals 1.
    payloads = _parse_json_objects(result.output)
    assert payloads[0]["tasks_run"] == 1
    assert payloads[-1] == {"agent_id": "agent-uuid-1", "polls": 2, "tasks_run": 1, "failed": 0}


def test_run_host_polling_hands_back_after_workflow_packet(
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub = _StubCtxClient()
    _stub_working_project(stub)
    stub.queue(
        "/agents/agent-uuid-1/task-queue/claim",
        {
            "success": True,
            "tasks": [{"id": "t-wf", "command": WORKFLOW_COMMAND, "status": "running", "source": "webhook"}],
        },
    )
    _install_stub_client(monkeypatch, stub)
    _register_local_agent(monkeypatch, isolated_home)
    clock = _install_fake_clock(monkeypatch)

    import deepvista_cli.commands.tasks as tq_module

    monkeypatch.setattr(tq_module, "emit_host_run_packet", lambda *args, **kwargs: None)

    # No --run-once: the loop must still exit so the host agent can drive
    # the packet instead of sitting behind a blocked foreground poll.
    result = CliRunner().invoke(cli, ["tasks", "run", "--host"])
    assert result.exit_code == 0, result.output
    assert [c[1] for c in stub.calls if c[1] not in {"/projects", "/projects/me"} and "/tasks" not in c[1]] == [
        "/agents/agent-uuid-1/task-queue/claim"
    ]
    assert clock.sleeps == []


def test_run_refuses_when_another_run_holds_the_lock(
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub = _StubCtxClient()
    _install_stub_client(monkeypatch, stub)
    _register_local_agent(monkeypatch, isolated_home)

    import deepvista_cli.commands.tasks as tq_module

    # PID 1 (launchd/init) is always alive and never this process.
    tq_module.RUN_LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    tq_module.RUN_LOCK_PATH.write_text("1")

    result = CliRunner().invoke(cli, ["tasks", "run", "--run-once"])
    assert result.exit_code == 2
    # No claim — the queue must not be touched by a second instance.
    assert stub.calls == []
    # The foreign lock is left in place.
    assert tq_module.RUN_LOCK_PATH.read_text() == "1"


def test_run_reclaims_stale_lock_and_releases_on_exit(
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub = _StubCtxClient()
    _stub_working_project(stub)
    stub.queue("/agents/agent-uuid-1/task-queue/claim", {"success": True, "tasks": []})
    _install_stub_client(monkeypatch, stub)
    _register_local_agent(monkeypatch, isolated_home)

    import deepvista_cli.commands.tasks as tq_module

    tq_module.RUN_LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    tq_module.RUN_LOCK_PATH.write_text("99999999")
    monkeypatch.setattr(tq_module, "_pid_alive", lambda pid: False)

    result = CliRunner().invoke(cli, ["tasks", "run", "--run-once"])
    assert result.exit_code == 0, result.output
    assert [c[1] for c in stub.calls if c[1] not in {"/projects", "/projects/me"} and "/tasks" not in c[1]] == [
        "/agents/agent-uuid-1/task-queue/claim"
    ]
    # Lock was reclaimed for the run and removed afterwards.
    assert not tq_module.RUN_LOCK_PATH.exists()


# ---------------------------------------------------------------------------
# complete
# ---------------------------------------------------------------------------


def test_complete_reports_terminal_status(
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub = _StubCtxClient()
    stub.queue(
        "/agents/agent-uuid-1/task-queue/t-wf/result",
        {"success": True, "task": {"id": "t-wf", "status": "completed"}},
    )
    _install_stub_client(monkeypatch, stub)
    _register_local_agent(monkeypatch, isolated_home)

    result = CliRunner().invoke(
        cli,
        ["tasks", "complete", "t-wf", "--status", "completed", "--note", "lead brief shipped"],
    )
    assert result.exit_code == 0, result.output

    method, path, body = stub.calls[-1]
    assert (method, path) == ("POST", "/agents/agent-uuid-1/task-queue/t-wf/result")
    assert body == {"status": "completed", "exit_code": 0, "output_tail": "lead brief shipped"}


def test_complete_rejects_unknown_status(
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub = _StubCtxClient()
    _install_stub_client(monkeypatch, stub)
    _register_local_agent(monkeypatch, isolated_home)

    result = CliRunner().invoke(cli, ["tasks", "complete", "t-wf", "--status", "running"])
    assert result.exit_code != 0
    assert stub.calls == []


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


def test_list_shows_queue(
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub = _StubCtxClient()
    # DV-1247: `tasks list` now lists task cards (GET /agents/{id}/tasks).
    stub.queue(
        "/agents/agent-uuid-1/tasks",
        {"success": True, "tasks": [{"id": "t-1", "title": "Say hello", "status": "pending"}]},
    )
    _install_stub_client(monkeypatch, stub)
    _register_local_agent(monkeypatch, isolated_home)

    result = CliRunner().invoke(cli, ["tasks", "list"])
    assert result.exit_code == 0, result.output
    payload = _parse_first_json(result.output)
    assert payload["count"] == 1
    assert payload["tasks"][0]["id"] == "t-1"


# ---------------------------------------------------------------------------
# setup
# ---------------------------------------------------------------------------


def test_setup_dry_run_previews_cron_entry(
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub = _StubCtxClient()
    _install_stub_client(monkeypatch, stub)

    import deepvista_cli.commands.tasks as tq_module

    monkeypatch.setattr(tq_module, "_read_crontab", lambda: ["0 0 * * * /bin/true"])

    def explode(lines):  # type: ignore[no-untyped-def]
        raise AssertionError("crontab must not be written in dry-run")

    monkeypatch.setattr(tq_module, "_write_crontab", explode)

    result = CliRunner().invoke(cli, ["--dry-run", "tasks", "setup", "--interval", "10"])
    assert result.exit_code == 0, result.output
    payload = _parse_first_json(result.output)
    assert payload["dry_run"] is True
    assert "*/10 * * * *" in payload["entry"]
    assert CRON_MARKER in payload["entry"]


def test_setup_installs_and_replaces_entry_idempotently(
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub = _StubCtxClient()
    _install_stub_client(monkeypatch, stub)

    import deepvista_cli.commands.tasks as tq_module

    written: list[list[str]] = []
    monkeypatch.setattr(
        tq_module,
        "_read_crontab",
        lambda: ["0 0 * * * /bin/true", f"*/5 * * * * /old/deepvista task_queue run {CRON_MARKER}"],
    )
    monkeypatch.setattr(tq_module, "_write_crontab", lambda lines: written.append(lines) or True)

    result = CliRunner().invoke(cli, ["tasks", "setup", "--interval", "15"])
    assert result.exit_code == 0, result.output
    payload = _parse_first_json(result.output)
    assert payload["installed"] is True
    assert payload["interval_minutes"] == 15

    lines = written[0]
    # Unrelated entry preserved, old marker entry replaced, exactly one marker line.
    assert lines[0] == "0 0 * * * /bin/true"
    marker_lines = [line for line in lines if CRON_MARKER in line]
    assert len(marker_lines) == 1
    assert "*/15 * * * *" in marker_lines[0]


def test_setup_remove_uninstalls_entry(
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub = _StubCtxClient()
    _install_stub_client(monkeypatch, stub)

    import deepvista_cli.commands.tasks as tq_module

    written: list[list[str]] = []
    monkeypatch.setattr(
        tq_module,
        "_read_crontab",
        lambda: ["0 0 * * * /bin/true", f"*/5 * * * * /usr/local/bin/deepvista task_queue run {CRON_MARKER}"],
    )
    monkeypatch.setattr(tq_module, "_write_crontab", lambda lines: written.append(lines) or True)

    result = CliRunner().invoke(cli, ["tasks", "setup", "--remove"])
    assert result.exit_code == 0, result.output
    payload = _parse_first_json(result.output)
    assert payload["removed"] is True
    assert written[0] == ["0 0 * * * /bin/true"]


def test_cron_entry_includes_profile_flag():
    entry = _cron_entry(5, "staging")
    assert "--profile staging" in entry
    assert _cron_entry(5, "default").find("--profile") == -1


def test_cron_entry_runs_once_per_tick():
    # Cron provides the schedule; each tick must be a single pass, not a
    # second long-lived poller fighting the foreground one for the lock.
    assert "tasks run --run-once" in _cron_entry(5, "default")


# ---------------------------------------------------------------------------
# multi-agent / all-projects polling
# ---------------------------------------------------------------------------


def _register_two_agents(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Write two agent registration files (different projects) and redirect state dirs."""
    agents_dir = tmp_path / ".config" / "deepvista" / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    (agents_dir / "claude-code__misc__proj-1.json").write_text(
        json.dumps(
            {"agent_id": "agent-proj-1", "agent_type": "claude-code", "agent_role": "misc", "project_id": "proj-1"}
        )
    )
    (agents_dir / "claude-code__misc__proj-2.json").write_text(
        json.dumps(
            {"agent_id": "agent-proj-2", "agent_type": "claude-code", "agent_role": "misc", "project_id": "proj-2"}
        )
    )
    import deepvista_cli.commands.agents as agents_module
    import deepvista_cli.commands.tasks as tq_module

    monkeypatch.setattr(agents_module, "AGENTS_DIR", agents_dir)
    monkeypatch.setattr(tq_module, "AGENTS_DIR", agents_dir)
    monkeypatch.setattr(tq_module, "RUN_LOCK_PATH", tmp_path / ".config" / "deepvista" / "task_queue.run.lock")


def test_run_once_polls_only_current_project_agent(
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``tasks run`` scopes to the working project — only that agent's queue is claimed."""
    stub = _StubCtxClient()
    stub.queue("/projects/me", {"id": "proj-1", "name": "Project 1"})
    stub.queue("/projects", [{"id": "proj-1", "name": "Project 1"}, {"id": "proj-2", "name": "Project 2"}])
    stub.queue("/agents/agent-proj-1/task-queue/claim", {"success": True, "tasks": []})
    _install_stub_client(monkeypatch, stub)
    _register_two_agents(monkeypatch, isolated_home)

    result = CliRunner().invoke(cli, ["tasks", "run", "--run-once", "--project", "proj-1"])
    assert result.exit_code == 0, result.output

    claimed_paths = {c[1] for c in stub.calls}
    assert "/agents/agent-proj-1/task-queue/claim" in claimed_paths
    assert "/agents/agent-proj-2/task-queue/claim" not in claimed_paths


def test_ensure_agents_for_all_projects_registers_missing_and_reuses_existing(
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Auto-registers for new projects and reuses existing local registrations."""
    stub = _StubCtxClient()
    stub.queue("/projects", [{"id": "proj-a"}, {"id": "proj-b"}])
    stub.queue(
        "/agents",
        {"agent": {"id": "new-agent-b", "agent_type": "deepvista-cli", "agent_role": "misc"}},
    )
    # Initial sync posted after registration (mirrors `agents register` flow).
    stub.queue("/agents/new-agent-b/sync", {"success": True, "agent": {"id": "new-agent-b"}})
    _install_stub_client(monkeypatch, stub)

    agents_dir = isolated_home / ".config" / "deepvista" / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    # proj-a already has a local registration.
    (agents_dir / "deepvista-cli__misc__proj-a.json").write_text(
        json.dumps(
            {
                "agent_id": "existing-agent-a",
                "agent_type": "deepvista-cli",
                "agent_role": "misc",
                "project_id": "proj-a",
            }
        )
    )

    import deepvista_cli.commands.agents as agents_module
    import deepvista_cli.commands.tasks as tq_module

    monkeypatch.setattr(agents_module, "AGENTS_DIR", agents_dir)
    monkeypatch.setattr(tq_module, "AGENTS_DIR", agents_dir)
    # Patch detect_agent_tool in task_queue's namespace (it's imported directly).
    monkeypatch.setattr(tq_module, "detect_agent_tool", lambda: ("deepvista-cli", {}))

    import click
    from click.testing import CliRunner as _CliRunner

    from deepvista_cli.main import cli as _cli

    captured: list = []

    @_cli.command("_test_ensure")
    @click.pass_context
    def _test_cmd(ctx):  # type: ignore[no-untyped-def]
        agents, _ = tq_module._ensure_agents_for_all_projects(ctx)
        captured.extend(agents)

    result = _CliRunner().invoke(_cli, ["_test_ensure"])
    assert result.exit_code == 0, result.output

    agent_ids = [a[0] for a in captured]
    assert "existing-agent-a" in agent_ids
    assert "new-agent-b" in agent_ids

    # Verify the new registration was saved locally.
    saved = json.loads((agents_dir / "deepvista-cli__misc__proj-b.json").read_text())
    assert saved["agent_id"] == "new-agent-b"
    assert saved["project_id"] == "proj-b"

    # The POST for proj-b must have used the /agents endpoint (X-Project-Id goes in header, not path).
    post_calls = [c for c in stub.calls if c[0] == "POST" and c[1] == "/agents"]
    assert len(post_calls) == 1


def test_run_type_filter_restricts_to_single_agent(
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """--type restricts polling to that agent only (backward-compat single-agent mode)."""
    stub = _StubCtxClient()
    stub.queue("/agents/agent-proj-1/task-queue/claim", {"success": True, "tasks": []})
    _install_stub_client(monkeypatch, stub)
    _register_two_agents(monkeypatch, isolated_home)

    result = CliRunner().invoke(cli, ["tasks", "run", "--run-once", "--type", "claude-code", "--project", "proj-1"])
    assert result.exit_code == 0, result.output

    claimed_paths = [c[1] for c in stub.calls if "/tasks" not in c[1]]
    assert claimed_paths == ["/agents/agent-proj-1/task-queue/claim"]


def test_run_scoped_to_project_skips_other_agents_on_claim_failure(
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A claim failure on another project's agent is never attempted when scoped."""
    stub = _StubCtxClient()
    stub.queue("/projects/me", {"id": "proj-2", "name": "Project 2"})
    stub.queue("/projects", [{"id": "proj-1", "name": "Project 1"}, {"id": "proj-2", "name": "Project 2"}])
    stub.queue("/agents/agent-proj-2/task-queue/claim", {"success": True, "tasks": []})
    _install_stub_client(monkeypatch, stub)
    _register_two_agents(monkeypatch, isolated_home)

    result = CliRunner().invoke(cli, ["tasks", "run", "--run-once", "--project", "proj-2"])
    assert result.exit_code == 0, result.output
    claimed_paths = {c[1] for c in stub.calls}
    assert "/agents/agent-proj-2/task-queue/claim" in claimed_paths
    assert "/agents/agent-proj-1/task-queue/claim" not in claimed_paths
