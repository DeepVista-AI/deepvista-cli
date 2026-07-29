"""Tests for the skill catalog sync + lazy-load pipeline."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from deepvista_cli import skill_catalog

# ---------------------------------------------------------------------------
# Fake client
# ---------------------------------------------------------------------------


class FakeClient:
    """In-memory stand-in for ``DeepVistaClient``.

    Queue response bodies per endpoint. Each ``post`` pops the next response
    for that endpoint; if the queue is empty the test fails loudly — we want
    to catch unexpected network calls, not silently return None.
    """

    def __init__(self) -> None:
        self._responses: dict[str, list[Any]] = {}
        self.calls: list[tuple[str, dict | None]] = []

    def enqueue(self, path: str, response: Any) -> None:
        self._responses.setdefault(path, []).append(response)

    def post(self, path: str, body: dict | None = None) -> Any:
        self.calls.append((path, body))
        queue = self._responses.get(path)
        if not queue:
            raise AssertionError(f"unexpected POST {path} (body={body!r})")
        return queue.pop(0)


# ---------------------------------------------------------------------------
# slugify / render unit tests
# ---------------------------------------------------------------------------


def test_slugify_basic():
    assert skill_catalog.slugify_for_dir("Hello World") == "hello-world"


def test_slugify_collapses_punctuation():
    assert skill_catalog.slugify_for_dir("Foo, Bar — Baz!!") == "foo-bar-baz"


def test_slugify_cjk_falls_back():
    assert skill_catalog.slugify_for_dir("你好", fallback="id123") == "id123"


def test_stub_dir_name_applies_prefix():
    meta = skill_catalog.SkillMeta(id="x", title="My Skill", description="")
    assert skill_catalog.stub_dir_name(meta, prefix="dv-") == "dv-my-skill"


def test_build_stub_markdown_includes_marker_and_id():
    meta = skill_catalog.SkillMeta(
        id="abc-123",
        title="Ship It",
        description="A skill for shipping things.",
        updated_at="2026-04-24T00:00:00Z",
        tags=("ship", "deploy"),
    )
    md = skill_catalog.build_stub_markdown(meta, prefix="dv-")

    assert "name: dv-ship-it" in md
    assert f"{skill_catalog.STUB_MARKER}: true" in md
    assert "x-deepvista-id: abc-123" in md
    assert "x-deepvista-updated-at: 2026-04-24T00:00:00Z" in md
    assert "!`deepvista skill load abc-123`" in md
    # Plain-English fallback for agents without !cmd preprocessing.
    assert "deepvista skill load abc-123" in md
    # Frontmatter fence present.
    assert md.startswith("---\n")


def test_build_stub_markdown_quotes_special_chars_in_description():
    meta = skill_catalog.SkillMeta(
        id="x",
        title="Quoting",
        description='He said "hello" — and left.',
    )
    md = skill_catalog.build_stub_markdown(meta)
    # Embedded quote must be escaped.
    assert r'"He said \"hello\" — and left."' in md


def test_description_truncation():
    long = "word " * 300
    meta = skill_catalog.SkillMeta(id="x", title="Long", description=long)
    md = skill_catalog.build_stub_markdown(meta)
    # A compact single-line description ends with an ellipsis.
    desc_line = next(line for line in md.splitlines() if line.startswith("description:"))
    assert desc_line.endswith('…"')


# ---------------------------------------------------------------------------
# compute_plan / apply_plan
# ---------------------------------------------------------------------------


def _meta(id_: str, title: str, desc: str = "") -> skill_catalog.SkillMeta:
    return skill_catalog.SkillMeta(id=id_, title=title, description=desc)


def test_compute_plan_add_update_remove(tmp_path: Path):
    prefix = "dv-"
    target = tmp_path / "skills"
    target.mkdir()

    # Pretend we previously synced "old-one" and "rename-me".
    # "rename-me" is going to change its title → dir rename → old dir removed.
    (target / "dv-old-one").mkdir()
    (target / "dv-old-one" / "SKILL.md").write_text("stale stub")
    (target / "dv-rename-me").mkdir()
    (target / "dv-rename-me" / "SKILL.md").write_text("also stale")

    state = {
        "stubs": [
            {"id": "id-old", "dir_name": "dv-old-one", "content_hash": "x"},
            {"id": "id-rename", "dir_name": "dv-rename-me", "content_hash": "x"},
        ]
    }

    server = [
        _meta("id-new", "Brand New"),
        _meta("id-rename", "Rename Me Now"),  # title changed → dir changes
    ]

    plan = skill_catalog.compute_plan(server, target=target, prefix=prefix, state=state)

    added_ids = {m.id for m in plan.to_add}
    updated_ids = {m.id for m in plan.to_update}

    assert added_ids == {"id-new", "id-rename"}  # rename appears as an add at new dir
    assert updated_ids == set()  # neither existing stub matches the new content
    # `old-one` (dropped by server) + `rename-me` (old slug) both removed.
    assert set(plan.to_remove) == {"dv-old-one", "dv-rename-me"}


def test_compute_plan_disambiguates_duplicate_titles(tmp_path: Path):
    """Two server skills with the same title must land in distinct dirs."""
    target = tmp_path / "skills"
    target.mkdir()

    server = [
        _meta("11111111-1111-1111-1111-111111111111", "Workflow Foo"),
        _meta("22222222-2222-2222-2222-222222222222", "Workflow Foo"),  # same title
    ]
    plan = skill_catalog.compute_plan(server, target=target, prefix="dv-", state={})

    first = plan.dir_names["11111111-1111-1111-1111-111111111111"]
    second = plan.dir_names["22222222-2222-2222-2222-222222222222"]
    assert first == "dv-workflow-foo"
    assert second != first
    assert second.startswith("dv-workflow-foo-")

    skill_catalog.apply_plan(plan, target=target, prefix="dv-")
    assert (target / first / "SKILL.md").exists()
    assert (target / second / "SKILL.md").exists()


def test_compute_plan_unchanged(tmp_path: Path):
    target = tmp_path / "skills"
    target.mkdir()

    meta = _meta("id-1", "Stable Skill", "A stable description.")
    rendered = skill_catalog.build_stub_markdown(meta)
    stub_dir = target / skill_catalog.stub_dir_name(meta)
    stub_dir.mkdir()
    (stub_dir / "SKILL.md").write_text(rendered)

    state = {
        "stubs": [
            {
                "id": "id-1",
                "dir_name": skill_catalog.stub_dir_name(meta),
                "content_hash": skill_catalog.stub_content_hash(rendered),
            }
        ]
    }

    plan = skill_catalog.compute_plan([meta], target=target, prefix="dv-", state=state)
    assert plan.unchanged == 1
    assert not plan.to_add
    assert not plan.to_update
    assert not plan.to_remove


def test_apply_plan_writes_files_and_removes_only_marked_dirs(tmp_path: Path):
    target = tmp_path / "skills"
    target.mkdir()

    # A user-owned skill that happens to share our prefix but has NO marker —
    # must be left alone even if it appears in `to_remove`.
    user_dir = target / "dv-user-owned"
    user_dir.mkdir()
    (user_dir / "SKILL.md").write_text("---\nname: user-owned\n---\nhand-written")

    # A genuine catalog stub we should remove.
    doomed_dir = target / "dv-doomed"
    doomed_dir.mkdir()
    doomed_stub = skill_catalog.build_stub_markdown(_meta("id-doomed", "Doomed"))
    (doomed_dir / "SKILL.md").write_text(doomed_stub)

    plan = skill_catalog.SyncPlan(
        to_add=[_meta("id-fresh", "Fresh Skill")],
        to_remove=["dv-user-owned", "dv-doomed"],
    )
    new_state = skill_catalog.apply_plan(plan, target=target, prefix="dv-")

    # New stub was written.
    added_dir = target / "dv-fresh-skill"
    assert (added_dir / "SKILL.md").exists()

    # User-owned dir is untouched.
    assert user_dir.exists()
    assert (user_dir / "SKILL.md").read_text() == ("---\nname: user-owned\n---\nhand-written")

    # Marked catalog dir was removed.
    assert not doomed_dir.exists()

    # New state includes the added stub only.
    assert [s["id"] for s in new_state["stubs"]] == ["id-fresh"]


# ---------------------------------------------------------------------------
# sync_catalog orchestration
# ---------------------------------------------------------------------------


def _enqueue_list(fake: FakeClient, cards: list[dict]) -> None:
    fake.enqueue("/get_context_cards", {"cards": cards, "has_more": False})


def test_sync_catalog_end_to_end(tmp_path: Path):
    state_path = tmp_path / "state.json"
    target = tmp_path / "skills"

    fake = FakeClient()
    _enqueue_list(
        fake,
        [
            {"id": "id-a", "title": "Alpha", "description": "First", "updated_at": "t1"},
            {"id": "id-b", "title": "Bravo", "description": "Second", "updated_at": "t1"},
        ],
    )

    result = skill_catalog.sync_catalog(
        fake,
        target=target,
        prefix="dv-",
        state_path=state_path,
        throttle_min=0,  # never throttle in tests
    )

    assert result["ok"] is True
    assert result["summary"]["added"] == 2
    assert (target / "dv-alpha" / "SKILL.md").exists()
    assert (target / "dv-bravo" / "SKILL.md").exists()

    state = skill_catalog.load_state(state_path)
    assert {s["id"] for s in state["stubs"]} == {"id-a", "id-b"}
    assert state["target"] == str(target)


def test_sync_catalog_throttled(tmp_path: Path):
    state_path = tmp_path / "state.json"
    target = tmp_path / "skills"

    # Seed a fresh last-sync.
    skill_catalog.save_state({"last_sync_epoch": int(time.time()), "stubs": []}, state_path)

    fake = FakeClient()  # empty queue — any network call would raise
    result = skill_catalog.sync_catalog(
        fake,
        target=target,
        prefix="dv-",
        state_path=state_path,
        throttle_min=60,
    )
    assert result["skipped"] == "throttled"
    assert fake.calls == []  # no network call attempted


def test_sync_catalog_force_overrides_throttle(tmp_path: Path):
    state_path = tmp_path / "state.json"
    target = tmp_path / "skills"
    skill_catalog.save_state({"last_sync_epoch": int(time.time()), "stubs": []}, state_path)

    fake = FakeClient()
    _enqueue_list(fake, [{"id": "id-a", "title": "Alpha", "description": ""}])

    result = skill_catalog.sync_catalog(
        fake,
        target=target,
        prefix="dv-",
        state_path=state_path,
        throttle_min=60,
        force=True,
    )
    assert result.get("ok") is True
    assert (target / "dv-alpha" / "SKILL.md").exists()


def test_sync_catalog_dry_run_does_not_write(tmp_path: Path):
    state_path = tmp_path / "state.json"
    target = tmp_path / "skills"
    fake = FakeClient()
    _enqueue_list(fake, [{"id": "id-a", "title": "Alpha", "description": ""}])

    result = skill_catalog.sync_catalog(
        fake,
        target=target,
        prefix="dv-",
        state_path=state_path,
        throttle_min=0,
        dry_run=True,
    )

    assert result["dry_run"] is True
    assert result["plan"]["to_add"] == ["Alpha"]
    assert not (target / "dv-alpha").exists()
    # State file should not have been written on dry run.
    assert not state_path.exists()


def test_sync_catalog_migrates_stubs_on_target_change(tmp_path: Path):
    """Switching --target should clean stubs from the old target."""
    state_path = tmp_path / "state.json"
    target_a = tmp_path / "old" / "skills"
    target_b = tmp_path / "new" / "skills"

    fake1 = FakeClient()
    _enqueue_list(fake1, [{"id": "id-a", "title": "Alpha", "description": ""}])
    skill_catalog.sync_catalog(fake1, target=target_a, prefix="dv-", state_path=state_path, throttle_min=0)
    assert (target_a / "dv-alpha" / "SKILL.md").exists()

    fake2 = FakeClient()
    _enqueue_list(fake2, [{"id": "id-a", "title": "Alpha", "description": ""}])
    result = skill_catalog.sync_catalog(fake2, target=target_b, prefix="dv-", state_path=state_path, throttle_min=0)

    assert (target_b / "dv-alpha" / "SKILL.md").exists()
    # Old location cleaned up, reported in result.
    assert not (target_a / "dv-alpha").exists()
    assert result.get("migrated_from") == str(target_a)
    assert "dv-alpha" in result.get("migrated_stubs_removed", [])


def test_sync_catalog_reconciles_when_stubs_wiped(tmp_path: Path):
    """A wiped target must trigger a sync even when within throttle window."""
    state_path = tmp_path / "state.json"
    target = tmp_path / "skills"

    fake1 = FakeClient()
    _enqueue_list(
        fake1,
        [
            {"id": "id-a", "title": "Alpha", "description": ""},
            {"id": "id-b", "title": "Bravo", "description": ""},
        ],
    )
    skill_catalog.sync_catalog(fake1, target=target, prefix="dv-", state_path=state_path, throttle_min=0)

    # Simulate external wipe (e.g. marketplace auto-update).
    import shutil as _sh

    _sh.rmtree(target)

    fake2 = FakeClient()
    _enqueue_list(
        fake2,
        [
            {"id": "id-a", "title": "Alpha", "description": ""},
            {"id": "id-b", "title": "Bravo", "description": ""},
        ],
    )
    # Throttle is long, but reconcile must bypass it.
    result = skill_catalog.sync_catalog(fake2, target=target, prefix="dv-", state_path=state_path, throttle_min=60)

    assert result.get("ok") is True
    assert (target / "dv-alpha" / "SKILL.md").exists()
    assert (target / "dv-bravo" / "SKILL.md").exists()


def test_sync_catalog_removes_server_deleted_stubs(tmp_path: Path):
    state_path = tmp_path / "state.json"
    target = tmp_path / "skills"

    # Round 1: sync two skills.
    fake = FakeClient()
    _enqueue_list(
        fake,
        [
            {"id": "id-a", "title": "Alpha", "description": ""},
            {"id": "id-b", "title": "Bravo", "description": ""},
        ],
    )
    skill_catalog.sync_catalog(fake, target=target, prefix="dv-", state_path=state_path, throttle_min=0)

    # Round 2: server drops id-b.
    fake2 = FakeClient()
    _enqueue_list(fake2, [{"id": "id-a", "title": "Alpha", "description": ""}])
    result = skill_catalog.sync_catalog(
        fake2, target=target, prefix="dv-", state_path=state_path, throttle_min=0, force=True
    )

    assert result["summary"]["removed"] == 1
    assert (target / "dv-alpha").exists()
    assert not (target / "dv-bravo").exists()


# ---------------------------------------------------------------------------
# load_skill_body — lazy body fetch + cache
# ---------------------------------------------------------------------------


def test_load_skill_body_writes_and_reuses_cache(tmp_path: Path):
    cache_root = tmp_path / "cache"
    fake = FakeClient()
    fake.enqueue(
        "/get_context_card",
        {
            "id": "abc",
            "title": "Alpha",
            "summary": "short",
            "content": "# Alpha\n\nHello from server.",
        },
    )

    body1 = skill_catalog.load_skill_body(fake, "abc", cache_root=cache_root, ttl_sec=60)
    assert "Hello from server." in body1
    assert len(fake.calls) == 1

    # Second call hits cache — no additional network call.
    body2 = skill_catalog.load_skill_body(fake, "abc", cache_root=cache_root, ttl_sec=60)
    assert body1 == body2
    assert len(fake.calls) == 1


def test_load_skill_body_no_cache_refetches(tmp_path: Path):
    cache_root = tmp_path / "cache"
    fake = FakeClient()
    fake.enqueue(
        "/get_context_card",
        {"id": "abc", "title": "A", "content": "one"},
    )
    fake.enqueue(
        "/get_context_card",
        {"id": "abc", "title": "A", "content": "two"},
    )

    first = skill_catalog.load_skill_body(fake, "abc", cache_root=cache_root, ttl_sec=60)
    second = skill_catalog.load_skill_body(fake, "abc", cache_root=cache_root, ttl_sec=60, use_cache=False)

    assert "one" in first
    assert "two" in second
    assert len(fake.calls) == 2


def test_load_skill_body_cache_expires(tmp_path: Path):
    cache_root = tmp_path / "cache"
    fake = FakeClient()
    fake.enqueue("/get_context_card", {"id": "abc", "title": "A", "content": "one"})
    body = skill_catalog.load_skill_body(fake, "abc", cache_root=cache_root, ttl_sec=60)
    cache_path = skill_catalog._card_cache_path("abc", root=cache_root)
    assert cache_path.exists()

    # Roll the mtime back past the TTL.
    past = time.time() - 120
    import os

    os.utime(cache_path, (past, past))

    fake.enqueue("/get_context_card", {"id": "abc", "title": "A", "content": "two"})
    body2 = skill_catalog.load_skill_body(fake, "abc", cache_root=cache_root, ttl_sec=60)
    assert "two" in body2
    assert "one" not in body2
    assert body != body2


# ---------------------------------------------------------------------------
# Trigger description (DV-1869)
#
# For a skill card the `description` column *is* the whole SKILL.md, so taking
# it verbatim gave the stub a flattened-YAML description — the one line an agent
# reads to decide whether to load the skill.
# ---------------------------------------------------------------------------

SKILL_BODY = """---
name: narrated-browser
description: Drive a browser through a flow and produce a narrated MP4.
type: tool
files:
  - path: narrate.py
    sha256: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
    mode: "755"
---

# Narrated browser recordings

Turn a flow into a narrated MP4.
"""


def test_trigger_description_prefers_the_parsed_attribute():
    meta = skill_catalog.SkillMeta.from_card(
        {
            "id": "id-1",
            "title": "narrated-browser",
            "description": SKILL_BODY,
            "attributes": {"description": "From attributes.", "bundle_sha": "abc", "file_count": 1},
        }
    )
    assert meta.description == "From attributes."


def test_trigger_description_falls_back_to_the_bodys_frontmatter():
    meta = skill_catalog.SkillMeta.from_card({"id": "id-1", "title": "narrated-browser", "description": SKILL_BODY})

    assert meta.description == "Drive a browser through a flow and produce a narrated MP4."
    # The regression: no YAML punctuation, no manifest, no `type:`/`execution:`.
    assert not meta.description.startswith("---")
    assert "sha256" not in meta.description


def test_trigger_description_keeps_working_for_plain_bodies():
    meta = skill_catalog.SkillMeta.from_card({"id": "id-1", "title": "Plain", "description": "Just prose."})
    assert meta.description == "Just prose."


def test_stub_description_is_the_skills_own_description():
    meta = skill_catalog.SkillMeta.from_card({"id": "id-1", "title": "narrated-browser", "description": SKILL_BODY})

    stub = skill_catalog.build_stub_markdown(meta)

    assert 'description: "Drive a browser through a flow and produce a narrated MP4."' in stub


# ---------------------------------------------------------------------------
# Rendered body (DV-1869): one frontmatter block, no manifest
# ---------------------------------------------------------------------------


def test_render_skill_body_does_not_double_wrap_frontmatter():
    rendered = skill_catalog.render_skill_body({"id": "id-1", "title": "narrated-browser", "description": SKILL_BODY})

    assert rendered.splitlines().count("---") == 2
    assert rendered.startswith("---\nname: narrated-browser")
    # The manifest is machine state the installer already consumed.
    assert "files:" not in rendered
    assert "sha256" not in rendered
    # The real description survives; the title is not duplicated as an H1.
    assert "description: Drive a browser through a flow" in rendered
    assert rendered.count("# Narrated browser recordings") == 1
    # The id is stamped onto the body's own block rather than a second one.
    assert "x-deepvista-id: id-1" in rendered


def test_render_skill_body_is_idempotent_on_the_id_stamp():
    card = {"id": "id-1", "title": "narrated-browser", "description": SKILL_BODY}
    once = skill_catalog.render_skill_body(card)
    twice = skill_catalog.render_skill_body({**card, "description": once})
    assert once == twice
    assert twice.count("x-deepvista-id:") == 1


def test_render_skill_body_still_wraps_a_frontmatterless_card():
    rendered = skill_catalog.render_skill_body({"id": "id-1", "title": "Plain", "description": "Just prose."})

    assert rendered.startswith('---\nname: "Plain"')
    assert "# Plain" in rendered
    assert "Just prose." in rendered


# ---------------------------------------------------------------------------
# Stub removal must not take an installed bundle with it (DV-1869)
#
# A stub dir doubles as a bundle root, so `rmtree` deleted a working install's
# scripts — the machine lost them at the next SessionStart sync.
# ---------------------------------------------------------------------------


def _installed_stub(target: Path, dir_name: str = "dv-alpha") -> Path:
    from deepvista_cli import bundle

    stub_dir = target / dir_name
    stub_dir.mkdir(parents=True)
    (stub_dir / "SKILL.md").write_text(skill_catalog.build_stub_markdown(_meta("id-a", "Alpha")))
    (stub_dir / "scripts").mkdir()
    (stub_dir / "scripts" / "run.py").write_text("print('hi')\n")
    bundle.write_marker(stub_dir, [bundle.BundleFile(path="scripts/run.py", sha256=_sha("print('hi')\n"))])
    return stub_dir


def _sha(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode()).hexdigest()


def test_remove_stub_dir_deletes_the_bundle_it_installed(tmp_path: Path):
    stub_dir = _installed_stub(tmp_path)

    assert skill_catalog.remove_stub_dir(stub_dir, "dv-") is True
    assert not stub_dir.exists()


def test_remove_stub_dir_keeps_a_locally_edited_file(tmp_path: Path):
    stub_dir = _installed_stub(tmp_path)
    (stub_dir / "scripts" / "run.py").write_text("print('i edited this')\n")

    assert skill_catalog.remove_stub_dir(stub_dir, "dv-") is False
    assert (stub_dir / "scripts" / "run.py").read_text() == "print('i edited this')\n"
    # The stub itself is still retired.
    assert not (stub_dir / "SKILL.md").exists()


def test_remove_stub_dir_keeps_files_it_never_installed(tmp_path: Path):
    stub_dir = _installed_stub(tmp_path)
    (stub_dir / "my-notes.md").write_text("mine\n")

    assert skill_catalog.remove_stub_dir(stub_dir, "dv-") is False
    assert (stub_dir / "my-notes.md").exists()
    assert not (stub_dir / "scripts" / "run.py").exists()


def test_remove_stub_dir_refuses_an_unmarked_dir(tmp_path: Path):
    stub_dir = tmp_path / "dv-user-owned"
    stub_dir.mkdir()
    (stub_dir / "SKILL.md").write_text("---\nname: user-owned\n---\nhand-written")

    assert skill_catalog.remove_stub_dir(stub_dir, "dv-") is False
    assert (stub_dir / "SKILL.md").read_text() == "---\nname: user-owned\n---\nhand-written"


def test_sync_catalog_carries_an_installed_bundle_to_the_new_target(tmp_path: Path):
    """The reported failure: a target switch must not lose installed scripts."""
    state_path = tmp_path / "state.json"
    target_a = tmp_path / "old" / "skills"
    target_b = tmp_path / "new" / "skills"

    fake1 = FakeClient()
    _enqueue_list(fake1, [{"id": "id-a", "title": "Alpha", "description": ""}])
    skill_catalog.sync_catalog(fake1, target=target_a, prefix="dv-", state_path=state_path, throttle_min=0)

    # Simulate `pull` / `skill load` having installed the bundle into the stub dir.
    from deepvista_cli import bundle

    stub_a = target_a / "dv-alpha"
    (stub_a / "scripts").mkdir()
    (stub_a / "scripts" / "run.py").write_text("print('hi')\n")
    (stub_a / "scripts" / "run.py").chmod(0o755)
    bundle.write_marker(stub_a, [bundle.BundleFile(path="scripts/run.py", sha256=_sha("print('hi')\n"), mode="755")])

    fake2 = FakeClient()
    _enqueue_list(fake2, [{"id": "id-a", "title": "Alpha", "description": ""}])
    result = skill_catalog.sync_catalog(fake2, target=target_b, prefix="dv-", state_path=state_path, throttle_min=0)

    moved = target_b / "dv-alpha" / "scripts" / "run.py"
    assert moved.read_text() == "print('hi')\n"
    assert moved.stat().st_mode & 0o777 == 0o755
    assert (target_b / "dv-alpha" / bundle.MARKER_FILENAME).exists()
    assert not (target_a / "dv-alpha").exists()
    assert result.get("migrated_bundles") == ["dv-alpha"]


def test_synced_target_dir_follows_the_recorded_target(tmp_path: Path, monkeypatch):
    """`pull` must install where sync actually wrote, not where we'd default to."""
    state_path = tmp_path / "state.json"
    plugin_dir = tmp_path / "plugin" / "skills"
    skill_catalog.save_state({"target": str(plugin_dir), "stubs": []}, state_path)
    monkeypatch.setattr(skill_catalog, "CATALOG_STATE_FILE", state_path)

    assert skill_catalog.synced_target_dir() == plugin_dir


def test_synced_target_dir_defaults_without_state(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(skill_catalog, "CATALOG_STATE_FILE", tmp_path / "missing.json")
    monkeypatch.delenv("CLAUDE_PLUGIN_ROOT", raising=False)
    assert skill_catalog.synced_target_dir() == skill_catalog.DEFAULT_TARGET_DIR


# ---------------------------------------------------------------------------
# Bundle store (DV-1869 follow-up)
#
# Stubs follow whichever agent dir syncs them — under the Claude Code plugin
# that's `${CLAUDE_PLUGIN_ROOT}/skills`, a version-pinned path the marketplace
# updater wipes on upgrade. Bundles kept beside them were deleted by an upgrade
# with no old location left to migrate from, so they now live in their own store.
# ---------------------------------------------------------------------------


def test_bundle_root_is_the_store_keyed_by_card_id(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("DEEPVISTA_BUNDLE_DIR", str(tmp_path / "store"))

    root = skill_catalog.bundle_root_for("card-abc", {"title": "Narrated Browser"})

    assert root == tmp_path / "store" / "card-abc"
    # Keyed by id, not the title — renaming a skill must not orphan its bundle.
    renamed = skill_catalog.bundle_root_for("card-abc", {"title": "Something Else Entirely"})
    assert renamed == root


def test_bundle_root_honours_an_explicit_target(tmp_path: Path):
    root = skill_catalog.bundle_root_for("card-abc", {"title": "x"}, target=tmp_path / "workdir")
    assert root == tmp_path / "workdir"


def test_default_target_follows_the_plugin_root(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(tmp_path / "plugin"))
    assert skill_catalog.default_target_dir() == tmp_path / "plugin" / "skills"

    monkeypatch.delenv("CLAUDE_PLUGIN_ROOT")
    assert skill_catalog.default_target_dir() == skill_catalog.DEFAULT_TARGET_DIR


def _legacy_install(stub_dir: Path) -> None:
    """A bundle installed under the old layout: files inside the stub dir."""
    from deepvista_cli import bundle

    stub_dir.mkdir(parents=True, exist_ok=True)
    (stub_dir / "SKILL.md").write_text(skill_catalog.build_stub_markdown(_meta("id-a", "Alpha")))
    (stub_dir / "scripts").mkdir(exist_ok=True)
    (stub_dir / "scripts" / "run.py").write_text("print('hi')\n")
    (stub_dir / "scripts" / "run.py").chmod(0o755)
    bundle.write_marker(stub_dir, [bundle.BundleFile(path="scripts/run.py", sha256=_sha("print('hi')\n"), mode="755")])


def test_migrate_legacy_bundle_moves_files_and_marker(tmp_path: Path, monkeypatch):
    from deepvista_cli import bundle

    state_path = tmp_path / "state.json"
    stubs = tmp_path / "skills"
    _legacy_install(stubs / "dv-alpha")
    skill_catalog.save_state({"target": str(stubs), "stubs": [{"id": "id-a", "dir_name": "dv-alpha"}]}, state_path)
    monkeypatch.setattr(skill_catalog, "CATALOG_STATE_FILE", state_path)
    store = tmp_path / "store" / "id-a"

    moved = skill_catalog.migrate_legacy_bundle("id-a", {"title": "Alpha"}, store)

    assert moved == ["scripts/run.py"]
    assert (store / "scripts" / "run.py").read_text() == "print('hi')\n"
    assert (store / "scripts" / "run.py").stat().st_mode & 0o777 == 0o755
    assert (store / bundle.MARKER_FILENAME).exists()
    # Moved, not copied — the stub dir keeps only the stub.
    assert not (stubs / "dv-alpha" / "scripts" / "run.py").exists()
    assert (stubs / "dv-alpha" / "SKILL.md").exists()


def test_migrate_legacy_bundle_is_a_no_op_with_nothing_to_move(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(skill_catalog, "CATALOG_STATE_FILE", tmp_path / "missing.json")
    assert skill_catalog.migrate_legacy_bundle("id-a", {"title": "Alpha"}, tmp_path / "store") == []


def test_migrate_legacy_bundle_lets_the_store_win(tmp_path: Path, monkeypatch):
    """A fresh install in the store is at least as current as the legacy copy."""
    state_path = tmp_path / "state.json"
    stubs = tmp_path / "skills"
    _legacy_install(stubs / "dv-alpha")
    skill_catalog.save_state({"target": str(stubs), "stubs": [{"id": "id-a", "dir_name": "dv-alpha"}]}, state_path)
    monkeypatch.setattr(skill_catalog, "CATALOG_STATE_FILE", state_path)

    store = tmp_path / "store" / "id-a"
    (store / "scripts").mkdir(parents=True)
    (store / "scripts" / "run.py").write_text("print('newer')\n")

    assert skill_catalog.migrate_legacy_bundle("id-a", {"title": "Alpha"}, store) == []
    assert (store / "scripts" / "run.py").read_text() == "print('newer')\n"


def test_ensure_skill_bundle_migrates_instead_of_redownloading(tmp_path: Path, monkeypatch):
    """A legacy install must be adopted, not fetched again."""
    from deepvista_cli import bundle

    state_path = tmp_path / "state.json"
    stubs = tmp_path / "skills"
    _legacy_install(stubs / "dv-alpha")
    skill_catalog.save_state({"target": str(stubs), "stubs": [{"id": "id-a", "dir_name": "dv-alpha"}]}, state_path)
    monkeypatch.setattr(skill_catalog, "CATALOG_STATE_FILE", state_path)
    monkeypatch.setenv("DEEPVISTA_BUNDLE_DIR", str(tmp_path / "store"))

    sha = _sha("print('hi')\n")
    body = f'---\nname: alpha\nfiles:\n  - path: scripts/run.py\n    sha256: {sha}\n    mode: "755"\n---\n\n# Alpha\n'

    class NoFetchClient:
        def post(self, path, body=None):
            raise AssertionError(f"unexpected POST {path}")

        def get(self, path, params=None):
            raise AssertionError(f"unexpected download: {path} {params}")

    root = skill_catalog.ensure_skill_bundle(NoFetchClient(), "id-a", {"id": "id-a", "title": "Alpha", "content": body})

    assert root == tmp_path / "store" / "id-a"
    assert (root / "scripts" / "run.py").read_text() == "print('hi')\n"
    assert bundle.read_marker(root).get("bundle_sha")


def test_a_wiped_plugin_dir_does_not_touch_the_store(tmp_path: Path, monkeypatch):
    """The upgrade scenario the store exists for.

    The marketplace updater deletes the whole version-pinned plugin dir, so there
    is no old location for a migration to read — the bundle only survives because
    it was never in there.
    """
    import shutil as _shutil

    from deepvista_cli import bundle

    state_path = tmp_path / "state.json"
    plugin_v1 = tmp_path / "plugin" / "4.3.0" / "skills"
    store = tmp_path / "store" / "id-a"

    fake1 = FakeClient()
    _enqueue_list(fake1, [{"id": "id-a", "title": "Alpha", "description": ""}])
    skill_catalog.sync_catalog(fake1, target=plugin_v1, prefix="dv-", state_path=state_path, throttle_min=0)

    # Bundle installed into the store, not the stub dir.
    (store / "scripts").mkdir(parents=True)
    (store / "scripts" / "run.py").write_text("print('hi')\n")
    bundle.write_marker(store, [bundle.BundleFile(path="scripts/run.py", sha256=_sha("print('hi')\n"))])

    # Upgrade: the old plugin version dir is deleted outright, new one appears.
    _shutil.rmtree(tmp_path / "plugin" / "4.3.0")
    plugin_v2 = tmp_path / "plugin" / "4.4.0" / "skills"

    fake2 = FakeClient()
    _enqueue_list(fake2, [{"id": "id-a", "title": "Alpha", "description": ""}])
    skill_catalog.sync_catalog(fake2, target=plugin_v2, prefix="dv-", state_path=state_path, throttle_min=0)

    assert (plugin_v2 / "dv-alpha" / "SKILL.md").exists()
    assert (store / "scripts" / "run.py").read_text() == "print('hi')\n"
