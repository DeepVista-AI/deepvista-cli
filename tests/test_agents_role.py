"""DV-832 · agent_role cache + flag plumbing in deepvista agents."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from deepvista_cli.commands import agents


def _set_cache_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    cache_dir = tmp_path / "agents"
    cache_dir.mkdir()
    monkeypatch.setattr(agents, "AGENTS_DIR", cache_dir)
    return cache_dir


def test_save_then_load_by_role_round_trip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cache_dir = _set_cache_dir(monkeypatch, tmp_path)

    agents._save_agent_id("claude-code", "uuid-marketing", "marketing")
    agents._save_agent_id("claude-code", "uuid-engineering", "engineering")

    assert (cache_dir / "claude-code__marketing.json").exists()
    assert (cache_dir / "claude-code__engineering.json").exists()

    assert agents._load_agent_id("claude-code", "marketing") == "uuid-marketing"
    assert agents._load_agent_id("claude-code", "engineering") == "uuid-engineering"


def test_load_without_role_returns_newest_match(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cache_dir = _set_cache_dir(monkeypatch, tmp_path)

    older = cache_dir / "claude-code__marketing.json"
    newer = cache_dir / "claude-code__engineering.json"
    older.write_text(json.dumps({"agent_id": "uuid-old", "agent_type": "claude-code", "agent_role": "marketing"}))
    newer.write_text(json.dumps({"agent_id": "uuid-new", "agent_type": "claude-code", "agent_role": "engineering"}))

    import os

    os.utime(older, (1_700_000_000, 1_700_000_000))
    os.utime(newer, (1_800_000_000, 1_800_000_000))

    assert agents._load_agent_id("claude-code") == "uuid-new"


def test_load_falls_back_to_legacy_filename(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cache_dir = _set_cache_dir(monkeypatch, tmp_path)
    (cache_dir / "claude-code.json").write_text(json.dumps({"agent_id": "uuid-legacy", "agent_type": "claude-code"}))

    # Loading without a role surfaces the legacy entry.
    assert agents._load_agent_id("claude-code") == "uuid-legacy"


def test_remove_without_role_clears_all_for_type(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cache_dir = _set_cache_dir(monkeypatch, tmp_path)

    (cache_dir / "claude-code__marketing.json").write_text("{}")
    (cache_dir / "claude-code__engineering.json").write_text("{}")
    (cache_dir / "claude-code.json").write_text("{}")
    (cache_dir / "cursor__misc.json").write_text("{}")

    agents._remove_agent_id("claude-code")

    assert not (cache_dir / "claude-code__marketing.json").exists()
    assert not (cache_dir / "claude-code__engineering.json").exists()
    assert not (cache_dir / "claude-code.json").exists()
    assert (cache_dir / "cursor__misc.json").exists()


def test_remove_with_role_only_clears_that_role(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cache_dir = _set_cache_dir(monkeypatch, tmp_path)

    (cache_dir / "claude-code__marketing.json").write_text("{}")
    (cache_dir / "claude-code__engineering.json").write_text("{}")

    agents._remove_agent_id("claude-code", "marketing")

    assert not (cache_dir / "claude-code__marketing.json").exists()
    assert (cache_dir / "claude-code__engineering.json").exists()


def test_agent_role_choices_match_backend_enum() -> None:
    # Mirrors the SQL CHECK constraint + Python AgentRole enum in deepvista.
    expected = ("sales", "marketing", "product", "engineering", "hiring", "content", "misc")
    assert agents.AGENT_ROLE_CHOICES == expected
    assert agents.DEFAULT_AGENT_ROLE == "misc"
