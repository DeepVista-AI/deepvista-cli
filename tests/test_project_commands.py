"""Tests for project scoping (DV-1294):

- X-Project-Id header injection in the HTTP client
- working-project config persistence + resolution order
- project-prefixed web-link generation
- the `deepvista project` command group + `--project` override
"""

from __future__ import annotations

import json
import types
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

import deepvista_cli.config as cfg
from deepvista_cli.client.http import DeepVistaClient
from deepvista_cli.config import CLIConfig
from deepvista_cli.main import cli
from deepvista_cli.output.formatter import add_urls_to_data, generate_url

# ---------------------------------------------------------------------------
# Fixtures / stubs
# ---------------------------------------------------------------------------


@pytest.fixture()
def isolated_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the (already-imported) config module at a temp dir.

    Functions in ``deepvista_cli.config`` reference ``CONFIG_DIR`` /
    ``PROFILES_PATH`` as module globals at call time, so patching the attributes
    redirects reads and writes without reloading the module (which would
    desync the class ``main.cli`` already imported).
    """
    config_dir = tmp_path / ".config" / "deepvista"
    monkeypatch.setattr(cfg, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(cfg, "PROFILES_PATH", config_dir / "config.json")
    monkeypatch.delenv("DEEPVISTA_PROJECT_ID", raising=False)
    return config_dir


class _StubCtxClient:
    """Minimal stand-in for the real client attached to ctx.obj._client."""

    def __init__(self) -> None:
        self.responses: dict[str, list[Any]] = {}
        # Records (method, path, resolved project_id) so tests can assert the
        # working project that *would* have been sent as X-Project-Id.
        self.calls: list[tuple[str, str, str | None]] = []

    def queue(self, path: str, response: Any) -> None:
        self.responses.setdefault(path, []).append(response)

    def _pop(self, path: str) -> Any:
        q = self.responses.get(path)
        if not q:
            raise AssertionError(f"no response queued for {path}")
        return q.pop(0)


def _install_stub_client(monkeypatch: pytest.MonkeyPatch, stub: _StubCtxClient) -> None:
    """Swap the real client's __init__/get/post so tests can drive responses
    and observe the resolved project id (``self.config.project_id``)."""

    def fake_init(self, config):  # type: ignore[no-untyped-def]
        self.config = config

    def fake_get(self, path, params=None, extra_headers=None):  # type: ignore[no-untyped-def]
        stub.calls.append(("GET", path, self.config.project_id))
        return stub._pop(path)

    def fake_post(self, path, body=None, extra_headers=None):  # type: ignore[no-untyped-def]
        stub.calls.append(("POST", path, self.config.project_id))
        return stub._pop(path)

    monkeypatch.setattr(DeepVistaClient, "__init__", fake_init)
    monkeypatch.setattr(DeepVistaClient, "get", fake_get)
    monkeypatch.setattr(DeepVistaClient, "post", fake_post)


# ---------------------------------------------------------------------------
# 1. X-Project-Id header injection
# ---------------------------------------------------------------------------


def _patch_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    import deepvista_cli.client.http as http_mod
    import deepvista_cli.client.origin as origin_mod

    monkeypatch.setattr(http_mod, "get_valid_token", lambda _path: types.SimpleNamespace(access_token="tok-123"))
    monkeypatch.setattr(origin_mod, "build_origin", lambda: {})


def test_auth_headers_include_project_id_when_set(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_auth(monkeypatch)
    client = DeepVistaClient(CLIConfig(project_id="proj-1"))
    headers = client._auth_headers()
    assert headers["X-Project-Id"] == "proj-1"
    assert headers["Authorization"] == "Bearer tok-123"


def test_auth_headers_omit_project_id_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_auth(monkeypatch)
    client = DeepVistaClient(CLIConfig(project_id=None))
    headers = client._auth_headers()
    assert "X-Project-Id" not in headers


# ---------------------------------------------------------------------------
# 2. Config persistence + resolution order
# ---------------------------------------------------------------------------


def test_set_and_clear_working_project_preserves_other_keys(isolated_config: Path) -> None:
    cfg.set_profile("default", {"api_url": "https://api.example.com"})
    cfg.set_working_project("default", "proj-abc")

    profile = cfg.get_profile("default")
    assert profile["project_id"] == "proj-abc"
    assert profile["api_url"] == "https://api.example.com"  # untouched

    assert cfg.clear_working_project("default") is True
    profile = cfg.get_profile("default")
    assert "project_id" not in profile
    assert profile["api_url"] == "https://api.example.com"
    # Clearing again is a no-op.
    assert cfg.clear_working_project("default") is False


def test_apply_profile_resolves_project_id(isolated_config: Path) -> None:
    cfg.set_working_project("default", "proj-from-profile")
    config = CLIConfig(profile="default")
    config.apply_profile("default")
    assert config.project_id == "proj-from-profile"


def test_env_var_overrides_profile(isolated_config: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg.set_working_project("default", "proj-from-profile")
    monkeypatch.setenv("DEEPVISTA_PROJECT_ID", "proj-from-env")
    config = CLIConfig(profile="default")
    config.apply_profile("default")
    assert config.project_id == "proj-from-env"


# ---------------------------------------------------------------------------
# 3. Project-prefixed web links
# ---------------------------------------------------------------------------


def test_generate_url_with_project_prefix() -> None:
    url = generate_url("card-1", "card", "https://app.deepvista.ai", project_id="proj-9")
    assert url == "https://app.deepvista.ai/project/proj-9/vistabase/card-1"


def test_generate_url_without_project_prefix() -> None:
    url = generate_url("card-1", "card", "https://app.deepvista.ai")
    assert url == "https://app.deepvista.ai/vistabase/card-1"


def test_format_output_links_are_project_scoped() -> None:
    data = {"cards": [{"id": "c1", "type": "note"}]}
    out = add_urls_to_data(data, entity_type="card", base_url="https://app.deepvista.ai", project_id="p1")
    assert out["cards"][0]["url"] == "https://app.deepvista.ai/project/p1/notes/c1"


# ---------------------------------------------------------------------------
# 4. `deepvista project` command group
# ---------------------------------------------------------------------------


def test_project_list_returns_projects(isolated_config: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    stub = _StubCtxClient()
    stub.queue("/projects", [{"id": "p1", "name": "Alpha", "role": "owner"}])
    _install_stub_client(monkeypatch, stub)

    result = CliRunner().invoke(cli, ["project", "list"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["count"] == 1
    assert payload["projects"][0]["id"] == "p1"
    # project links point at /project/{id}, not /vistabase/{id}.
    assert payload["projects"][0]["url"].endswith("/project/p1")


def test_project_list_slims_output_and_derives_role(isolated_config: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    stub = _StubCtxClient()
    stub.queue(
        "/projects",
        [
            {"id": "p1", "name": "Owned", "tags": ["a", "b"], "conversation_starters": [{}], "is_shared": False},
            {"id": "p2", "name": "Shared", "permission": "editor", "is_shared": True},
        ],
    )
    _install_stub_client(monkeypatch, stub)

    result = CliRunner().invoke(cli, ["project", "list"])
    assert result.exit_code == 0, result.output
    projects = json.loads(result.output)["projects"]
    # The noisy fat-model fields are dropped by default.
    assert "tags" not in projects[0]
    assert "conversation_starters" not in projects[0]
    # Role is derived: owner when not shared, the explicit permission when shared.
    assert projects[0]["role"] == "owner"
    assert projects[1]["role"] == "editor"


def test_project_list_full_keeps_raw_fields(isolated_config: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    stub = _StubCtxClient()
    stub.queue("/projects", [{"id": "p1", "name": "Owned", "tags": ["a", "b"]}])
    _install_stub_client(monkeypatch, stub)

    result = CliRunner().invoke(cli, ["project", "list", "--full"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["projects"][0]["tags"] == ["a", "b"]


def test_project_use_persists_and_validates(isolated_config: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    stub = _StubCtxClient()
    stub.queue("/projects", [{"id": "p1", "name": "Alpha"}, {"id": "p2", "name": "Beta"}])
    _install_stub_client(monkeypatch, stub)

    result = CliRunner().invoke(cli, ["project", "use", "p2"])
    assert result.exit_code == 0, result.output
    assert cfg.get_profile("default")["project_id"] == "p2"


def test_project_use_accepts_slug_and_persists_uuid(isolated_config: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`project use <slug>` resolves to the canonical UUID before persisting (DV-1564)."""
    uuid = "11111111-1111-4111-8111-111111111111"
    stub = _StubCtxClient()
    stub.queue("/projects", [{"id": uuid, "slug": "alpha", "name": "Alpha"}])
    _install_stub_client(monkeypatch, stub)

    result = CliRunner().invoke(cli, ["project", "use", "alpha"])
    assert result.exit_code == 0, result.output
    assert cfg.get_profile("default")["project_id"] == uuid
    payload = json.loads(result.output)
    assert payload["working_project"] == uuid
    assert payload["slug"] == "alpha"


def test_project_list_surfaces_slug(isolated_config: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    stub = _StubCtxClient()
    stub.queue("/projects", [{"id": "p1", "slug": "alpha", "name": "Alpha"}])
    _install_stub_client(monkeypatch, stub)

    result = CliRunner().invoke(cli, ["project", "list"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["projects"][0]["slug"] == "alpha"


def test_project_use_rejects_inaccessible_id(isolated_config: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    stub = _StubCtxClient()
    stub.queue("/projects", [{"id": "p1", "name": "Alpha"}])
    _install_stub_client(monkeypatch, stub)

    result = CliRunner().invoke(cli, ["project", "use", "nope"])
    assert result.exit_code == cfg.EXIT_VALIDATION_ERROR
    assert "project_id" not in cfg.get_profile("default")


def test_project_current_hits_projects_me(isolated_config: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    stub = _StubCtxClient()
    stub.queue("/projects/me", {"id": "p1", "name": "Alpha"})
    _install_stub_client(monkeypatch, stub)

    result = CliRunner().invoke(cli, ["project", "current"])
    assert result.exit_code == 0, result.output
    assert stub.calls == [("GET", "/projects/me", None)]


def test_project_clear_unsets_working_project(isolated_config: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg.set_working_project("default", "p1")
    stub = _StubCtxClient()
    _install_stub_client(monkeypatch, stub)

    result = CliRunner().invoke(cli, ["project", "clear"])
    assert result.exit_code == 0, result.output
    assert "project_id" not in cfg.get_profile("default")


# ---------------------------------------------------------------------------
# 5. --project resolution order through a real command
# ---------------------------------------------------------------------------


def _run_card_list(monkeypatch: pytest.MonkeyPatch, argv: list[str]) -> tuple[Any, _StubCtxClient]:
    stub = _StubCtxClient()
    stub.queue("/get_context_cards", {"cards": [], "has_more": False})
    _install_stub_client(monkeypatch, stub)
    result = CliRunner().invoke(cli, argv)
    return result, stub


def test_profile_working_project_scopes_commands(isolated_config: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg.set_working_project("default", "proj-profile")
    result, stub = _run_card_list(monkeypatch, ["card", "list"])
    assert result.exit_code == 0, result.output
    assert stub.calls[0] == ("POST", "/get_context_cards", "proj-profile")


def test_global_project_flag_overrides_profile(isolated_config: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg.set_working_project("default", "proj-profile")
    result, stub = _run_card_list(monkeypatch, ["--project", "proj-flag", "card", "list"])
    assert result.exit_code == 0, result.output
    assert stub.calls[0] == ("POST", "/get_context_cards", "proj-flag")


def test_per_command_project_override(isolated_config: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg.set_working_project("default", "proj-profile")
    result, stub = _run_card_list(monkeypatch, ["card", "list", "--project", "proj-cmd"])
    assert result.exit_code == 0, result.output
    assert stub.calls[0] == ("POST", "/get_context_cards", "proj-cmd")


def test_env_var_scopes_commands(isolated_config: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEEPVISTA_PROJECT_ID", "proj-env")
    result, stub = _run_card_list(monkeypatch, ["card", "list"])
    assert result.exit_code == 0, result.output
    assert stub.calls[0] == ("POST", "/get_context_cards", "proj-env")
