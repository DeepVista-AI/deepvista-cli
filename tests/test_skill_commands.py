"""Click-level tests for `deepvista skill sync` / `skill load`."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

from deepvista_cli.main import cli


class _StubCtxClient:
    """Minimal stand-in for the real client attached to ctx.obj._client."""

    def __init__(self) -> None:
        self.responses: dict[str, list[Any]] = {}

    def queue(self, path: str, response: Any) -> None:
        self.responses.setdefault(path, []).append(response)

    def post(self, path: str, body: dict | None = None) -> Any:
        q = self.responses.get(path)
        if not q:
            raise AssertionError(f"no response queued for POST {path}")
        return q.pop(0)


@pytest.fixture()
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect CLI state dirs into a pytest tmp dir."""
    monkeypatch.setenv("DEEPVISTA_CONFIG_DIR", str(tmp_path / ".config" / "deepvista"))
    # Also point catalog defaults at tmp — skill_catalog reads CONFIG_DIR lazily.
    import importlib

    import deepvista_cli.config as cfg_module

    importlib.reload(cfg_module)
    import deepvista_cli.skill_catalog as cat_module

    importlib.reload(cat_module)
    return tmp_path


def _install_stub_client(monkeypatch: pytest.MonkeyPatch, stub: _StubCtxClient) -> None:
    """Swap the real DeepVistaClient for our stub on the CLI context."""

    def fake_init(self, config):  # type: ignore[no-untyped-def]
        # Copy the minimal interface tests need.
        self.config = config

    # Patch the real client's post / get / _auth_headers so any accidental call fails visibly.
    from deepvista_cli.client import http as http_module

    monkeypatch.setattr(http_module.DeepVistaClient, "__init__", fake_init)
    monkeypatch.setattr(
        http_module.DeepVistaClient,
        "post",
        lambda self, path, body=None: stub.post(path, body),
    )


def test_skill_sync_dry_run_prints_plan(
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub = _StubCtxClient()
    stub.queue(
        "/get_context_cards",
        {
            "cards": [
                {"id": "id-a", "title": "Alpha", "description": "A skill"},
                {"id": "id-b", "title": "Bravo", "description": "B skill"},
            ],
            "has_more": False,
        },
    )
    _install_stub_client(monkeypatch, stub)

    target = isolated_home / "skills"
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "skill",
            "sync",
            "--target",
            str(target),
            "--throttle-min",
            "0",
            "--dry-run",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["dry_run"] is True
    assert set(payload["plan"]["to_add"]) == {"Alpha", "Bravo"}
    # Dry run should not touch disk.
    assert not target.exists()


def test_skill_sync_writes_stubs_and_quiet_mode_is_silent(
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub = _StubCtxClient()
    stub.queue(
        "/get_context_cards",
        {"cards": [{"id": "id-a", "title": "Alpha", "description": "A"}], "has_more": False},
    )
    _install_stub_client(monkeypatch, stub)

    target = isolated_home / "skills"
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["skill", "sync", "--target", str(target), "--throttle-min", "0", "--quiet"],
    )
    assert result.exit_code == 0, result.output
    assert result.output.strip() == ""
    stub_md = target / "dv-alpha" / "SKILL.md"
    assert stub_md.exists()
    body = stub_md.read_text()
    assert "x-deepvista-id: id-a" in body
    assert "!`deepvista skill load id-a`" in body


def test_skill_load_prints_body_and_caches(
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub = _StubCtxClient()
    stub.queue(
        "/get_context_card",
        {"id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee", "title": "A", "content": "hi from server"},
    )
    _install_stub_client(monkeypatch, stub)

    skill_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    runner = CliRunner()
    first = runner.invoke(cli, ["skill", "load", skill_id])
    assert first.exit_code == 0, first.output
    assert "hi from server" in first.output

    # Second call uses cache — no second queued response needed.
    second = runner.invoke(cli, ["skill", "load", skill_id])
    assert second.exit_code == 0
    assert first.output == second.output


def test_skill_load_rejects_non_uuid(
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub = _StubCtxClient()  # empty queue — any call fails
    _install_stub_client(monkeypatch, stub)

    runner = CliRunner()
    result = runner.invoke(cli, ["skill", "load", "not-a-uuid"])
    # output_error calls sys.exit(EXIT_VALIDATION_ERROR=3)
    assert result.exit_code != 0
    assert "Invalid skill ID" in result.output or "Invalid skill ID" in (result.stderr or "")


def test_skill_sync_exits_zero_on_network_error(
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Hook-safety: sync must never fail the parent session."""
    from deepvista_cli.client import http as http_module

    def boom(self, path, body=None):
        raise RuntimeError("network down")

    def fake_init(self, config):  # type: ignore[no-untyped-def]
        self.config = config

    monkeypatch.setattr(http_module.DeepVistaClient, "__init__", fake_init)
    monkeypatch.setattr(http_module.DeepVistaClient, "post", boom)

    target = isolated_home / "skills"
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["skill", "sync", "--target", str(target), "--throttle-min", "0", "--quiet"],
    )
    assert result.exit_code == 0
