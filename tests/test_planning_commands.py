"""Click-level tests for `deepvista planning` (DV-853).

Covers:

- ``planning daily-note`` — idempotency, --force, --dry-run, custom --roles
- ``planning today`` — returns the day's note and parses role sections
- ``planning append-summary`` — appends a timestamped summary block
- ``planning roles`` — lists role sections, excluding reserved ones
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

from deepvista_cli.commands.planning import _parse_role_sections, _seed_markdown
from deepvista_cli.main import cli


class _StubCtxClient:
    """In-memory client recording calls and replaying queued responses."""

    def __init__(self) -> None:
        self.responses: dict[str, list[Any]] = {}
        self.calls: list[tuple[str, dict | None]] = []

    def queue(self, path: str, response: Any) -> None:
        self.responses.setdefault(path, []).append(response)

    def post(self, path: str, body: dict | None = None) -> Any:
        self.calls.append((path, body))
        q = self.responses.get(path)
        if not q:
            raise AssertionError(f"no response queued for POST {path}")
        return q.pop(0)


@pytest.fixture()
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
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
        "post",
        lambda self, path, body=None: stub.post(path, body),
    )


# ---------------------------------------------------------------------------
# Pure helpers (no Click)
# ---------------------------------------------------------------------------


def test_seed_markdown_renders_one_section_per_role():
    md = _seed_markdown(("marketing", "engineering", "gtm"), "20260528")
    assert "# Daily Planning 20260528" in md
    assert "## marketing" in md
    assert "## engineering" in md
    assert "## gtm" in md
    # Reserved sections are seeded so they get parsed out by the section walker.
    assert "## Workflow today" in md
    assert "## Summary" in md


def test_parse_role_sections_excludes_reserved():
    md = (
        "# Daily Planning 20260528\n"
        "## Workflow today\n- workflow item\n\n"
        "## marketing\n- write a launch tweet\n\n"
        "## engineering\n- ship DV-853\n\n"
        "## Summary\n_pending_\n"
    )
    sections = _parse_role_sections(md)
    assert set(sections) == {"marketing", "engineering"}
    assert "launch tweet" in sections["marketing"]
    assert "DV-853" in sections["engineering"]


# ---------------------------------------------------------------------------
# planning daily-note
# ---------------------------------------------------------------------------


def test_daily_note_creates_when_absent(
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub = _StubCtxClient()
    # First call: look up existing planning notes — none for this date.
    stub.queue("/get_context_cards", {"cards": []})
    # Second call: create the note.
    stub.queue(
        "/create_context_card",
        {"id": "note-1", "title": "Daily Planning 20260528", "tags": []},
    )
    _install_stub_client(monkeypatch, stub)

    runner = CliRunner()
    result = runner.invoke(cli, ["planning", "daily-note", "--date", "20260528"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["created"] is True
    assert payload["date"] == "20260528"
    assert payload["roles"] == ["marketing", "engineering", "gtm"]
    assert payload["source"] == "template"
    # Verify the create payload carries the seeded sections.
    create_call = next(c for c in stub.calls if c[0] == "/create_context_card")
    body = create_call[1] or {}
    assert "## marketing" in body["description"]
    assert "daily-planning" in body["tags"]
    assert "date:20260528" in body["tags"]
    # Templated notes don't carry the agent-source tag — the slash command
    # uses this signal to decide whether to regenerate via the skill.
    assert "source:agent" not in body["tags"]


def test_daily_note_idempotent_when_present(
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A second call on the same day finds the existing note and returns it
    untouched — no POST to /create_context_card."""
    stub = _StubCtxClient()
    stub.queue(
        "/get_context_cards",
        {
            "cards": [
                {
                    "id": "existing",
                    "title": "Daily Planning 20260528",
                    "tags": ["daily-planning", "date:20260528"],
                    "description": "# Daily Planning 20260528\n",
                }
            ]
        },
    )
    _install_stub_client(monkeypatch, stub)

    runner = CliRunner()
    result = runner.invoke(cli, ["planning", "daily-note", "--date", "20260528"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["created"] is False
    assert payload["reason"] == "already_exists"
    # Crucially: no second POST. The lookup is the only call.
    assert [c[0] for c in stub.calls] == ["/get_context_cards"]


def test_daily_note_force_recreates(
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`--force` skips the lookup and posts a fresh create — useful for the
    /refresh-skills equivalent of planning."""
    stub = _StubCtxClient()
    stub.queue("/create_context_card", {"id": "note-fresh"})
    _install_stub_client(monkeypatch, stub)

    runner = CliRunner()
    result = runner.invoke(cli, ["planning", "daily-note", "--date", "20260528", "--force"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["created"] is True
    assert [c[0] for c in stub.calls] == ["/create_context_card"]


def test_daily_note_agent_content_bypasses_template(
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The `daily-planning` skill calls `daily-note --content-file -` with an
    LLM-reasoned plan; the templated seed must be bypassed and the note must
    be tagged ``source:agent`` so /deepvista run trusts it."""
    stub = _StubCtxClient()
    stub.queue("/get_context_cards", {"cards": []})
    stub.queue("/create_context_card", {"id": "note-agent"})
    _install_stub_client(monkeypatch, stub)

    agent_md = (
        "# Daily Planning 20260528\n\n"
        "Yesterday shipped DV-852; today we wrap DV-853 and prep DV-860.\n\n"
        "## Workflow today\n- /refresh-skills\n\n"
        "## marketing\n- Draft launch tweet for DV-853 (see card-001).\n"
    )
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["planning", "daily-note", "--date", "20260528", "--content", agent_md],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["created"] is True
    assert payload["source"] == "agent"
    create_call = next(c for c in stub.calls if c[0] == "/create_context_card")
    body = create_call[1] or {}
    # Body is the agent's markdown, not the boilerplate stub.
    assert "Yesterday shipped DV-852" in body["description"]
    assert "_Task brief for `@marketing`" not in body["description"]
    # Tag set tells /deepvista run not to regenerate.
    assert "source:agent" in body["tags"]
    assert "daily-planning" in body["tags"]


def test_today_reports_source_for_agent_and_template(
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`planning today` exposes the source label so the slash command can
    detect a stub and offer to regenerate via the daily-planning skill."""
    stub = _StubCtxClient()
    # First lookup: an agent-generated note.
    stub.queue(
        "/get_context_cards",
        {
            "cards": [
                {
                    "id": "note-1",
                    "title": "Daily Planning 20260528",
                    "tags": ["daily-planning", "date:20260528", "source:agent"],
                    "description": "# Daily Planning 20260528\n## marketing\n- ship\n",
                }
            ]
        },
    )
    # Second lookup: a templated stub.
    stub.queue(
        "/get_context_cards",
        {
            "cards": [
                {
                    "id": "note-2",
                    "title": "Daily Planning 20260529",
                    "tags": ["daily-planning", "date:20260529"],
                    "description": "# Daily Planning 20260529\n## marketing\n- stub\n",
                }
            ]
        },
    )
    _install_stub_client(monkeypatch, stub)

    runner = CliRunner()
    agent_result = runner.invoke(cli, ["planning", "today", "--date", "20260528"])
    assert agent_result.exit_code == 0, agent_result.output
    assert json.loads(agent_result.output)["source"] == "agent"

    template_result = runner.invoke(cli, ["planning", "today", "--date", "20260529"])
    assert template_result.exit_code == 0, template_result.output
    assert json.loads(template_result.output)["source"] == "template"


def test_daily_note_rejects_invalid_date(
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_stub_client(monkeypatch, _StubCtxClient())
    runner = CliRunner()
    result = runner.invoke(cli, ["planning", "daily-note", "--date", "2026-05-28"])
    # Non-YYYYMMDD is rejected before any network hit.
    assert result.exit_code != 0 or "Invalid --date" in result.output


def test_daily_note_dry_run_writes_nothing(
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub = _StubCtxClient()
    stub.queue("/get_context_cards", {"cards": []})
    _install_stub_client(monkeypatch, stub)

    runner = CliRunner()
    result = runner.invoke(cli, ["planning", "daily-note", "--date", "20260528", "--dry-run"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["dry_run"] is True
    # Only the lookup ran; no create call.
    assert all(c[0] != "/create_context_card" for c in stub.calls)


# ---------------------------------------------------------------------------
# planning today
# ---------------------------------------------------------------------------


def test_today_returns_sections(
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub = _StubCtxClient()
    md = _seed_markdown(("marketing", "engineering"), "20260528").replace(
        "_Task brief for `@marketing`",
        "- ship a launch tweet for DV-853",
    )
    stub.queue(
        "/get_context_cards",
        {
            "cards": [
                {
                    "id": "note-1",
                    "title": "Daily Planning 20260528",
                    "tags": ["daily-planning", "date:20260528"],
                    "description": md,
                }
            ]
        },
    )
    _install_stub_client(monkeypatch, stub)

    runner = CliRunner()
    result = runner.invoke(cli, ["planning", "today", "--date", "20260528"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["note_id"] == "note-1"
    assert set(payload["roles"]) == {"marketing", "engineering"}
    assert "DV-853" in payload["sections"]["marketing"]


def test_today_errors_when_no_note(
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub = _StubCtxClient()
    stub.queue("/get_context_cards", {"cards": []})
    _install_stub_client(monkeypatch, stub)

    runner = CliRunner()
    result = runner.invoke(cli, ["planning", "today", "--date", "20260528"])
    # Non-zero exit so a slash command / shell pipeline can react.
    assert result.exit_code != 0 or "No planning note" in result.output


# ---------------------------------------------------------------------------
# planning append-summary
# ---------------------------------------------------------------------------


def test_append_summary_writes_block(
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub = _StubCtxClient()
    stub.queue(
        "/get_context_card",
        {"card": {"id": "note-1", "description": "# Daily Planning 20260528\n\n## marketing\n- todo\n"}},
    )
    stub.queue("/update_context_card", {"id": "note-1"})
    _install_stub_client(monkeypatch, stub)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["planning", "append-summary", "--note-id", "note-1", "--summary", "### @marketing\nDone."],
    )
    assert result.exit_code == 0, result.output
    update_call = next(c for c in stub.calls if c[0] == "/update_context_card")
    body = update_call[1] or {}
    assert "## Summary —" in body["description"]
    assert "Done." in body["description"]
    assert body["description"].count("# Daily Planning 20260528") == 1


def test_append_summary_rejects_empty(
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_stub_client(monkeypatch, _StubCtxClient())
    runner = CliRunner()
    result = runner.invoke(cli, ["planning", "append-summary", "--note-id", "note-1", "--summary", "   "])
    assert "Missing summary" in result.output


# ---------------------------------------------------------------------------
# planning roles
# ---------------------------------------------------------------------------


def test_roles_lists_role_sections_only(
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub = _StubCtxClient()
    stub.queue(
        "/get_context_cards",
        {
            "cards": [
                {
                    "id": "note-1",
                    "title": "Daily Planning 20260528",
                    "tags": ["daily-planning", "date:20260528"],
                    "description": (
                        "# Daily Planning 20260528\n## Workflow today\n- x\n## marketing\n- y\n## Summary\n"
                    ),
                }
            ]
        },
    )
    _install_stub_client(monkeypatch, stub)

    runner = CliRunner()
    result = runner.invoke(cli, ["planning", "roles", "--date", "20260528"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["roles"] == ["marketing"]
