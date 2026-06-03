"""Click-level tests for `deepvista task_queue run` / `list` / `setup` (DV-936)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

from deepvista_cli.commands.task_queue import CRON_MARKER, _cron_entry, _validate_command
from deepvista_cli.main import cli


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
    monkeypatch.setattr(http_module.DeepVistaClient, "post", lambda self, path, body=None: stub.post(path, body))
    monkeypatch.setattr(http_module.DeepVistaClient, "get", lambda self, path, params=None: stub.get(path, params))


def _register_local_agent(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, agent_id: str = "agent-uuid-1") -> None:
    """Write a local agent registration file and point the command module at it."""
    agents_dir = tmp_path / ".config" / "deepvista" / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    (agents_dir / "deepvista-cli__misc.json").write_text(
        json.dumps({"agent_id": agent_id, "agent_type": "deepvista-cli", "agent_role": "misc"})
    )
    import deepvista_cli.commands.agents as agents_module
    import deepvista_cli.commands.task_queue as tq_module

    monkeypatch.setattr(agents_module, "AGENTS_DIR", agents_dir)
    monkeypatch.setattr(tq_module, "AGENTS_DIR", agents_dir)


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


def test_run_exits_immediately_when_queue_empty(
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub = _StubCtxClient()
    stub.queue("/agents/agent-uuid-1/task-queue/claim", {"success": True, "tasks": []})
    _install_stub_client(monkeypatch, stub)
    _register_local_agent(monkeypatch, isolated_home)

    result = CliRunner().invoke(cli, ["task_queue", "run"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["tasks_run"] == 0
    # Only the claim call — no execution, no result reports.
    assert [c[1] for c in stub.calls] == ["/agents/agent-uuid-1/task-queue/claim"]


def test_run_executes_claimed_task_and_reports_result(
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub = _StubCtxClient()
    stub.queue(
        "/agents/agent-uuid-1/task-queue/claim",
        {"success": True, "tasks": [{"id": "t-1", "command": "deepvista notes list", "status": "running"}]},
    )
    stub.queue("/agents/agent-uuid-1/task-queue/t-1/result", {"success": True})
    _install_stub_client(monkeypatch, stub)
    _register_local_agent(monkeypatch, isolated_home)

    import deepvista_cli.commands.task_queue as tq_module

    class _FakeProc:
        returncode = 0
        stdout = "ok"
        stderr = ""

    executed: list[list[str]] = []

    def fake_run(argv, **kwargs):  # type: ignore[no-untyped-def]
        executed.append(argv)
        return _FakeProc()

    monkeypatch.setattr(tq_module.subprocess, "run", fake_run)

    result = CliRunner().invoke(cli, ["task_queue", "run"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["tasks_run"] == 1
    assert payload["failed"] == 0
    assert payload["results"][0]["status"] == "completed"

    # Executed argv keeps the CLI args, binary resolved to an absolute path or name.
    assert executed[0][1:] == ["notes", "list"]

    # Result was reported to the backend.
    method, path, body = stub.calls[-1]
    assert (method, path) == ("POST", "/agents/agent-uuid-1/task-queue/t-1/result")
    assert body == {"status": "completed", "exit_code": 0, "output_tail": "ok"}


def test_run_rejects_non_deepvista_command_without_executing(
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub = _StubCtxClient()
    stub.queue(
        "/agents/agent-uuid-1/task-queue/claim",
        {"success": True, "tasks": [{"id": "t-1", "command": "rm -rf /", "status": "running"}]},
    )
    stub.queue("/agents/agent-uuid-1/task-queue/t-1/result", {"success": True})
    _install_stub_client(monkeypatch, stub)
    _register_local_agent(monkeypatch, isolated_home)

    import deepvista_cli.commands.task_queue as tq_module

    def explode(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("subprocess.run must not be called for disallowed commands")

    monkeypatch.setattr(tq_module.subprocess, "run", explode)

    result = CliRunner().invoke(cli, ["task_queue", "run"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
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
    _install_stub_client(monkeypatch, stub)
    import deepvista_cli.commands.agents as agents_module
    import deepvista_cli.commands.task_queue as tq_module

    empty = isolated_home / ".config" / "deepvista" / "agents"
    monkeypatch.setattr(agents_module, "AGENTS_DIR", empty)
    monkeypatch.setattr(tq_module, "AGENTS_DIR", empty)

    result = CliRunner().invoke(cli, ["task_queue", "run"])
    assert result.exit_code == 3
    assert stub.calls == []


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


def test_list_shows_queue(
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub = _StubCtxClient()
    stub.queue(
        "/agents/agent-uuid-1/task-queue",
        {"tasks": [{"id": "t-1", "command": "deepvista notes list", "status": "pending"}]},
    )
    _install_stub_client(monkeypatch, stub)
    _register_local_agent(monkeypatch, isolated_home)

    result = CliRunner().invoke(cli, ["task_queue", "list"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
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

    import deepvista_cli.commands.task_queue as tq_module

    monkeypatch.setattr(tq_module, "_read_crontab", lambda: ["0 0 * * * /bin/true"])

    def explode(lines):  # type: ignore[no-untyped-def]
        raise AssertionError("crontab must not be written in dry-run")

    monkeypatch.setattr(tq_module, "_write_crontab", explode)

    result = CliRunner().invoke(cli, ["--dry-run", "task_queue", "setup", "--interval", "10"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["dry_run"] is True
    assert "*/10 * * * *" in payload["entry"]
    assert CRON_MARKER in payload["entry"]


def test_setup_installs_and_replaces_entry_idempotently(
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub = _StubCtxClient()
    _install_stub_client(monkeypatch, stub)

    import deepvista_cli.commands.task_queue as tq_module

    written: list[list[str]] = []
    monkeypatch.setattr(
        tq_module,
        "_read_crontab",
        lambda: ["0 0 * * * /bin/true", f"*/5 * * * * /old/deepvista task_queue run {CRON_MARKER}"],
    )
    monkeypatch.setattr(tq_module, "_write_crontab", lambda lines: written.append(lines) or True)

    result = CliRunner().invoke(cli, ["task_queue", "setup", "--interval", "15"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
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

    import deepvista_cli.commands.task_queue as tq_module

    written: list[list[str]] = []
    monkeypatch.setattr(
        tq_module,
        "_read_crontab",
        lambda: ["0 0 * * * /bin/true", f"*/5 * * * * /usr/local/bin/deepvista task_queue run {CRON_MARKER}"],
    )
    monkeypatch.setattr(tq_module, "_write_crontab", lambda lines: written.append(lines) or True)

    result = CliRunner().invoke(cli, ["task_queue", "setup", "--remove"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["removed"] is True
    assert written[0] == ["0 0 * * * /bin/true"]


def test_cron_entry_includes_profile_flag():
    entry = _cron_entry(5, "staging")
    assert "--profile staging" in entry
    assert _cron_entry(5, "default").find("--profile") == -1
