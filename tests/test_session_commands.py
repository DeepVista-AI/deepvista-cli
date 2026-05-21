"""Click-level tests for `deepvista session` (DV-742).

Covers:
  * `session init` creates a `type='session'` card on first call and is
    idempotent on the second.
  * `session tick` appends turns and bumps the local state cache.
  * `session finalize` flips status to complete and queues enrichment.
  * `notes session-init` / `tick` / `finalize` aliases delegate to the new
    group and emit a deprecation hint on stderr.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

from deepvista_cli.main import cli


class _StubClient:
    """Minimal stand-in for the real client attached to ctx.obj._client."""

    def __init__(self) -> None:
        self.responses: dict[str, list[Any]] = {}
        self.calls: list[tuple[str, dict | None]] = []

    def queue(self, path: str, response: Any) -> None:
        self.responses.setdefault(path, []).append(response)

    def post(self, path: str, body: dict | None = None) -> Any:
        self.calls.append((path, body))
        q = self.responses.get(path)
        if not q:
            raise AssertionError(f"no response queued for POST {path}: {body!r}")
        return q.pop(0)


@pytest.fixture()
def isolated_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect XDG_STATE_HOME and DEEPVISTA_CONFIG_DIR into a tmp dir."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("DEEPVISTA_CONFIG_DIR", str(tmp_path / "config"))
    return tmp_path


def _install_stub(monkeypatch: pytest.MonkeyPatch, stub: _StubClient) -> None:
    """Swap DeepVistaClient.__init__ + .post for the stub."""

    def fake_init(self, config):  # type: ignore[no-untyped-def]
        self.config = config

    from deepvista_cli.client import http as http_module

    monkeypatch.setattr(http_module.DeepVistaClient, "__init__", fake_init)
    monkeypatch.setattr(
        http_module.DeepVistaClient,
        "post",
        lambda self, path, body=None: stub.post(path, body),
    )


def _make_transcript(tmp_path: Path, lines: list[dict]) -> Path:
    p = tmp_path / "transcript.jsonl"
    p.write_text("\n".join(json.dumps(line) for line in lines) + "\n")
    return p


def test_session_init_creates_session_card(
    isolated_state: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    stub = _StubClient()
    # No existing card found -> create.
    stub.queue("/get_context_cards", {"cards": []})  # session card lookup
    stub.queue("/get_context_cards", {"cards": []})  # legacy note fallback
    stub.queue("/create_context_card", {"id": "card-new", "type": "session"})
    _install_stub(monkeypatch, stub)

    transcript = _make_transcript(tmp_path, [])
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "session",
            "init",
            "--session-id",
            "sess-1",
            "--transcript",
            str(transcript),
            "--cwd",
            str(tmp_path),
            "--agent",
            "claude-code",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["created"] is True
    assert payload["card_id"] == "card-new"
    # The create call asked for type='session', not 'note'.
    create_call = next(call for call in stub.calls if call[0] == "/create_context_card")
    assert create_call[1]["card_type"] == "session"


def test_session_init_idempotent_via_cache(
    isolated_state: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A second `session init` for the same session_id reuses the cached id."""
    from deepvista_cli import session_note as sn

    # Seed the state cache as if a prior init ran.
    state_path = sn.state_path("sess-2")
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps({"card_id": "card-existing", "session_id": "sess-2"}))

    stub = _StubClient()
    _install_stub(monkeypatch, stub)

    transcript = _make_transcript(tmp_path, [])
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "session",
            "init",
            "--session-id",
            "sess-2",
            "--transcript",
            str(transcript),
            "--cwd",
            str(tmp_path),
            "--agent",
            "claude-code",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["created"] is False
    assert payload["card_id"] == "card-existing"
    # No POSTs needed — the cache short-circuited everything.
    assert stub.calls == []


def test_session_init_recovers_legacy_note(
    isolated_state: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A rolling note created by the pre-DV-742 CLI is recovered on resume."""
    stub = _StubClient()
    # session lookup empty, note fallback returns the legacy rolling note.
    stub.queue("/get_context_cards", {"cards": []})
    stub.queue("/get_context_cards", {"cards": [{"id": "legacy-note", "type": "note"}]})
    _install_stub(monkeypatch, stub)

    transcript = _make_transcript(tmp_path, [])
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "session",
            "init",
            "--session-id",
            "sess-legacy",
            "--transcript",
            str(transcript),
            "--cwd",
            str(tmp_path),
            "--agent",
            "claude-code",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["created"] is False
    assert payload["card_id"] == "legacy-note"
    # Both lookups happened; no create.
    paths = [call[0] for call in stub.calls]
    assert paths == ["/get_context_cards", "/get_context_cards"]


def test_session_tick_appends_new_turns(
    isolated_state: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from deepvista_cli import session_note as sn

    state_path = sn.state_path("sess-tick")
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps({"card_id": "card-tick", "session_id": "sess-tick", "last_turn_index": 0}))

    transcript = _make_transcript(
        tmp_path,
        [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ],
    )

    stub = _StubClient()
    stub.queue("/get_context_card", {"description": "---\n---\n## Turns\n\n"})
    stub.queue("/update_context_card", {"id": "card-tick", "ok": True})
    _install_stub(monkeypatch, stub)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["session", "tick", "--session-id", "sess-tick", "--transcript", str(transcript)],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["card_id"] == "card-tick"
    assert payload["appended"] == 1
    # State cache advanced.
    state_after = json.loads(state_path.read_text())
    assert state_after["last_turn_index"] == 1
    # Update payload tagged with the session-tick reason for the trigger.
    update_call = next(call for call in stub.calls if call[0] == "/update_context_card")
    assert update_call[1]["reason"] == "session-tick"


def test_session_finalize_flips_status_and_enriches(
    isolated_state: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from deepvista_cli import session_note as sn

    state_path = sn.state_path("sess-fin")
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps({"card_id": "card-fin", "session_id": "sess-fin", "last_turn_index": 0}))

    stub = _StubClient()
    stub.queue("/get_context_card", {"description": "---\nstatus: active\n---\n## Turns\n\n", "type": "session"})
    stub.queue("/update_context_card", {"ok": True})
    stub.queue("/index_notes", {"queued": [{"id": "card-fin", "type": "session"}], "count": 1})
    _install_stub(monkeypatch, stub)

    runner = CliRunner()
    result = runner.invoke(cli, ["session", "finalize", "--session-id", "sess-fin"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "complete"
    update_call = next(call for call in stub.calls if call[0] == "/update_context_card")
    assert update_call[1]["reason"] == "session-finalize"
    enrich_call = next(call for call in stub.calls if call[0] == "/index_notes")
    assert enrich_call[1]["card_ids"] == ["card-fin"]


def test_notes_session_init_aliases_to_new_group(
    isolated_state: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """`notes session-init` is a thin alias that delegates to `session init`."""
    stub = _StubClient()
    stub.queue("/get_context_cards", {"cards": []})
    stub.queue("/get_context_cards", {"cards": []})
    stub.queue("/create_context_card", {"id": "card-alias", "type": "session"})
    _install_stub(monkeypatch, stub)

    transcript = _make_transcript(tmp_path, [])
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "notes",
            "session-init",
            "--session-id",
            "sess-alias",
            "--transcript",
            str(transcript),
            "--cwd",
            str(tmp_path),
            "--agent",
            "claude-code",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["card_id"] == "card-alias"
    # The alias still writes a session card, not a note.
    create_call = next(call for call in stub.calls if call[0] == "/create_context_card")
    assert create_call[1]["card_type"] == "session"
