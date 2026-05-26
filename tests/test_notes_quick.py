"""Tests for ``deepvista notes +quick`` input validation.

``+quick`` is only for single-line facts that fit in a 50-char title. Longer
or multi-sentence input must be rejected so callers reach for
``deepvista notes create --title ... --content ...`` instead of writing notes
with a title that's silently chopped to ``"first 50 chars..."``.
"""

from __future__ import annotations

from typing import Any

import click
import pytest
from click.testing import CliRunner

from deepvista_cli.commands import agents as agents_cmd
from deepvista_cli.commands import notes as notes_cmd


class _Recorder:
    def __init__(self) -> None:
        self.posts: list[tuple[str, dict[str, Any]]] = []

    def post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        self.posts.append((path, body))
        return {"card": {"id": "card-1", "title": body.get("title")}}


def _run(monkeypatch: pytest.MonkeyPatch, text: str) -> tuple[Any, _Recorder]:
    monkeypatch.setattr(notes_cmd, "detect_agent_tool", lambda: ("claude-code", "1.0"))
    monkeypatch.setattr(agents_cmd, "load_agent_id_for_active_agent", lambda: None)
    recorder = _Recorder()
    monkeypatch.setattr(notes_cmd, "_client", lambda ctx: recorder)

    class _Obj:
        output_format = "json"
        auth_url = "http://localhost"

    @click.group()
    @click.pass_context
    def root(ctx: click.Context) -> None:
        ctx.obj = _Obj()

    root.add_command(notes_cmd.notes_group)
    return CliRunner().invoke(root, ["notes", "+quick", text]), recorder


def test_quick_note_accepts_short_single_line(monkeypatch: pytest.MonkeyPatch) -> None:
    result, recorder = _run(monkeypatch, "shipped DV-831 fix")
    assert result.exit_code == 0, result.output
    assert recorder.posts, "expected a create_context_card POST"
    _, body = recorder.posts[0]
    assert body["title"] == "shipped DV-831 fix"
    assert body["description"] == "shipped DV-831 fix"


def test_quick_note_rejects_input_over_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    long_text = "x" * 51
    result, recorder = _run(monkeypatch, long_text)
    assert result.exit_code != 0
    assert "notes create" in result.output
    assert not recorder.posts, "must not POST when validation fails"


def test_quick_note_rejects_input_with_period(monkeypatch: pytest.MonkeyPatch) -> None:
    result, recorder = _run(monkeypatch, "first sentence. second sentence")
    assert result.exit_code != 0
    assert "notes create" in result.output
    assert not recorder.posts


def test_quick_note_rejects_multiline_input(monkeypatch: pytest.MonkeyPatch) -> None:
    result, recorder = _run(monkeypatch, "line one\nline two")
    assert result.exit_code != 0
    assert "notes create" in result.output
    assert not recorder.posts
