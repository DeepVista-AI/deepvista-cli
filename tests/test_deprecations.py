"""Deprecation notices for sugar/alias commands (DV tech-debt cleanup).

Several commands are pure syntactic sugar or historical aliases that hit the
exact same backend endpoints as a canonical command:

- ``vistabase``                     → alias of ``card``
- ``notes session-init|tick|finalize`` → forward to ``session …`` (DV-742)
- ``card +pin`` / ``card +archive`` → ``card update --status pinned|archived``
- ``card +similar``                 → ``card get`` + ``card +search``
- ``notes list|get|create|update|delete`` → ``card … --type note``

Each now prints a deprecation notice on **stderr** (so stdout stays clean JSON),
pointing at the replacement. ``card create`` also grew the agent tagging that
``notes create`` had, so the ``notes create`` → ``card create --type note``
migration is behaviour-preserving.
"""

from __future__ import annotations

from typing import Any

import click
import pytest
from click.testing import CliRunner

from deepvista_cli import session_note as sn
from deepvista_cli.client import origin as origin_mod
from deepvista_cli.commands import agents as agents_mod
from deepvista_cli.commands import card as card_cmd
from deepvista_cli.commands import notes as notes_cmd


class _Recorder:
    """Capture POST/DELETE bodies sent through the CLI's HTTP client."""

    def __init__(self) -> None:
        self.posts: list[tuple[str, dict[str, Any]]] = []
        self.deletes: list[tuple[str, dict[str, Any] | None]] = []

    def post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        self.posts.append((path, body))
        # A response shape broad enough for every command under test:
        #  - single-entity readers use id/title/snippet
        #  - list/search readers use `cards`
        #  - `_find_session_card` scans `cards` (empty → no match → create path)
        return {
            "card": {"id": "card-1", "title": body.get("title", "t")},
            "id": "card-1",
            "title": "t",
            "snippet": "s",
            "cards": [],
        }

    def delete(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self.deletes.append((path, params))
        return {"deleted": True}


class _Obj:
    output_format = "json"
    auth_url = "http://localhost"
    project_id = None


@pytest.fixture
def runner(monkeypatch: pytest.MonkeyPatch) -> tuple[CliRunner, click.Group, _Recorder]:
    """A CliRunner wired to a root group mirroring main.py's registration.

    Stubs the HTTP client and agent detection so no network or local agent
    cache is touched.
    """
    recorder = _Recorder()
    monkeypatch.setattr(card_cmd, "_client", lambda ctx: recorder)
    monkeypatch.setattr(notes_cmd, "_client", lambda ctx: recorder)

    monkeypatch.setattr(origin_mod, "detect_agent_tool", lambda: ("claude-code", "1.0"))
    monkeypatch.setattr(notes_cmd, "detect_agent_tool", lambda: ("claude-code", "1.0"))
    monkeypatch.setattr(agents_mod, "load_agent_id_for_active_agent", lambda: "abc-uuid")

    @click.group()
    @click.pass_context
    def root(ctx: click.Context) -> None:
        ctx.obj = _Obj()

    root.add_command(card_cmd.card_group)
    root.add_command(card_cmd.card_group, name="vistabase")
    root.add_command(notes_cmd.notes_group)
    return CliRunner(), root, recorder


# ---------------------------------------------------------------------------
# vistabase alias
# ---------------------------------------------------------------------------


def test_vistabase_alias_warns(runner: tuple[CliRunner, click.Group, _Recorder]) -> None:
    cli, root, recorder = runner
    result = cli.invoke(root, ["vistabase", "list"])
    assert result.exit_code == 0, result.output
    assert "deprecated" in result.stderr
    assert "vistabase" in result.stderr
    # Still functional — it hits the same endpoint as `card list`.
    assert recorder.posts[0][0] == "/get_context_cards"


def test_card_group_does_not_warn(runner: tuple[CliRunner, click.Group, _Recorder]) -> None:
    """The canonical `card` invocation must stay noise-free on stderr."""
    cli, root, _ = runner
    result = cli.invoke(root, ["card", "list"])
    assert result.exit_code == 0, result.output
    assert "deprecated" not in result.stderr


# ---------------------------------------------------------------------------
# card +pin / +archive / +similar
# ---------------------------------------------------------------------------


def test_card_pin_warns_and_updates_status(runner: tuple[CliRunner, click.Group, _Recorder]) -> None:
    cli, root, recorder = runner
    result = cli.invoke(root, ["card", "+pin", "card-1"])
    assert result.exit_code == 0, result.output
    assert "deprecated" in result.stderr
    path, body = recorder.posts[0]
    assert path == "/update_context_card"
    assert body["display_status"] == "pinned"


def test_card_archive_warns_and_updates_status(runner: tuple[CliRunner, click.Group, _Recorder]) -> None:
    cli, root, recorder = runner
    result = cli.invoke(root, ["card", "+archive", "card-1"])
    assert result.exit_code == 0, result.output
    assert "deprecated" in result.stderr
    path, body = recorder.posts[0]
    assert path == "/update_context_card"
    assert body["display_status"] == "archived"


def test_card_similar_warns(runner: tuple[CliRunner, click.Group, _Recorder]) -> None:
    cli, root, recorder = runner
    result = cli.invoke(root, ["card", "+similar", "card-1"])
    assert result.exit_code == 0, result.output
    assert "deprecated" in result.stderr
    # get (read the seed) then a search over its title/snippet.
    assert [p for p, _ in recorder.posts] == ["/get_context_card", "/get_context_cards"]


# ---------------------------------------------------------------------------
# notes CRUD → card --type note
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "argv",
    [
        ["notes", "list"],
        ["notes", "get", "card-1"],
        ["notes", "create", "--title", "t"],
        ["notes", "update", "card-1", "--title", "t"],
        ["notes", "delete", "card-1"],
    ],
    ids=["list", "get", "create", "update", "delete"],
)
def test_notes_crud_warns(runner: tuple[CliRunner, click.Group, _Recorder], argv: list[str]) -> None:
    cli, root, _ = runner
    result = cli.invoke(root, argv)
    assert result.exit_code == 0, result.output
    assert "deprecated" in result.stderr
    assert "card" in result.stderr


# ---------------------------------------------------------------------------
# notes session-* → session … (DV-742)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "argv",
    [
        ["notes", "session-init", "--session-id", "s1", "--transcript", "/tmp/t.jsonl", "--cwd", "/tmp/proj"],
        ["notes", "session-tick", "--session-id", "s1", "--transcript", "/tmp/t.jsonl"],
        ["notes", "session-finalize", "--session-id", "s1"],
    ],
    ids=["init", "tick", "finalize"],
)
def test_notes_session_aliases_warn(runner: tuple[CliRunner, click.Group, _Recorder], argv: list[str]) -> None:
    cli, root, _ = runner
    # The warning is emitted before the forward, so it lands on stderr
    # regardless of whether the (cache-less) inner command succeeds.
    result = cli.invoke(root, [*argv, "--dry-run"])
    assert "deprecated" in result.stderr
    assert "session" in result.stderr


# ---------------------------------------------------------------------------
# card create now applies agent tagging (parity with notes create)
# ---------------------------------------------------------------------------


def test_card_create_emits_agent_tag_when_registered(
    runner: tuple[CliRunner, click.Group, _Recorder],
) -> None:
    cli, root, recorder = runner
    result = cli.invoke(root, ["card", "create", "--type", "note", "--title", "t"])
    assert result.exit_code == 0, result.output
    path, body = recorder.posts[0]
    assert path == "/create_context_card"
    assert "agent:claude-code:abc-uuid" in (body.get("tags") or [])


def test_card_create_falls_back_to_bare_agent_tag(
    runner: tuple[CliRunner, click.Group, _Recorder], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(agents_mod, "load_agent_id_for_active_agent", lambda: None)
    cli, root, recorder = runner
    result = cli.invoke(root, ["card", "create", "--type", "note", "--title", "t"])
    assert result.exit_code == 0, result.output
    _, body = recorder.posts[0]
    tags = body.get("tags") or []
    assert f"{sn.AGENT_TAG_PREFIX}claude-code" in tags
    assert not any(t.startswith(sn.AGENT_ID_TAG_PREFIX) for t in tags)


def test_card_create_merges_user_tags_after_agent_tag(
    runner: tuple[CliRunner, click.Group, _Recorder],
) -> None:
    cli, root, recorder = runner
    result = cli.invoke(root, ["card", "create", "--type", "note", "--title", "t", "--tags", '["x","y"]'])
    assert result.exit_code == 0, result.output
    _, body = recorder.posts[0]
    tags = body.get("tags") or []
    assert tags[0] == "agent:claude-code:abc-uuid"
    assert "x" in tags and "y" in tags
