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


# ---------------------------------------------------------------------------
# skill preflight — DV-869
# ---------------------------------------------------------------------------

_PREFLIGHT_SKILL_ID = "11111111-2222-3333-4444-555555555555"

# A workflow body with two accordion phases:
#  - Phase 1: server-only tool_plan + done_when contract + a placeholder input
#  - Phase 2: a host tool (run_command) + an imperative cue, no done_when
_PREFLIGHT_BODY = """\
<accordion checked="false" open="true">
Phase 1: Gather context

Look up the topic <topic name> in the knowledge base.

```yaml
tool_plan:
  - grep_context_cards: "search"
  - read_context_card: "read"
done_when: "a context summary card is written"
```
</accordion>

<accordion checked="false" open="false">
Phase 2: Build it

Ask the user for the target directory, then scaffold.

```yaml
tool_plan:
  - run_command: "shell"
```
</accordion>
"""


def test_skill_preflight_emits_summary_header_and_body(
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub = _StubCtxClient()
    stub.queue(
        "/get_context_card",
        {
            "id": _PREFLIGHT_SKILL_ID,
            "title": "Demo Workflow",
            "status": "queued",
            "description": _PREFLIGHT_BODY,
        },
    )
    _install_stub_client(monkeypatch, stub)

    runner = CliRunner()
    result = runner.invoke(cli, ["skill", "preflight", _PREFLIGHT_SKILL_ID])
    assert result.exit_code == 0, result.output

    header_line = result.output.splitlines()[0]
    header = json.loads(header_line)
    assert header["type"] == "preflight_summary"
    assert header["skill_id"] == _PREFLIGHT_SKILL_ID
    assert header["needs_local_agent"] is True
    assert len(header["phases"]) == 2

    # All three sections present in the human-readable body.
    assert "Likely inputs (heuristic):" in result.output
    assert "Likely permissions:" in result.output
    assert "Expected output:" in result.output

    # Read-only: no write endpoint was hit.
    assert "/update_context_card" not in stub.responses
    assert stub.responses.get("/workflow_phase") is None


def test_skill_preflight_rejects_non_uuid(
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub = _StubCtxClient()  # empty queue — any API call fails loudly
    _install_stub_client(monkeypatch, stub)

    runner = CliRunner()
    result = runner.invoke(cli, ["skill", "preflight", "not-a-uuid"])
    assert result.exit_code == 3
    assert "Invalid skill ID" in result.output or "Invalid skill ID" in (result.stderr or "")


# ---------------------------------------------------------------------------
# WorkflowDocument.analyze_preflight — unit tests
# ---------------------------------------------------------------------------


def test_analyze_preflight_server_only_phase_needs_no_local_perms() -> None:
    from deepvista_cli.workflow_doc import PERMISSION_SERVER, WorkflowDocument

    report = WorkflowDocument(_PREFLIGHT_BODY).analyze_preflight()
    phase1 = report.phases[0]
    assert phase1.runs_on_deepvista is True
    assert phase1.permission == PERMISSION_SERVER


def test_analyze_preflight_run_command_phase_needs_local_agent() -> None:
    from deepvista_cli.workflow_doc import PERMISSION_LOCAL, WorkflowDocument

    report = WorkflowDocument(_PREFLIGHT_BODY).analyze_preflight()
    phase2 = report.phases[1]
    assert phase2.runs_on_deepvista is False
    assert phase2.permission == PERMISSION_LOCAL


def test_analyze_preflight_detects_placeholder_and_cue_inputs() -> None:
    from deepvista_cli.workflow_doc import WorkflowDocument

    report = WorkflowDocument(_PREFLIGHT_BODY).analyze_preflight()
    # Phase 1 angle-bracket placeholder.
    assert any("<topic name>" in i for i in report.phases[0].inputs)
    # Phase 2 imperative cue.
    assert any(i.lower().startswith("ask the user") for i in report.phases[1].inputs)


def test_analyze_preflight_uses_done_when_then_title_fallback() -> None:
    from deepvista_cli.workflow_doc import WorkflowDocument

    report = WorkflowDocument(_PREFLIGHT_BODY).analyze_preflight()
    # Phase 1 has a done_when contract.
    assert report.phases[0].expected_output == "a context summary card is written"
    # Phase 2 has none → falls back to the phase title.
    assert report.phases[1].expected_output == "Phase 2: Build it"


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
