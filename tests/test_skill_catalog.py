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
    cache_path = skill_catalog._body_cache_path("abc", root=cache_root)
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
