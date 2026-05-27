"""Tests for the managed-agent → Claude Code subagent export pipeline (DV-836)."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from deepvista_cli import agent_catalog

# ---------------------------------------------------------------------------
# Fake client
# ---------------------------------------------------------------------------


class FakeClient:
    """In-memory stand-in for ``DeepVistaClient`` (GET only)."""

    def __init__(self, agents: list[dict[str, Any]]) -> None:
        self._agents = agents
        self.calls: list[tuple[str, dict | None]] = []

    def get(self, path: str, params: dict | None = None) -> Any:
        self.calls.append((path, params))
        if path == "/agents":
            return {"agents": self._agents}
        raise AssertionError(f"unexpected GET {path}")


def _agent(role: str, *, name: str = "", aid: str = "id-x", updated: str = "2026-01-01") -> dict[str, Any]:
    return {
        "id": aid,
        "name": name or f"{role.title()} Claude",
        "agent_type": "claude-code",
        "agent_role": role,
        "updated_at": updated,
    }


# ---------------------------------------------------------------------------
# slug / render
# ---------------------------------------------------------------------------


def test_slugify_basic():
    assert agent_catalog.slugify("Marketing") == "marketing"
    assert agent_catalog.slugify("Go To Market!") == "go-to-market"


def test_slugify_fallback_on_empty():
    assert agent_catalog.slugify("你好", fallback="fallback") == "fallback"


def test_file_name_applies_prefix():
    meta = agent_catalog.AgentRoleMeta(role="marketing", agent_name="M", agent_id="a")
    assert agent_catalog.file_name(meta, prefix="dv-") == "dv-marketing.md"


def test_build_agent_markdown_handle_and_marker():
    meta = agent_catalog.AgentRoleMeta(
        role="marketing", agent_name="Marketing Claude", agent_id="abc123", updated_at="2026-05-01"
    )
    md = agent_catalog.build_agent_markdown(meta)
    # Invocation handle is the bare role, so `@marketing` resolves.
    assert "name: marketing" in md
    # Carries our marker + provenance so we can safely reclaim it later.
    assert f"{agent_catalog.AGENT_MARKER}: true" in md
    assert "x-deepvista-role:" in md
    assert "x-deepvista-agent-id: abc123" in md
    # Known role gets its specialist description + preloads the deepvista skill.
    assert "Marketing specialist for DeepVista" in md
    assert "skills: deepvista" in md
    assert "Marketing Claude" in md  # backing managed-agent name in the body


def test_build_agent_markdown_generic_role():
    meta = agent_catalog.AgentRoleMeta(role="legal", agent_name="", agent_id="z")
    md = agent_catalog.build_agent_markdown(meta)
    assert "name: legal" in md
    assert "Legal specialist for DeepVista" in md


def test_build_agent_markdown_bakes_custom_soul():
    """A managed agent with config.soul renders that prompt as the body, not the template."""
    meta = agent_catalog.AgentRoleMeta(
        role="marketing",
        agent_name="Marketing",
        agent_id="abc123",
        system_prompt="You are a bespoke marketing brain.\nGround everything in notes.",
    )
    md = agent_catalog.build_agent_markdown(meta)
    # Frontmatter stays templated (routing + preloaded skill + role description).
    assert "name: marketing" in md
    assert "skills: deepvista" in md
    assert "Marketing specialist for DeepVista" in md
    # Body is the custom prompt verbatim; the default template body is bypassed.
    assert "You are a bespoke marketing brain." in md
    assert "Operating procedure" not in md


def test_metas_from_agents_reads_config_soul():
    """config.soul flows into AgentRoleMeta.system_prompt for the export to bake in."""
    agents = [
        {
            "id": "m1",
            "name": "Marketing",
            "agent_type": "deepvista-cli",
            "agent_role": "marketing",
            "updated_at": "2026-05-27",
            "config": {"soul": "CUSTOM PROMPT", "machine": "laptop"},
        }
    ]
    metas = agent_catalog.metas_from_agents(agents)
    assert len(metas) == 1
    assert metas[0].system_prompt == "CUSTOM PROMPT"


# ---------------------------------------------------------------------------
# grouping
# ---------------------------------------------------------------------------


def test_metas_skip_misc_and_empty():
    metas = agent_catalog.metas_from_agents([_agent("misc"), _agent(""), _agent("  "), _agent("sales")])
    assert [m.role for m in metas] == ["sales"]


def test_metas_group_by_role_keep_freshest_and_count():
    metas = agent_catalog.metas_from_agents(
        [
            _agent("sales", name="Old Sales", aid="a1", updated="2026-01-01"),
            _agent("sales", name="New Sales", aid="a2", updated="2026-05-01"),
            _agent("marketing", aid="b1", updated="2026-02-01"),
        ]
    )
    by_role = {m.role: m for m in metas}
    assert set(by_role) == {"sales", "marketing"}
    assert by_role["sales"].agent_id == "a2"  # freshest representative
    assert by_role["sales"].agent_name == "New Sales"
    assert by_role["sales"].count == 2


# ---------------------------------------------------------------------------
# curated detection
# ---------------------------------------------------------------------------


def test_curated_names_ignores_our_files(tmp_path: Path):
    # A hand-curated agent (no marker).
    (tmp_path / "marketing.md").write_text("---\nname: marketing\n---\nbody\n", encoding="utf-8")
    # One of ours (carries the marker) — must not count as curated.
    (tmp_path / "dv-sales.md").write_text(
        f"---\nname: sales\n{agent_catalog.AGENT_MARKER}: true\n---\n", encoding="utf-8"
    )
    assert agent_catalog.curated_names(tmp_path, "dv-") == {"marketing"}


def test_plan_skips_curated_role(tmp_path: Path):
    (tmp_path / "marketing.md").write_text("---\nname: marketing\n---\n", encoding="utf-8")
    metas = agent_catalog.metas_from_agents([_agent("marketing"), _agent("sales")])
    plan = agent_catalog.compute_plan(metas, target=tmp_path, prefix="dv-", state={})
    assert plan.skipped_curated == ["marketing"]
    assert [m.slug for m in plan.to_add] == ["sales"]


# ---------------------------------------------------------------------------
# plan + apply + end-to-end
# ---------------------------------------------------------------------------


def test_sync_writes_then_idempotent(tmp_path: Path):
    client = FakeClient([_agent("sales"), _agent("marketing")])
    res = agent_catalog.sync_agent_defs(client, target=tmp_path, force=True, state_path=tmp_path / "state.json")
    assert res["ok"] is True
    assert res["summary"]["added"] == 2
    assert (tmp_path / "dv-sales.md").exists()
    assert (tmp_path / "dv-marketing.md").exists()

    # Re-run: nothing changes.
    res2 = agent_catalog.sync_agent_defs(client, target=tmp_path, force=True, state_path=tmp_path / "state.json")
    assert res2["summary"] == {"added": 0, "updated": 0, "removed": 0, "unchanged": 2, "skipped_curated": 0}


def test_sync_removes_def_when_role_gone(tmp_path: Path):
    state = tmp_path / "state.json"
    agent_catalog.sync_agent_defs(
        FakeClient([_agent("sales"), _agent("marketing")]), target=tmp_path, force=True, state_path=state
    )
    assert (tmp_path / "dv-marketing.md").exists()

    # Marketing role disappears server-side → its def is reclaimed.
    res = agent_catalog.sync_agent_defs(FakeClient([_agent("sales")]), target=tmp_path, force=True, state_path=state)
    assert res["summary"]["removed"] == 1
    assert not (tmp_path / "dv-marketing.md").exists()
    assert (tmp_path / "dv-sales.md").exists()


def test_sync_never_deletes_unmarked_file(tmp_path: Path):
    state = tmp_path / "state.json"
    agent_catalog.sync_agent_defs(FakeClient([_agent("sales")]), target=tmp_path, force=True, state_path=state)
    # A file sharing our prefix but without the marker must survive a reclaim.
    intruder = tmp_path / "dv-sales.md"
    intruder.write_text("---\nname: sales\n---\nhand edited\n", encoding="utf-8")
    agent_catalog.sync_agent_defs(FakeClient([]), target=tmp_path, force=True, state_path=state)
    assert intruder.exists()
    assert "hand edited" in intruder.read_text(encoding="utf-8")


def test_sync_throttled_skips_network(tmp_path: Path):
    state = tmp_path / "state.json"
    agent_catalog.save_state({"last_sync_epoch": int(time.time()), "defs": []}, state)
    client = FakeClient([_agent("sales")])
    res = agent_catalog.sync_agent_defs(client, target=tmp_path, throttle_min=60, state_path=state)
    assert res["skipped"] == "throttled"
    assert client.calls == []  # no network hit


def test_dry_run_writes_nothing(tmp_path: Path):
    client = FakeClient([_agent("sales")])
    res = agent_catalog.sync_agent_defs(
        client, target=tmp_path, force=True, dry_run=True, state_path=tmp_path / "s.json"
    )
    assert res["dry_run"] is True
    assert res["plan"]["to_add"] == ["sales"]
    assert not list(tmp_path.glob("dv-*.md"))
