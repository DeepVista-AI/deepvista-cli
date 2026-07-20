"""Tests for `deepvista auth login` output — welcome copy (DV-1646) + JSON contract."""

from __future__ import annotations

import json
import types
from pathlib import Path

import pytest
from click.testing import CliRunner

import deepvista_cli.config as cfg
from deepvista_cli.main import cli


@pytest.fixture()
def isolated_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    config_dir = tmp_path / ".config" / "deepvista"
    monkeypatch.setattr(cfg, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(cfg, "PROFILES_PATH", config_dir / "config.json")
    monkeypatch.delenv("DEEPVISTA_PROJECT_ID", raising=False)
    return config_dir


def _patch_login(monkeypatch: pytest.MonkeyPatch) -> None:
    import deepvista_cli.commands.auth as auth_module

    tokens = types.SimpleNamespace(email="jing@deepvista.ai", user_id="u-1")
    monkeypatch.setattr(auth_module, "login_auto", lambda auth_url, creds_path: tokens)


def test_login_keeps_json_contract_and_prints_welcome(isolated_config: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_login(monkeypatch)

    result = CliRunner().invoke(cli, ["auth", "login"])
    assert result.exit_code == 0, result.output

    # Machine-readable contract on stdout is unchanged (status/email/user_id).
    json_start = result.output.index("{")
    decoder = json.JSONDecoder()
    payload, _ = decoder.raw_decode(result.output[json_start:])
    assert payload == {"status": "authenticated", "email": "jing@deepvista.ai", "user_id": "u-1"}

    # Human welcome: identity, next steps, and the getting-started prompt.
    assert "Logged in as jing@deepvista.ai" in result.output
    assert "What's next?" in result.output
    assert "deepvista project use" in result.output  # no working project set → pick one first
    assert "Help me get started with DeepVista." in result.output


def test_login_with_working_project_suggests_tasks_run(isolated_config: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_login(monkeypatch)
    cfg.set_working_project("default", "proj-1")

    result = CliRunner().invoke(cli, ["auth", "login"])
    assert result.exit_code == 0, result.output
    assert "deepvista tasks run" in result.output
    assert "deepvista project use" not in result.output
