"""Click-level tests for `deepvista tasks run` / `list` / `clean` / `setup` (DV-1247/DV-1079)."""

from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

from deepvista_cli.commands.tasks import (
    CRON_MARKER,
    _cron_entry,
    _summarize_stream_event,
    _summarize_tool_input,
)
from deepvista_cli.main import cli


class _StubCtxClient:
    """Minimal stand-in for the real client attached to ctx.obj._client."""

    def __init__(self) -> None:
        self.responses: dict[str, list[Any]] = {}
        self.sticky: dict[str, Any] = {}
        self.calls: list[tuple[str, str, dict | None]] = []

    def queue(self, path: str, response: Any) -> None:
        """Queue a single-use response, popped in FIFO order."""
        self.responses.setdefault(path, []).append(response)

    def queue_always(self, path: str, response: Any) -> None:
        """Answer every call to ``path`` with ``response``.

        For idempotent GETs the code may legitimately repeat — project
        resolution happens once for the per-project run lock (DV-1563) and
        again on the claim path. A one-shot queue would couple these tests to
        that call count, which is an implementation detail.
        """
        self.sticky[path] = response

    def _pop(self, method: str, path: str, body: dict | None = None) -> Any:
        self.calls.append((method, path, body))
        q = self.responses.get(path)
        if not q:
            if path in self.sticky:
                return self.sticky[path]
            # Startup validation + online sync for locally cached agents.
            if method == "GET" and re.fullmatch(r"/agents/[^/]+", path):
                agent_id = path.rsplit("/", 1)[-1]
                return {"agent": {"id": agent_id}}
            if method == "POST" and re.fullmatch(r"/agents/[^/]+/sync", path):
                agent_id = path.split("/")[2]
                return {"success": True, "agent": {"id": agent_id}}
            # DV-1247 task-card endpoints are claimed on every poll pass; tests
            # that don't exercise task cards get an empty default.
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

    def delete(self, path: str, params: dict | None = None) -> Any:
        return self._pop("DELETE", path, params)


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
    monkeypatch.setattr(
        http_module.DeepVistaClient,
        "delete",
        lambda self, path, params=None: stub.delete(path, params),
    )


DEFAULT_PROJECT_ID = "proj-default"


def _stub_working_project(stub: _StubCtxClient, project_id: str = DEFAULT_PROJECT_ID) -> None:
    """Queue API responses so ``tasks run`` resolves a working project."""
    stub.queue_always("/projects/me", {"id": project_id, "name": "Default project"})
    stub.queue_always("/projects", [{"id": project_id, "name": "Default project"}])


def _register_local_agent(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    agent_id: str = "agent-uuid-1",
    project_id: str = DEFAULT_PROJECT_ID,
) -> None:
    """Write a fingerprint+project Machine cache and point modules at it."""
    import deepvista_cli.commands.agents as agents_module
    import deepvista_cli.commands.tasks as tq_module

    fp = "test-machine-fp"
    monkeypatch.setattr(agents_module, "detect_agent_tool", lambda: ("deepvista-cli", "test"))
    monkeypatch.setattr(tq_module, "detect_agent_tool", lambda: ("deepvista-cli", "test"))
    monkeypatch.setattr(agents_module, "_machine_fingerprint", lambda: fp)

    machines_dir = tmp_path / ".config" / "deepvista" / "machines"
    machines_dir.mkdir(parents=True, exist_ok=True)
    (machines_dir / f"{fp}__{project_id}.json").write_text(
        json.dumps(
            {
                "agent_id": agent_id,
                "machine_fingerprint": fp,
                "last_seen_tool": "deepvista-cli",
                "agent_type": "deepvista-cli",
                "project_id": project_id,
            }
        )
    )
    monkeypatch.setattr(agents_module, "MACHINES_DIR", machines_dir)
    monkeypatch.setattr(tq_module, "MACHINES_DIR", machines_dir)
    monkeypatch.setattr(tq_module, "RUN_LOCK_DIR", tmp_path / ".config" / "deepvista")


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


def test_run_once_exits_immediately_when_queue_empty(
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub = _StubCtxClient()
    _stub_working_project(stub)
    stub.queue("/agents/agent-uuid-1/tasks/claim", {"success": True, "tasks": []})
    _install_stub_client(monkeypatch, stub)
    _register_local_agent(monkeypatch, isolated_home)

    result = CliRunner().invoke(cli, ["tasks", "run", "--run-once"])
    assert result.exit_code == 0, result.output
    payload = _parse_first_json(result.output)
    assert payload["tasks_run"] == 0
    claim_calls = [c[1] for c in stub.calls if c[1].endswith("/tasks/claim")]
    assert claim_calls == ["/agents/agent-uuid-1/tasks/claim"]


class _FakeStreamJsonProc:
    """Stand-in for the `claude -p --output-format stream-json` Popen (DV-1428).

    ``stdout`` is a plain iterable of JSONL strings (one per stream-json
    event) so ``for raw_line in proc.stdout`` in ``_run_task_card`` works
    without a real subprocess.
    """

    def __init__(self, event_lines: list[str], returncode: int = 0) -> None:
        self.stdout = iter(event_lines)
        self.stderr = _EmptyReadable()
        self.returncode = returncode
        self.killed = False

    def wait(self, timeout: float | None = None) -> int:
        return self.returncode

    def kill(self) -> None:
        self.killed = True


class _EmptyReadable:
    def read(self) -> str:
        return ""


def _stream_json_lines(*events: dict) -> list[str]:
    return [json.dumps(event) for event in events]


def test_summarize_tool_input_prefers_command_key():
    assert _summarize_tool_input({"command": "ls -la", "description": "list files"}) == "ls -la"


def test_summarize_tool_input_falls_back_through_keys():
    assert _summarize_tool_input({"path": "/tmp/foo"}) == "/tmp/foo"


def test_summarize_tool_input_truncates_long_values():
    long_value = "x" * 200
    assert _summarize_tool_input({"query": long_value}) == long_value[:80]


def test_summarize_tool_input_no_known_key_returns_empty():
    assert _summarize_tool_input({"foo": "bar"}) == ""


def test_summarize_stream_event_tool_use():
    event = {
        "type": "assistant",
        "message": {"content": [{"type": "tool_use", "name": "Bash", "input": {"command": "ls /tmp"}}]},
    }
    assert _summarize_stream_event(event) == "🔧 Bash: ls /tmp"


def test_summarize_stream_event_text():
    event = {"type": "assistant", "message": {"content": [{"type": "text", "text": "Working on it\nsecond line"}]}}
    assert _summarize_stream_event(event) == "💬 Working on it second line"


def test_summarize_stream_event_ignores_non_assistant_events():
    assert _summarize_stream_event({"type": "system", "subtype": "hook_started"}) is None
    assert _summarize_stream_event({"type": "result", "result": "done"}) is None


def test_run_executes_task_card_via_claude_and_reports_output(
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DV-1247/DV-1428: a claimed task card runs `claude -p` with incremental
    stream-json output; the final `result` event's text is reported as the
    output and the run completes."""
    stub = _StubCtxClient()
    _stub_working_project(stub)
    stub.queue(
        "/agents/agent-uuid-1/tasks/claim",
        {"success": True, "tasks": [{"id": "tc-1", "prompt": "reply hello world", "title": "Say hello"}]},
    )
    stub.queue("/agents/agent-uuid-1/tasks/claim", {"success": True, "tasks": []})
    stub.queue("/agents/agent-uuid-1/tasks/tc-1/result", {"success": True, "output_card_id": "out-1"})
    _install_stub_client(monkeypatch, stub)
    _register_local_agent(monkeypatch, isolated_home)

    import deepvista_cli.commands.tasks as tq_module

    executed: list[list[str]] = []
    event_lines = _stream_json_lines(
        {
            "type": "assistant",
            "message": {"content": [{"type": "tool_use", "name": "Bash", "input": {"command": "echo hi"}}]},
        },
        {"type": "result", "subtype": "success", "is_error": False, "result": "Hello, world!"},
    )

    def fake_popen(argv, **kwargs):  # type: ignore[no-untyped-def]
        executed.append(argv)
        return _FakeStreamJsonProc(event_lines)

    monkeypatch.setattr(tq_module.subprocess, "Popen", fake_popen)

    result = CliRunner().invoke(cli, ["tasks", "run", "--run-once"])
    assert result.exit_code == 0, result.output

    # Claude was invoked headless with the /deepvista-prefixed prompt, streaming.
    assert executed, "claude was not launched"
    argv = executed[0]
    assert argv[1] == "-p"
    assert argv[2].startswith("/deepvista [Task ID: tc-1.")
    assert argv[2].endswith("reply hello world")
    assert "--permission-mode" in argv
    assert "--output-format" in argv and "stream-json" in argv

    # The result (with the stream's final text) was reported to the task-card endpoint.
    result_calls = [c for c in stub.calls if c[1] == "/agents/agent-uuid-1/tasks/tc-1/result"]
    assert result_calls, "no result reported"
    _, _, body = result_calls[-1]
    assert body["status"] == "completed"
    assert body["exit_code"] == 0
    assert body["output"] == "Hello, world!"

    # A live-activity note fired for the tool-call event (DV-1428).
    note_calls = [c for c in stub.calls if c[1] == "/agents/agent-uuid-1/tasks/tc-1/note"]
    assert note_calls, "no live-activity note reported"
    assert "Bash" in note_calls[0][2]["note"]


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

    empty = isolated_home / ".config" / "deepvista" / "machines"
    monkeypatch.setattr(agents_module, "MACHINES_DIR", empty)
    monkeypatch.setattr(tq_module, "MACHINES_DIR", empty)
    monkeypatch.setattr(agents_module, "AGENTS_DIR", empty / "legacy-agents")
    monkeypatch.setattr(tq_module, "AGENTS_DIR", empty / "legacy-agents")
    monkeypatch.setattr(tq_module, "RUN_LOCK_DIR", isolated_home / ".config" / "deepvista")
    monkeypatch.setattr(agents_module, "_machine_fingerprint", lambda: "empty-fp")

    result = CliRunner().invoke(cli, ["tasks", "run"])
    assert result.exit_code == 3


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
        stub.queue("/agents/agent-uuid-1/tasks/claim", {"success": True, "tasks": []})
    _install_stub_client(monkeypatch, stub)
    _register_local_agent(monkeypatch, isolated_home)
    clock = _install_fake_clock(monkeypatch)

    result = CliRunner().invoke(cli, ["tasks", "run", "--poll-interval", "10", "--total-time", "25"])
    assert result.exit_code == 0, result.output

    # Passes at t=0, 10, 20; a fourth pass would start past the 25s budget.
    claim_calls = [c[1] for c in stub.calls if c[1].endswith("/tasks/claim")]
    assert claim_calls == ["/agents/agent-uuid-1/tasks/claim"] * 3
    assert clock.sleeps == [10, 10]

    # Empty passes are quiet; only the final summary is printed.
    assert "listening" in result.output
    assert "poll #2" not in result.output
    assert "sleeping" not in result.output
    payload = _parse_first_json(result.output)
    assert payload == {"agent_id": "agent-uuid-1", "polls": 3, "tasks_run": 0, "failed": 0}


def test_run_survives_transient_network_failure_mid_poll(
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A poll that fails with a persisted network error is skipped, not fatal (DV-1529)."""
    stub = _StubCtxClient()
    _stub_working_project(stub)
    stub.queue("/agents/agent-uuid-1/tasks/claim", {"success": True, "tasks": []})
    _install_stub_client(monkeypatch, stub)
    _register_local_agent(monkeypatch, isolated_home)
    clock = _install_fake_clock(monkeypatch)

    import deepvista_cli.commands.tasks as tq_module
    from deepvista_cli.config import EXIT_NETWORK_ERROR

    real_claim_and_submit_all = tq_module._claim_and_submit_all
    calls = {"n": 0}

    def flaky_claim_and_submit_all(ctx, agents, executor):  # type: ignore[no-untyped-def]
        calls["n"] += 1
        if calls["n"] == 1:
            raise SystemExit(EXIT_NETWORK_ERROR)
        return real_claim_and_submit_all(ctx, agents, executor)

    monkeypatch.setattr(tq_module, "_claim_and_submit_all", flaky_claim_and_submit_all)

    result = CliRunner().invoke(cli, ["tasks", "run", "--poll-interval", "10", "--total-time", "15"])

    assert result.exit_code == 0, result.output
    assert calls["n"] == 2
    assert "network error persisted after retries, skipping this poll" in result.output
    payload = _parse_first_json(result.output)
    assert payload == {"agent_id": "agent-uuid-1", "polls": 2, "tasks_run": 0, "failed": 0}
    assert clock.sleeps == [10]


def test_run_once_still_fails_fast_on_persistent_network_error(
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`--run-once` (the cron entrypoint) keeps the old fail-fast contract."""
    stub = _StubCtxClient()
    _stub_working_project(stub)
    _install_stub_client(monkeypatch, stub)
    _register_local_agent(monkeypatch, isolated_home)

    import deepvista_cli.commands.tasks as tq_module
    from deepvista_cli.config import EXIT_NETWORK_ERROR

    def always_fails(ctx, agents, executor):  # type: ignore[no-untyped-def]
        raise SystemExit(EXIT_NETWORK_ERROR)

    monkeypatch.setattr(tq_module, "_claim_and_submit_all", always_fails)

    result = CliRunner().invoke(cli, ["tasks", "run", "--run-once"])

    assert result.exit_code == EXIT_NETWORK_ERROR


def test_run_verbose_logs_every_idle_poll(
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub = _StubCtxClient()
    _stub_working_project(stub)
    for _ in range(2):
        stub.queue("/agents/agent-uuid-1/tasks/claim", {"success": True, "tasks": []})
    _install_stub_client(monkeypatch, stub)
    _register_local_agent(monkeypatch, isolated_home)
    _install_fake_clock(monkeypatch)

    result = CliRunner().invoke(
        cli,
        ["tasks", "run", "--poll-interval", "10", "--total-time", "15", "--verbose"],
    )
    assert result.exit_code == 0, result.output
    assert "poll #1" in result.output
    assert "poll #2" in result.output
    assert "sleeping 10s" in result.output


def test_run_quiet_suppresses_idle_status_lines(
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub = _StubCtxClient()
    _stub_working_project(stub)
    stub.queue("/agents/agent-uuid-1/tasks/claim", {"success": True, "tasks": []})
    _install_stub_client(monkeypatch, stub)
    _register_local_agent(monkeypatch, isolated_home)

    result = CliRunner().invoke(cli, ["tasks", "run", "--run-once", "--quiet"])
    assert result.exit_code == 0, result.output
    assert "listening" not in result.output
    assert "poll #" not in result.output
    payload = _parse_first_json(result.output)
    assert payload["tasks_run"] == 0


def test_run_polling_executes_task_cards_across_passes(
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub = _StubCtxClient()
    _stub_working_project(stub)
    stub.queue(
        "/agents/agent-uuid-1/tasks/claim",
        {"success": True, "tasks": [{"id": "tc-1", "prompt": "reply hello", "title": "Say hello"}]},
    )
    stub.queue("/agents/agent-uuid-1/tasks/claim", {"success": True, "tasks": []})
    stub.queue("/agents/agent-uuid-1/tasks/tc-1/result", {"success": True})
    _install_stub_client(monkeypatch, stub)
    _register_local_agent(monkeypatch, isolated_home)
    _install_fake_clock(monkeypatch)

    import deepvista_cli.commands.tasks as tq_module

    def fake_popen(argv, **kwargs):  # type: ignore[no-untyped-def]
        return _FakeStreamJsonProc(
            _stream_json_lines({"type": "result", "subtype": "success", "is_error": False, "result": "ok"}),
        )

    monkeypatch.setattr(tq_module.subprocess, "Popen", fake_popen)

    result = CliRunner().invoke(cli, ["tasks", "run", "--poll-interval", "30", "--total-time", "45"])
    assert result.exit_code == 0, result.output

    payloads = _parse_json_objects(result.output)
    assert payloads[-1]["tasks_run"] == 1
    assert payloads[-1]["failed"] == 0


def test_run_refuses_when_another_run_holds_the_lock(
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub = _StubCtxClient()
    # The run lock is per project (DV-1563), so the working project is resolved
    # before the lock is even named.
    _stub_working_project(stub)
    _install_stub_client(monkeypatch, stub)
    _register_local_agent(monkeypatch, isolated_home)

    import deepvista_cli.commands.tasks as tq_module

    # PID 1 (launchd/init) is always alive and never this process.
    lock_path = tq_module._run_lock_path(DEFAULT_PROJECT_ID)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text("1")

    result = CliRunner().invoke(cli, ["tasks", "run", "--run-once"])
    assert result.exit_code == 2
    # No claim — a second instance must not touch the project's queue.
    assert not [c for c in stub.calls if "/tasks/claim" in c[1]]
    # The foreign lock is left in place.
    assert lock_path.read_text() == "1"


def test_run_locks_are_per_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The point of DV-1563: one machine, one daemon per project, no crosstalk.

    A live daemon on proj-1 must not block proj-2 — under the old single global
    lock it did, so a second project's queue silently never got polled.
    """
    import deepvista_cli.commands.tasks as tq_module

    monkeypatch.setattr(tq_module, "RUN_LOCK_DIR", tmp_path)

    one = tq_module._run_lock_path("proj-1")
    two = tq_module._run_lock_path("proj-2")
    assert one != two

    # PID 1 (launchd/init) is always alive and never this process.
    one.parent.mkdir(parents=True, exist_ok=True)
    one.write_text("1")

    assert tq_module._acquire_run_lock(one) is False
    assert tq_module._acquire_run_lock(two) is True

    tq_module._release_run_lock(two)
    assert not two.exists()
    # Releasing ours must never disturb another project's lock.
    assert one.read_text() == "1"


def test_release_run_lock_leaves_a_foreign_lock_alone(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A crashed-then-restarted daemon must not delete the new owner's lock."""
    import deepvista_cli.commands.tasks as tq_module

    monkeypatch.setattr(tq_module, "RUN_LOCK_DIR", tmp_path)
    lock = tq_module._run_lock_path("proj-1")
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text("1")

    tq_module._release_run_lock(lock)
    assert lock.read_text() == "1"


def test_stale_lock_from_a_dead_pid_is_reclaimed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import deepvista_cli.commands.tasks as tq_module

    monkeypatch.setattr(tq_module, "RUN_LOCK_DIR", tmp_path)
    monkeypatch.setattr(tq_module, "_pid_alive", lambda pid: False)
    lock = tq_module._run_lock_path("proj-1")
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text("99999999")

    assert tq_module._acquire_run_lock(lock) is True
    assert lock.read_text() == str(os.getpid())


def test_run_reclaims_stale_lock_and_releases_on_exit(
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub = _StubCtxClient()
    _stub_working_project(stub)
    stub.queue("/agents/agent-uuid-1/tasks/claim", {"success": True, "tasks": []})
    _install_stub_client(monkeypatch, stub)
    _register_local_agent(monkeypatch, isolated_home)

    import deepvista_cli.commands.tasks as tq_module

    lock_path = tq_module._run_lock_path(DEFAULT_PROJECT_ID)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text("99999999")
    monkeypatch.setattr(tq_module, "_pid_alive", lambda pid: False)

    result = CliRunner().invoke(cli, ["tasks", "run", "--run-once"])
    assert result.exit_code == 0, result.output
    assert [c[1] for c in stub.calls if c[1].endswith("/tasks/claim")] == ["/agents/agent-uuid-1/tasks/claim"]
    # Lock was reclaimed for the run and removed afterwards.
    assert not lock_path.exists()


# ---------------------------------------------------------------------------
# parallel execution
# ---------------------------------------------------------------------------


def test_run_executes_multiple_task_cards_in_parallel(
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Claimed task cards run concurrently up to --max-parallel."""
    stub = _StubCtxClient()
    _stub_working_project(stub)
    tasks = [{"id": f"tc-{i}", "prompt": f"task {i}", "title": f"Task {i}"} for i in range(3)]
    stub.queue("/agents/agent-uuid-1/tasks/claim", {"success": True, "tasks": tasks})
    stub.queue("/agents/agent-uuid-1/tasks/claim", {"success": True, "tasks": []})
    for task in tasks:
        stub.queue(f"/agents/agent-uuid-1/tasks/{task['id']}/result", {"success": True})
    _install_stub_client(monkeypatch, stub)
    _register_local_agent(monkeypatch, isolated_home)

    import deepvista_cli.commands.tasks as tq_module

    active = 0
    peak = 0
    active_lock = threading.Lock()
    start_barrier = threading.Barrier(3)

    def fake_popen(argv, **kwargs):  # type: ignore[no-untyped-def]
        nonlocal active, peak
        with active_lock:
            active += 1
            peak = max(peak, active)
        start_barrier.wait(timeout=2)
        with active_lock:
            active -= 1
        return _FakeStreamJsonProc(
            _stream_json_lines({"type": "result", "subtype": "success", "is_error": False, "result": "ok"}),
        )

    monkeypatch.setattr(tq_module.subprocess, "Popen", fake_popen)

    result = CliRunner().invoke(cli, ["tasks", "run", "--run-once", "--max-parallel", "3"])
    assert result.exit_code == 0, result.output
    payload = _parse_first_json(result.output)
    assert payload["tasks_run"] == 3
    assert peak >= 2, f"expected overlapping runs, peak concurrency was {peak}"


def test_run_max_parallel_caps_concurrency(
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """--max-parallel limits how many headless runs are active at once."""
    stub = _StubCtxClient()
    _stub_working_project(stub)
    tasks = [{"id": f"tc-{i}", "prompt": f"task {i}"} for i in range(4)]
    stub.queue("/agents/agent-uuid-1/tasks/claim", {"success": True, "tasks": tasks})
    stub.queue("/agents/agent-uuid-1/tasks/claim", {"success": True, "tasks": []})
    for task in tasks:
        stub.queue(f"/agents/agent-uuid-1/tasks/{task['id']}/result", {"success": True})
    _install_stub_client(monkeypatch, stub)
    _register_local_agent(monkeypatch, isolated_home)

    import deepvista_cli.commands.tasks as tq_module

    active = 0
    peak = 0
    active_lock = threading.Lock()

    def fake_popen(argv, **kwargs):  # type: ignore[no-untyped-def]
        nonlocal active, peak
        with active_lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.05)
        with active_lock:
            active -= 1
        return _FakeStreamJsonProc(
            _stream_json_lines({"type": "result", "subtype": "success", "is_error": False, "result": "ok"}),
        )

    monkeypatch.setattr(tq_module.subprocess, "Popen", fake_popen)

    result = CliRunner().invoke(cli, ["tasks", "run", "--run-once", "--max-parallel", "2"])
    assert result.exit_code == 0, result.output
    assert peak <= 2, f"expected at most 2 concurrent runs, saw {peak}"
    payload = _parse_first_json(result.output)
    assert payload["tasks_run"] == 4


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


def test_list_shows_queue(
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub = _StubCtxClient()
    _stub_working_project(stub)
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
# Machine identity + project claim scope
# ---------------------------------------------------------------------------


def _register_machine(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    agent_id: str = "agent-machine-1",
    project_id: str = "proj-1",
) -> None:
    """Write one fingerprint+project Machine registration."""
    import deepvista_cli.commands.agents as agents_module
    import deepvista_cli.commands.tasks as tq_module

    fp = "test-machine-fp"
    monkeypatch.setattr(agents_module, "detect_agent_tool", lambda: ("claude-code", "test"))
    monkeypatch.setattr(tq_module, "detect_agent_tool", lambda: ("claude-code", "test"))
    monkeypatch.setattr(agents_module, "_machine_fingerprint", lambda: fp)

    machines_dir = tmp_path / ".config" / "deepvista" / "machines"
    machines_dir.mkdir(parents=True, exist_ok=True)
    (machines_dir / f"{fp}__{project_id}.json").write_text(
        json.dumps(
            {
                "agent_id": agent_id,
                "machine_fingerprint": fp,
                "last_seen_tool": "claude-code",
                "agent_type": "claude-code",
                "project_id": project_id,
            }
        )
    )
    monkeypatch.setattr(agents_module, "MACHINES_DIR", machines_dir)
    monkeypatch.setattr(tq_module, "MACHINES_DIR", machines_dir)
    monkeypatch.setattr(tq_module, "RUN_LOCK_DIR", tmp_path / ".config" / "deepvista")


def test_run_once_polls_only_current_project_agent(
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``tasks run`` scopes claims to the working project on this Machine."""
    stub = _StubCtxClient()
    stub.queue_always("/projects/me", {"id": "proj-1", "name": "Project 1"})
    stub.queue_always("/projects", [{"id": "proj-1", "name": "Project 1"}, {"id": "proj-2", "name": "Project 2"}])
    stub.queue("/agents/agent-machine-1/tasks/claim", {"success": True, "tasks": []})
    _install_stub_client(monkeypatch, stub)
    _register_machine(monkeypatch, isolated_home)

    result = CliRunner().invoke(cli, ["tasks", "run", "--run-once", "--project", "proj-1"])
    assert result.exit_code == 0, result.output

    claimed_paths = {c[1] for c in stub.calls}
    assert "/agents/agent-machine-1/tasks/claim" in claimed_paths


def test_run_type_filter_uses_same_machine(
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """--type is soft metadata; Machine identity is still fingerprint-keyed."""
    stub = _StubCtxClient()
    _stub_working_project(stub, "proj-1")
    stub.queue("/agents/agent-machine-1/tasks/claim", {"success": True, "tasks": []})
    _install_stub_client(monkeypatch, stub)
    _register_machine(monkeypatch, isolated_home)

    result = CliRunner().invoke(cli, ["tasks", "run", "--run-once", "--type", "claude-code", "--project", "proj-1"])
    assert result.exit_code == 0, result.output

    claimed_paths = [c[1] for c in stub.calls if c[1].endswith("/tasks/claim")]
    assert claimed_paths == ["/agents/agent-machine-1/tasks/claim"]


def test_run_project_flag_registers_separate_project_binding(
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``--project`` scopes identity — same device can bind to another project."""
    stub = _StubCtxClient()
    stub.queue_always("/projects/me", {"id": "proj-2", "name": "Project 2"})
    stub.queue_always("/projects", [{"id": "proj-1", "name": "Project 1"}, {"id": "proj-2", "name": "Project 2"}])
    # No local cache for proj-2 → register path.
    stub.queue(
        "/agents",
        {
            "success": True,
            "agent": {
                "id": "agent-proj-2",
                "project_id": "proj-2",
                "machine_fingerprint": "test-machine-fp",
                "config": {"machine_fingerprint": "test-machine-fp"},
            },
        },
    )
    stub.queue("/agents/agent-proj-2/tasks/claim", {"success": True, "tasks": []})
    _install_stub_client(monkeypatch, stub)
    # Seed only proj-1 so proj-2 must register.
    _register_machine(monkeypatch, isolated_home, agent_id="agent-proj-1", project_id="proj-1")

    result = CliRunner().invoke(cli, ["tasks", "run", "--run-once", "--project", "proj-2"])
    assert result.exit_code == 0, result.output
    claimed_paths = {c[1] for c in stub.calls}
    assert "/agents/agent-proj-2/tasks/claim" in claimed_paths


def test_run_keeps_machine_registration_for_project(
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Project-scoped Machine cache is retained across polls."""
    import deepvista_cli.commands.agents as agents_module
    import deepvista_cli.commands.tasks as tq_module

    fp = "test-machine-fp"
    machines_dir = isolated_home / ".config" / "deepvista" / "machines"
    machines_dir.mkdir(parents=True, exist_ok=True)
    machine_file = machines_dir / f"{fp}__proj-1.json"
    machine_file.write_text(
        json.dumps(
            {
                "agent_id": "agent-machine-1",
                "machine_fingerprint": fp,
                "last_seen_tool": "deepvista-cli",
                "project_id": "proj-1",
            }
        )
    )
    monkeypatch.setattr(agents_module, "detect_agent_tool", lambda: ("deepvista-cli", "test"))
    monkeypatch.setattr(tq_module, "detect_agent_tool", lambda: ("deepvista-cli", "test"))
    monkeypatch.setattr(agents_module, "_machine_fingerprint", lambda: fp)
    monkeypatch.setattr(agents_module, "MACHINES_DIR", machines_dir)
    monkeypatch.setattr(tq_module, "MACHINES_DIR", machines_dir)
    monkeypatch.setattr(tq_module, "RUN_LOCK_DIR", isolated_home / ".config" / "deepvista")

    stub = _StubCtxClient()
    stub.queue_always("/projects/me", {"id": "proj-1", "name": "Project 1"})
    stub.queue_always("/projects", [{"id": "proj-1", "name": "Project 1"}])
    stub.queue("/agents/agent-machine-1/tasks/claim", {"success": True, "tasks": []})
    _install_stub_client(monkeypatch, stub)

    result = CliRunner().invoke(cli, ["tasks", "run", "--run-once", "--project", "proj-1"])
    assert result.exit_code == 0, result.output
    assert machine_file.exists()
    assert "removed stale agent" not in result.output


# ---------------------------------------------------------------------------
# DV-1429: claim failures must not empty the poll list
# ---------------------------------------------------------------------------


def test_run_keeps_agent_on_claim_agent_not_found(
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Claim AGENT_NOT_FOUND must not prune the poller's agent list (--run-once)."""
    stub = _StubCtxClient()
    _stub_working_project(stub)
    stub.queue(
        "/agents/agent-uuid-1/tasks/claim",
        {"success": False, "error": "Machine not found", "error_code": "AGENT_NOT_FOUND"},
    )
    _install_stub_client(monkeypatch, stub)
    _register_local_agent(monkeypatch, isolated_home)
    agent_file = isolated_home / ".config" / "deepvista" / "machines" / f"test-machine-fp__{DEFAULT_PROJECT_ID}.json"
    assert agent_file.exists()

    result = CliRunner().invoke(cli, ["tasks", "run", "--run-once"])

    assert result.exit_code == 0, result.output
    assert json.loads(agent_file.read_text())["agent_id"] == "agent-uuid-1"
    assert "removed stale agent" not in result.output
    assert "could not claim task cards" in result.output


def test_run_keeps_agent_after_transient_claim_failure(
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed claim on one poll must not empty ``agent_id`` for later polls."""
    stub = _StubCtxClient()
    _stub_working_project(stub)
    stub.queue(
        "/agents/agent-uuid-1/tasks/claim",
        {"success": False, "error": "Not Found", "_status_code": 404},
    )
    stub.queue("/agents/agent-uuid-1/tasks/claim", {"success": True, "tasks": []})
    _install_stub_client(monkeypatch, stub)
    _register_local_agent(monkeypatch, isolated_home)

    result = CliRunner().invoke(cli, ["tasks", "run", "--poll-interval", "10", "--total-time", "15"])

    assert result.exit_code == 0, result.output
    payloads = _parse_json_objects(result.output)
    assert payloads
    assert all(p.get("agent_id") == "agent-uuid-1" for p in payloads if "agent_id" in p)
    assert "removed stale agent" not in result.output


def test_run_syncs_online_each_poll(
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each poll pass re-validates the local agent and syncs online before claiming."""
    stub = _StubCtxClient()
    _stub_working_project(stub)
    for _ in range(2):
        stub.queue("/agents/agent-uuid-1/tasks/claim", {"success": True, "tasks": []})
    _install_stub_client(monkeypatch, stub)
    _register_local_agent(monkeypatch, isolated_home)
    _install_fake_clock(monkeypatch)

    result = CliRunner().invoke(cli, ["tasks", "run", "--poll-interval", "10", "--total-time", "15"])
    assert result.exit_code == 0, result.output

    sync_calls = [c[1] for c in stub.calls if c[1].endswith("/sync")]
    assert len(sync_calls) >= 2
    claim_calls = [c[1] for c in stub.calls if c[1].endswith("/tasks/claim")]
    assert len(claim_calls) == 2


# ---------------------------------------------------------------------------
# DV-1429: `tasks clean` — delete terminated task cards
# ---------------------------------------------------------------------------

_QUEUE_SAMPLE = [
    {"id": "tc-pending", "status": "pending", "title": "Pending", "prompt": "do something"},
    {"id": "tc-running", "status": "running", "title": "Running", "prompt": "do something"},
    {"id": "tc-done", "status": "completed", "title": "Done", "prompt": "do something"},
    {"id": "tc-fail", "status": "failed", "title": "Failed", "prompt": "do something"},
]


def test_clean_deletes_terminal_tasks_by_default(
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`tasks clean` (no args) deletes completed + failed entries, leaving active ones."""
    stub = _StubCtxClient()
    _stub_working_project(stub)
    stub.queue("/agents/agent-uuid-1/tasks", {"tasks": _QUEUE_SAMPLE})
    stub.queue("/agents/agent-uuid-1/tasks/tc-done", {"success": True})
    stub.queue("/agents/agent-uuid-1/tasks/tc-fail", {"success": True})
    _install_stub_client(monkeypatch, stub)
    _register_local_agent(monkeypatch, isolated_home)

    result = CliRunner().invoke(cli, ["tasks", "clean"])

    assert result.exit_code == 0, result.output
    deleted = [c[1] for c in stub.calls if c[0] == "DELETE"]
    assert deleted == [
        "/agents/agent-uuid-1/tasks/tc-done",
        "/agents/agent-uuid-1/tasks/tc-fail",
    ]


def test_clean_dry_run_deletes_nothing(
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`tasks clean --dry-run` previews the delete set without issuing DELETEs."""
    stub = _StubCtxClient()
    _stub_working_project(stub)
    stub.queue("/agents/agent-uuid-1/tasks", {"tasks": _QUEUE_SAMPLE})
    _install_stub_client(monkeypatch, stub)
    _register_local_agent(monkeypatch, isolated_home)

    result = CliRunner().invoke(cli, ["tasks", "clean", "--dry-run"])

    assert result.exit_code == 0, result.output
    assert not [c for c in stub.calls if c[0] == "DELETE"]
    assert "tc-done" in result.output and "tc-fail" in result.output


def test_clean_explicit_ids_skips_listing(
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`tasks clean <id>...` deletes exactly those ids and never lists the queue."""
    stub = _StubCtxClient()
    _stub_working_project(stub)
    stub.queue("/agents/agent-uuid-1/tasks/tc-1", {"success": True})
    stub.queue("/agents/agent-uuid-1/tasks/tc-2", {"success": True})
    _install_stub_client(monkeypatch, stub)
    _register_local_agent(monkeypatch, isolated_home)

    result = CliRunner().invoke(cli, ["tasks", "clean", "tc-1", "tc-2"])

    assert result.exit_code == 0, result.output
    deleted = [c[1] for c in stub.calls if c[0] == "DELETE"]
    assert deleted == [
        "/agents/agent-uuid-1/tasks/tc-1",
        "/agents/agent-uuid-1/tasks/tc-2",
    ]
    assert not [c for c in stub.calls if c[0] == "GET" and c[1].endswith("/tasks")]
