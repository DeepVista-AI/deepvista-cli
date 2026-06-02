"""Click-level tests for `deepvista listen start / status / stop` (DV-921).

The live SSE control channel + ``claude`` subprocess are stubbed — we
only verify the command-group scaffolding here: registration is invoked
on ``start --stub``, ``status`` reflects the daemon state file, and
``stop`` sends SIGTERM + cleans up.
"""

from __future__ import annotations

import json
import os
import signal
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner


@pytest.fixture()
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("DEEPVISTA_CONFIG_DIR", str(tmp_path / ".config" / "deepvista"))
    import importlib

    import deepvista_cli.config as cfg_module

    importlib.reload(cfg_module)
    import deepvista_cli.commands.agents as agents_module

    importlib.reload(agents_module)
    import deepvista_cli.commands.listen as listen_module

    importlib.reload(listen_module)
    import deepvista_cli.main as main_module

    importlib.reload(main_module)
    return tmp_path


class _StubClient:
    """Stub for ctx.obj._client — captures posts and answers from a queue."""

    def __init__(self) -> None:
        self.posts: list[tuple[str, dict | None]] = []
        self._responses: dict[str, list[Any]] = {}

    def queue(self, path: str, response: Any) -> None:
        self._responses.setdefault(path, []).append(response)

    def post(self, path: str, body: dict | None = None) -> Any:
        self.posts.append((path, body))
        q = self._responses.get(path)
        if q:
            return q.pop(0)
        return {"success": True}

    def get(self, path: str, params: dict | None = None) -> Any:
        return {"agent": {"id": "stub-agent"}}

    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": "Bearer stub"}


def _install_stub_client(monkeypatch: pytest.MonkeyPatch, stub: _StubClient) -> None:
    from deepvista_cli.client import http as http_module

    def fake_init(self, config):  # type: ignore[no-untyped-def]
        self.config = config

    monkeypatch.setattr(http_module.DeepVistaClient, "__init__", fake_init)
    monkeypatch.setattr(http_module.DeepVistaClient, "post", lambda self, path, body=None: stub.post(path, body))
    monkeypatch.setattr(http_module.DeepVistaClient, "get", lambda self, path, params=None: stub.get(path, params))
    monkeypatch.setattr(http_module.DeepVistaClient, "_auth_headers", lambda self: stub._auth_headers())


def test_listen_start_stub_registers_and_advertises(isolated_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    stub = _StubClient()
    stub.queue("/agents", {"success": True, "agent": {"id": "agent-123", "agent_role": "daemon"}})
    _install_stub_client(monkeypatch, stub)

    # Patch hook installation to a no-op — Claude Code settings aren't here.
    import deepvista_cli.commands.agents as agents_module

    monkeypatch.setattr(agents_module, "_install_hooks", lambda _t, _p: False)

    from deepvista_cli.main import cli

    runner = CliRunner()
    result = runner.invoke(cli, ["listen", "start", "--stub", "--role", "daemon"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["daemon"] == "registered"
    assert payload["agent_id"] == "agent-123"
    assert payload["stub"] is True

    # Confirm registration + capability sync hit the wire.
    paths = [p for p, _ in stub.posts]
    assert "/agents" in paths
    assert any(p == "/agents/agent-123/sync" for p in paths)


def test_listen_status_reports_offline_with_no_state(isolated_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    stub = _StubClient()
    _install_stub_client(monkeypatch, stub)
    from deepvista_cli.main import cli

    runner = CliRunner()
    result = runner.invoke(cli, ["listen", "status"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["online"] is False


def test_listen_status_reports_online_when_daemon_pid_alive(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub = _StubClient()
    _install_stub_client(monkeypatch, stub)
    import deepvista_cli.commands.listen as listen_module

    listen_module._write_daemon_state(
        {"agent_id": "agent-xyz", "agent_role": "daemon", "pid": os.getpid(), "started_at": 0.0}
    )

    from deepvista_cli.main import cli

    runner = CliRunner()
    result = runner.invoke(cli, ["listen", "status"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["online"] is True
    assert payload["agent_id"] == "agent-xyz"
    assert payload["active_count"] == 0


def test_listen_stop_clears_state_when_process_already_gone(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub = _StubClient()
    _install_stub_client(monkeypatch, stub)
    import deepvista_cli.commands.listen as listen_module

    # PID 1 exists but we cannot SIGTERM it — instead, plant a clearly dead PID.
    listen_module._write_daemon_state(
        {"agent_id": "agent-xyz", "agent_role": "daemon", "pid": 999_999, "started_at": 0.0}
    )

    from deepvista_cli.main import cli

    runner = CliRunner()
    result = runner.invoke(cli, ["listen", "stop"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["stopped"] is True
    assert not listen_module.DAEMON_STATE_PATH.exists()


def test_listen_stop_sigterms_running_pid(isolated_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    stub = _StubClient()
    _install_stub_client(monkeypatch, stub)
    import deepvista_cli.commands.listen as listen_module

    sent: dict[str, Any] = {}

    def fake_kill(pid: int, sig: int) -> None:
        if sig == 0:
            # liveness probe — first call says alive, then dead
            if not sent.get("killed"):
                return
            raise ProcessLookupError
        if sig == signal.SIGTERM:
            sent["killed"] = True
            sent["pid"] = pid

    monkeypatch.setattr(listen_module.os, "kill", fake_kill)

    listen_module._write_daemon_state({"agent_id": "agent-xyz", "agent_role": "daemon", "pid": 4242, "started_at": 0.0})

    from deepvista_cli.main import cli

    runner = CliRunner()
    result = runner.invoke(cli, ["listen", "stop", "--timeout", "1"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["stopped"] is True
    assert sent["pid"] == 4242


def test_listen_stop_errors_when_no_daemon(isolated_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    stub = _StubClient()
    _install_stub_client(monkeypatch, stub)
    from deepvista_cli.main import cli

    runner = CliRunner()
    result = runner.invoke(cli, ["listen", "stop"])
    # output_error -> sys.exit(3)
    assert result.exit_code == 3


def test_materialise_dispatch_writes_skill_and_inputs(isolated_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import deepvista_cli.commands.listen as listen_module

    frame = {
        "run_id": "run-abc",
        "skill_markdown": "# my skill\n\nrun it",
        "inputs": {"x": 1, "y": "two"},
    }
    workspace, skill_path, inputs_path = listen_module._materialise_dispatch(frame)
    assert workspace.exists()
    assert skill_path.read_text() == "# my skill\n\nrun it"
    assert json.loads(inputs_path.read_text()) == {"x": 1, "y": "two"}
