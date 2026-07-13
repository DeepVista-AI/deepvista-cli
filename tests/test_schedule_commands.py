"""Click-level tests for `deepvista schedule` (DV-1537).

Covers the bug fix: matching/identity must go through the stable ``kind``
attribute (mirroring the server's ``(user_id, kind)`` upsert), not a
hardcoded title string — and creation must go through the canonical
``POST /scheduled-jobs/activate`` endpoint instead of hand-rolling a
``POST /scheduled-jobs`` with a locally-built prompt/title.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

from deepvista_cli.main import cli

_JOB_KIND = "daily_planning"


class _StubCtxClient:
    """Minimal stand-in for the real client attached to ctx.obj._client."""

    def __init__(self) -> None:
        self.responses: dict[str, list[Any]] = {}
        self.calls: list[tuple[str, str, dict | None]] = []

    def queue(self, method: str, path: str, response: Any) -> None:
        self.responses.setdefault((method, path), []).append(response)  # type: ignore[arg-type]

    def _pop(self, method: str, path: str) -> Any:
        q = self.responses.get((method, path))  # type: ignore[arg-type]
        if not q:
            raise AssertionError(f"no response queued for {method} {path}")
        return q.pop(0)

    def get(self, path: str, params: dict | None = None, extra_headers: dict | None = None) -> Any:
        self.calls.append(("GET", path, None))
        return self._pop("GET", path)

    def post(self, path: str, body: dict | None = None, extra_headers: dict | None = None) -> Any:
        self.calls.append(("POST", path, body))
        return self._pop("POST", path)

    def patch(self, path: str, body: dict | None = None) -> Any:
        self.calls.append(("PATCH", path, body))
        return self._pop("PATCH", path)

    def delete(self, path: str, params: dict | None = None) -> Any:
        self.calls.append(("DELETE", path, None))
        return self._pop("DELETE", path)


@pytest.fixture()
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Redirect CLI state dirs into a pytest tmp dir."""
    monkeypatch.setenv("DEEPVISTA_CONFIG_DIR", str(tmp_path / ".config" / "deepvista"))
    import importlib

    import deepvista_cli.config as cfg_module

    importlib.reload(cfg_module)
    return tmp_path


def _install_stub_client(monkeypatch: pytest.MonkeyPatch, stub: _StubCtxClient) -> None:
    from deepvista_cli.client import http as http_module

    def fake_init(self, config):  # type: ignore[no-untyped-def]
        self.config = config

    monkeypatch.setattr(http_module.DeepVistaClient, "__init__", fake_init)
    monkeypatch.setattr(
        http_module.DeepVistaClient,
        "get",
        lambda self, path, params=None, extra_headers=None: stub.get(path, params, extra_headers),
    )
    monkeypatch.setattr(
        http_module.DeepVistaClient,
        "post",
        lambda self, path, body=None, extra_headers=None: stub.post(path, body, extra_headers),
    )
    monkeypatch.setattr(http_module.DeepVistaClient, "patch", lambda self, path, body=None: stub.patch(path, body))
    monkeypatch.setattr(
        http_module.DeepVistaClient, "delete", lambda self, path, params=None: stub.delete(path, params)
    )


def _job(**overrides: Any) -> dict:
    base = {
        "id": "job-1",
        "title": "Daily planning",
        "kind": _JOB_KIND,
        "prompt": "Run your `deepvista-daily-planning` skill...",
        "cron_schedule": "0 9 * * *",
        "enabled": True,
        "next_run_at": "2026-07-14T09:00:00+00:00",
        "last_run_at": None,
    }
    base.update(overrides)
    return base


def test_activate_creates_via_canonical_endpoint_when_none_exists(
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No existing job -> activate calls the canonical upsert, not POST /scheduled-jobs."""
    stub = _StubCtxClient()
    stub.queue("GET", "/scheduled-jobs", {"jobs": [], "credits": 100})
    stub.queue("POST", "/scheduled-jobs/activate", {"success": True, "job": _job()})
    _install_stub_client(monkeypatch, stub)

    result = CliRunner().invoke(cli, ["schedule", "activate"])
    assert result.exit_code == 0, result.output
    assert ("POST", "/scheduled-jobs/activate", {"kind": _JOB_KIND}) in stub.calls
    assert not any(path == "/scheduled-jobs" and method == "POST" for method, path, _ in stub.calls)
    assert '"status": "activated"' in result.output


def test_activate_matches_existing_job_by_kind_not_title(
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A row with a differently-cased/legacy title is still found via `kind` (the DV-1537 bug)."""
    stub = _StubCtxClient()
    existing = _job(title="Some Other Title", enabled=False)
    stub.queue("GET", "/scheduled-jobs", {"jobs": [existing], "credits": 100})
    stub.queue(
        "POST", "/scheduled-jobs/activate", {"success": True, "job": _job(title="Some Other Title", enabled=True)}
    )
    _install_stub_client(monkeypatch, stub)

    result = CliRunner().invoke(cli, ["schedule", "activate"])
    assert result.exit_code == 0, result.output
    assert '"status": "reactivated"' in result.output


def test_activate_already_active_short_circuits_without_network_call(
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub = _StubCtxClient()
    stub.queue("GET", "/scheduled-jobs", {"jobs": [_job(enabled=True)], "credits": 100})
    _install_stub_client(monkeypatch, stub)

    result = CliRunner().invoke(cli, ["schedule", "activate"])
    assert result.exit_code == 0, result.output
    assert '"status": "already_active"' in result.output
    assert not any(method == "POST" for method, _, _ in stub.calls)


def test_activate_with_cron_override_patches_after_activating(
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """--cron on an already-active job still applies (fixes the old silent-ignore quirk)."""
    stub = _StubCtxClient()
    stub.queue("GET", "/scheduled-jobs", {"jobs": [_job(enabled=True, cron_schedule="0 9 * * *")], "credits": 100})
    stub.queue(
        "POST", "/scheduled-jobs/activate", {"success": True, "job": _job(enabled=True, cron_schedule="0 9 * * *")}
    )
    stub.queue(
        "PATCH", "/scheduled-jobs/job-1", {"success": True, "job": _job(enabled=True, cron_schedule="30 14 * * *")}
    )
    _install_stub_client(monkeypatch, stub)

    result = CliRunner().invoke(cli, ["schedule", "activate", "--cron", "30 14 * * *"])
    assert result.exit_code == 0, result.output
    assert ("PATCH", "/scheduled-jobs/job-1", {"cron_schedule": "30 14 * * *"}) in stub.calls
    assert '"status": "updated"' in result.output
    assert '"cron_schedule": "30 14 * * *"' in result.output


def test_deactivate_matches_by_kind(
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub = _StubCtxClient()
    existing = _job(title="Legacy Title", enabled=True)
    stub.queue("GET", "/scheduled-jobs", {"jobs": [existing], "credits": 100})
    stub.queue("PATCH", "/scheduled-jobs/job-1", {"success": True, "job": _job(enabled=False)})
    _install_stub_client(monkeypatch, stub)

    result = CliRunner().invoke(cli, ["schedule", "deactivate"])
    assert result.exit_code == 0, result.output
    assert '"status": "deactivated"' in result.output


def test_delete_default_target_matches_by_kind(
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub = _StubCtxClient()
    existing = _job(title="Legacy Title", enabled=True)
    stub.queue("GET", "/scheduled-jobs", {"jobs": [existing], "credits": 100})
    stub.queue("DELETE", "/scheduled-jobs/job-1", {"success": True})
    _install_stub_client(monkeypatch, stub)

    result = CliRunner().invoke(cli, ["schedule", "delete"])
    assert result.exit_code == 0, result.output
    assert '"status": "deleted"' in result.output
