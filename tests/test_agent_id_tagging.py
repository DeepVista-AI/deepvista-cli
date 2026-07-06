"""Tests for DV-791: write `agent_id` tag + frontmatter on note/session create.

The CLI tags every note/session write with both ``agent:<name>`` and (when the
local agent cache has a UUID for the active agent) ``agent_id:<uuid>``. The
session card additionally carries ``agent_id`` in its frontmatter and the
``X-DeepVista-Origin`` HTTP header echoes the UUID so the backend can echo the
tag on server-side card creation.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from deepvista_cli import session_note as sn

# ---------------------------------------------------------------------------
# session_note.py — frontmatter + tags round-trip
# ---------------------------------------------------------------------------


def test_seed_frontmatter_includes_agent_id_when_provided() -> None:
    fm = sn.seed_frontmatter(
        session_id="sess-1",
        cwd="/tmp/proj",
        transcript="/tmp/t.jsonl",
        agent="claude-code",
        agent_version="1.2.3",
        agent_id="11111111-2222-3333-4444-555555555555",
    )
    assert fm["agent"] == "claude-code"
    assert fm["agent_id"] == "11111111-2222-3333-4444-555555555555"
    assert fm["agent_version"] == "1.2.3"


def test_seed_frontmatter_omits_agent_id_when_unknown() -> None:
    fm = sn.seed_frontmatter(
        session_id="sess-1",
        cwd="/tmp/proj",
        transcript="/tmp/t.jsonl",
        agent="claude-code",
    )
    assert "agent_id" not in fm


def test_frontmatter_serialize_then_parse_round_trips_agent_id() -> None:
    fm = {
        "agent": "claude-code",
        "agent_id": "abc-uuid",
        "cc_session_id": "sess-1",
        "turn_count": 0,
        "status": "active",
    }
    serialized = sn.serialize_frontmatter(fm, "## Turns\n\n")
    parsed, rest = sn.parse_frontmatter(serialized)
    assert parsed["agent"] == "claude-code"
    assert parsed["agent_id"] == "abc-uuid"
    assert "## Turns" in rest


def test_serialize_frontmatter_orders_agent_id_after_agent() -> None:
    """`agent_id` must sit directly after `agent` so the frontmatter is easy
    to scan for humans. Stable ordering also keeps diffs minimal across ticks.
    """
    fm = {
        "agent": "claude-code",
        "agent_id": "abc-uuid",
        "agent_version": "1.0",
    }
    serialized = sn.serialize_frontmatter(fm, "")
    # Order should be agent, agent_id, agent_version
    agent_pos = serialized.index("agent:")
    agent_id_pos = serialized.index("agent_id:")
    agent_version_pos = serialized.index("agent_version:")
    assert agent_pos < agent_id_pos < agent_version_pos


def test_session_tags_emits_unified_agent_tag_when_agent_id_present() -> None:
    """DV-791 (PR review): session cards carry a SINGLE ``agent:<tool>:<id>`` tag.

    The old split form (``agent:<tool>`` + ``agent_id:<uuid>``) is gone for
    new writes — the backend parser now emits the same combined shape, so
    a single ``tag_contains`` lookup turns up cards from either path.
    """
    tags = sn.session_tags(
        session_id="sess-1",
        agent="claude-code",
        cwd="/tmp/myproject",
        agent_id="abc-uuid",
    )
    assert f"{sn.SESSION_TAG_PREFIX}sess-1" in tags
    assert "agent:claude-code:abc-uuid" in tags
    # Crucially: no legacy ``agent:<tool>`` bare tag, no standalone ``agent_id:`` tag.
    assert "agent:claude-code" not in tags
    assert not any(t.startswith("agent_id:") for t in tags)


def test_session_tags_falls_back_to_bare_agent_tag_when_agent_id_unknown() -> None:
    tags = sn.session_tags(session_id="sess-1", agent="claude-code", cwd="/tmp/myproject")
    # Without an agent_id we degrade to ``agent:<tool>`` so callers can still
    # narrow by tool.
    assert f"{sn.AGENT_TAG_PREFIX}claude-code" in tags
    assert not any(t.startswith("agent_id:") for t in tags)


def test_build_agent_tag_helper() -> None:
    assert sn.build_agent_tag("claude-code", "uuid-1") == "agent:claude-code:uuid-1"
    assert sn.build_agent_tag("claude-code", None) == "agent:claude-code"
    assert sn.build_agent_tag("claude-code", "") == "agent:claude-code"


# ---------------------------------------------------------------------------
# agents.py — local cache lookup helper
# ---------------------------------------------------------------------------


def test_load_agent_id_for_active_agent_returns_cached_uuid(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from deepvista_cli.commands import agents

    # Redirect the on-disk cache to a tmpdir and prime it with an entry.
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    monkeypatch.setattr(agents, "AGENTS_DIR", agents_dir)
    (agents_dir / "claude-code.json").write_text(json.dumps({"agent_id": "cached-uuid", "agent_type": "claude-code"}))

    # Force detect_agent_tool to look like Claude Code.
    monkeypatch.setattr(agents, "detect_agent_tool", lambda: ("claude-code", "1.0"))

    assert agents.load_agent_id_for_active_agent() == "cached-uuid"


def test_load_agent_id_for_active_agent_returns_none_when_unregistered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from deepvista_cli.commands import agents

    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    monkeypatch.setattr(agents, "AGENTS_DIR", agents_dir)
    monkeypatch.setattr(agents, "detect_agent_tool", lambda: ("claude-code", None))

    assert agents.load_agent_id_for_active_agent() is None


# ---------------------------------------------------------------------------
# +quick tag emission
# ---------------------------------------------------------------------------


class _Recorder:
    """Capture POST bodies sent through the CLI's HTTP client."""

    def __init__(self) -> None:
        self.posts: list[tuple[str, dict[str, Any]]] = []

    def post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        self.posts.append((path, body))
        return {"card": {"id": "card-1", "title": body.get("title")}}


def _invoke_quick(monkeypatch: pytest.MonkeyPatch, agent_id: str | None) -> _Recorder:
    """Drive `deepvista notes +quick` with a stubbed client and agent lookup."""
    import click
    from click.testing import CliRunner

    from deepvista_cli.commands import notes as notes_cmd

    monkeypatch.setattr(notes_cmd, "detect_agent_tool", lambda: ("claude-code", "1.0"))

    from deepvista_cli.commands import agents as agents_cmd

    monkeypatch.setattr(agents_cmd, "load_agent_id_for_active_agent", lambda: agent_id)

    recorder = _Recorder()
    monkeypatch.setattr(notes_cmd, "_client", lambda ctx: recorder)

    class _Obj:
        output_format = "json"
        auth_url = "http://localhost"
        project_id = None

    @click.group()
    @click.pass_context
    def root(ctx: click.Context) -> None:
        ctx.obj = _Obj()

    root.add_command(notes_cmd.notes_group)
    runner = CliRunner()
    result = runner.invoke(root, ["notes", "+quick", "hello world"])
    assert result.exit_code == 0, result.output
    return recorder


def test_quick_note_emits_unified_agent_tag_when_registered(monkeypatch: pytest.MonkeyPatch) -> None:
    """``+quick`` writes a SINGLE ``agent:<tool>:<id>`` tag (DV-791 PR review)."""
    recorder = _invoke_quick(monkeypatch, agent_id="abc-uuid")
    assert recorder.posts, "expected a POST /create_context_card call"
    path, body = recorder.posts[0]
    assert path == "/create_context_card"
    tags = body.get("tags") or []
    assert "agent:claude-code:abc-uuid" in tags
    # No bare ``agent:<tool>`` and no standalone ``agent_id:`` tag.
    assert "agent:claude-code" not in tags
    assert not any(t.startswith("agent_id:") for t in tags)


def test_quick_note_falls_back_to_bare_agent_tag_when_unregistered(monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = _invoke_quick(monkeypatch, agent_id=None)
    _, body = recorder.posts[0]
    tags = body.get("tags") or []
    assert f"{sn.AGENT_TAG_PREFIX}claude-code" in tags
    assert not any(t.startswith("agent_id:") for t in tags)


# ---------------------------------------------------------------------------
# X-DeepVista-Origin header includes agent_id when known
# ---------------------------------------------------------------------------


def test_build_origin_includes_agent_id_when_registered(monkeypatch: pytest.MonkeyPatch) -> None:
    from deepvista_cli.client import origin as origin_mod

    # Clear the lru_cache so the previous test's value doesn't leak in.
    origin_mod.build_origin.cache_clear()

    monkeypatch.setattr(origin_mod, "detect_agent_tool", lambda: ("claude-code", "1.0"))
    from deepvista_cli.commands import agents as agents_cmd

    monkeypatch.setattr(agents_cmd, "load_agent_id_for_active_agent", lambda: "abc-uuid")

    o = origin_mod.build_origin()
    assert o["tool"] == "claude-code"
    assert o["agent_id"] == "abc-uuid"

    origin_mod.build_origin.cache_clear()


def test_build_origin_omits_agent_id_when_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    from deepvista_cli.client import origin as origin_mod

    origin_mod.build_origin.cache_clear()

    monkeypatch.setattr(origin_mod, "detect_agent_tool", lambda: ("claude-code", "1.0"))
    from deepvista_cli.commands import agents as agents_cmd

    monkeypatch.setattr(agents_cmd, "load_agent_id_for_active_agent", lambda: None)

    o = origin_mod.build_origin()
    assert "agent_id" not in o

    origin_mod.build_origin.cache_clear()
