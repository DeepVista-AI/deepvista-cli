"""Click-level tests for `deepvista agents sync` / `agents register` — DV-751."""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

from deepvista_cli.main import cli


class _StubCtxClient:
    """Minimal stand-in for the real client attached to ctx.obj._client.

    Queues are FIFO, keyed by ``(method, path)`` so the same path can return
    different shapes across calls (e.g. first sync fails AGENT_NOT_FOUND, the
    retry succeeds).
    """

    def __init__(self) -> None:
        self.responses: dict[tuple[str, str], list[Any]] = {}
        self.calls: list[tuple[str, str, dict | None]] = []

    def queue(self, method: str, path: str, response: Any) -> None:
        self.responses.setdefault((method, path), []).append(response)

    def _pop(self, method: str, path: str, body: dict | None) -> Any:
        self.calls.append((method, path, body))
        q = self.responses.get((method, path))
        if not q:
            raise AssertionError(f"no response queued for {method} {path}")
        return q.pop(0)

    def post(self, path: str, body: dict | None = None) -> Any:
        return self._pop("POST", path, body)

    def get(self, path: str, params: dict | None = None) -> Any:
        return self._pop("GET", path, params)


@pytest.fixture()
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect CLI state dirs and the hook installer into a pytest tmp dir."""
    monkeypatch.setenv("DEEPVISTA_CONFIG_DIR", str(tmp_path / ".config" / "deepvista"))

    import deepvista_cli.config as cfg_module

    importlib.reload(cfg_module)
    # agents module caches CONFIG_DIR at import time — reload it too so the
    # tmp-dir DEEPVISTA_CONFIG_DIR takes effect.
    import deepvista_cli.commands.agents as agents_module

    importlib.reload(agents_module)

    # Hooks would write to ~/.claude/settings.json — neuter them.
    monkeypatch.setattr(agents_module, "_install_hooks", lambda agent_type, profile: False)
    # _build_config_snapshot scans the user's environment (skills dirs, git,
    # MCP config, etc.) — return a deterministic payload so tests don't drift
    # with the host machine.
    monkeypatch.setattr(
        agents_module,
        "_build_config_snapshot",
        lambda agent_type: {"machine_fingerprint": "fp-test", "agent_type": agent_type},
    )
    return tmp_path


def _install_stub_client(monkeypatch: pytest.MonkeyPatch, stub: _StubCtxClient) -> None:
    """Swap the real DeepVistaClient for the stub on the CLI context."""
    from deepvista_cli.client import http as http_module

    def fake_init(self, config):  # type: ignore[no-untyped-def]
        self.config = config

    monkeypatch.setattr(http_module.DeepVistaClient, "__init__", fake_init)
    monkeypatch.setattr(
        http_module.DeepVistaClient,
        "post",
        lambda self, path, body=None: stub.post(path, body),
    )
    monkeypatch.setattr(
        http_module.DeepVistaClient,
        "get",
        lambda self, path, params=None: stub.get(path, params),
    )


def _agent_row(agent_id: str = "agent-1", agent_type: str = "claude-code") -> dict:
    return {
        "id": agent_id,
        "user_id": "user-1",
        "agent_type": agent_type,
        "name": f"{agent_type} stub",
        "status": "online",
    }


def test_agents_sync_auto_registers_when_no_local_file(
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """First-ever Stop hook on a fresh login: sync registers, then heartbeats."""
    stub = _StubCtxClient()
    stub.queue("POST", "/agents", {"success": True, "agent": _agent_row()})
    stub.queue("POST", "/agents/agent-1/sync", {"success": True, "agent": _agent_row()})
    _install_stub_client(monkeypatch, stub)

    runner = CliRunner()
    result = runner.invoke(cli, ["agents", "sync", "--type", "claude-code", "--status", "online"])

    assert result.exit_code == 0, result.output
    assert [c[:2] for c in stub.calls] == [("POST", "/agents"), ("POST", "/agents/agent-1/sync")]

    # The new local agent file should be created with the registered ID.
    import deepvista_cli.commands.agents as agents_module

    saved = agents_module._load_agent_id("claude-code")
    assert saved == "agent-1"


def test_agents_sync_adopts_existing_server_agent(
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No local file but the row already exists on the backend — adopt and sync."""
    existing = _agent_row(agent_id="agent-existing")
    stub = _StubCtxClient()
    stub.queue(
        "POST",
        "/agents",
        {
            "success": False,
            "error": "Agent of type 'claude-code' already registered on this machine",
            "error_code": "AGENT_ALREADY_REGISTERED",
            "agent": existing,
        },
    )
    stub.queue("POST", "/agents/agent-existing/sync", {"success": True, "agent": existing})
    _install_stub_client(monkeypatch, stub)

    runner = CliRunner()
    result = runner.invoke(cli, ["agents", "sync", "--type", "claude-code", "--status", "online"])

    assert result.exit_code == 0, result.output

    import deepvista_cli.commands.agents as agents_module

    assert agents_module._load_agent_id("claude-code") == "agent-existing"


def test_agents_sync_recovers_from_backend_agent_not_found(
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stale local agent_id triggers re-register + retry, transparently."""
    import deepvista_cli.commands.agents as agents_module

    # Pre-seed a stale local agent_id that the backend will reject.
    agents_module._save_agent_id("claude-code", "stale-agent")

    stub = _StubCtxClient()
    # First sync attempt: backend returns AGENT_NOT_FOUND.
    stub.queue(
        "POST",
        "/agents/stale-agent/sync",
        {"success": False, "error": "Agent not found", "error_code": "AGENT_NOT_FOUND"},
    )
    # Recovery path: re-register, then retry sync against the new ID.
    stub.queue("POST", "/agents", {"success": True, "agent": _agent_row(agent_id="agent-new")})
    stub.queue("POST", "/agents/agent-new/sync", {"success": True, "agent": _agent_row(agent_id="agent-new")})
    _install_stub_client(monkeypatch, stub)

    runner = CliRunner()
    result = runner.invoke(cli, ["agents", "sync", "--type", "claude-code", "--status", "online"])

    assert result.exit_code == 0, result.output
    assert [c[:2] for c in stub.calls] == [
        ("POST", "/agents/stale-agent/sync"),
        ("POST", "/agents"),
        ("POST", "/agents/agent-new/sync"),
    ]
    assert agents_module._load_agent_id("claude-code") == "agent-new"


def test_agents_sync_uses_existing_local_agent_id_on_happy_path(
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When a local agent_id resolves and the backend accepts it, no extra calls."""
    import deepvista_cli.commands.agents as agents_module

    agents_module._save_agent_id("claude-code", "agent-1")

    stub = _StubCtxClient()
    stub.queue("POST", "/agents/agent-1/sync", {"success": True, "agent": _agent_row()})
    _install_stub_client(monkeypatch, stub)

    runner = CliRunner()
    result = runner.invoke(cli, ["agents", "sync", "--type", "claude-code", "--status", "online"])

    assert result.exit_code == 0, result.output
    assert [c[:2] for c in stub.calls] == [("POST", "/agents/agent-1/sync")]


def test_agents_register_adopts_existing_when_local_missing(
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Explicit register against an already-registered server row should adopt, not fail."""
    existing = _agent_row(agent_id="agent-existing")
    stub = _StubCtxClient()
    stub.queue(
        "POST",
        "/agents",
        {
            "success": False,
            "error": "Agent of type 'claude-code' already registered on this machine",
            "error_code": "AGENT_ALREADY_REGISTERED",
            "agent": existing,
        },
    )
    # agents_register fires an initial sync + refetch after saving locally.
    stub.queue("POST", "/agents/agent-existing/sync", {"success": True, "agent": existing})
    stub.queue("GET", "/agents/agent-existing", {"agent": existing})
    _install_stub_client(monkeypatch, stub)

    runner = CliRunner()
    result = runner.invoke(cli, ["agents", "register", "--name", "Test", "--type", "claude-code"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload.get("id") == "agent-existing"

    import deepvista_cli.commands.agents as agents_module

    assert agents_module._load_agent_id("claude-code") == "agent-existing"
