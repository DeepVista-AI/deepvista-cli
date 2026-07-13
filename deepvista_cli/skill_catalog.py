"""Sync + lazy-load logic for the DeepVista remote skill catalog.

The catalog is a set of server-managed Skills. We distribute them to Claude
Code / opencode / Cursor / Codex as thin **SKILL.md stubs** under the user's
agent skills directory (default `~/.claude/skills/`). Each stub is just
frontmatter plus a `` !`deepvista skill load <id>` `` preprocessor directive.

Content lives on the server. It is fetched at skill-invocation time (not at
sync time) so the catalog is always fresh and the on-disk footprint stays
small.

Public surface:

- ``sync_catalog(...)``          — diff server → on-disk stubs, apply changes.
- ``load_skill_body(...)``       — fetch a single skill body, cached briefly.
- ``slugify_for_dir(title)``     — stable dir-name slug for a server title.
- ``build_stub_markdown(meta)``  — SKILL.md body for a stub.

The module has no CLI dependency — `deepvista_cli.commands.skill` wraps it
with Click. Tests target the functions here directly.
"""

from __future__ import annotations

import hashlib
import re
import shutil
import time
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from deepvista_cli.config import CONFIG_DIR
from deepvista_cli.utils import load_json_state, save_json_state

# ---------------------------------------------------------------------------
# Defaults & constants
# ---------------------------------------------------------------------------

DEFAULT_TARGET_DIR = Path.home() / ".claude" / "skills"
DEFAULT_STUB_PREFIX = "dv-"
DEFAULT_LIMIT = 30
DEFAULT_THROTTLE_MIN = 60
DEFAULT_BODY_CACHE_TTL_SEC = 300

CATALOG_STATE_FILE = CONFIG_DIR / "catalog-state.json"
BODY_CACHE_DIR = CONFIG_DIR / "cache" / "skill-bodies"

# Marker embedded in every stub so we can tell DeepVista-managed stubs apart
# from user-authored skills that happen to share our dir prefix.
STUB_MARKER = "x-deepvista-catalog"

_SLUG_RE = re.compile(r"[^a-z0-9]+")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SkillMeta:
    """Subset of a server skill card needed to produce a stub."""

    id: str
    title: str
    description: str
    updated_at: str = ""
    tags: tuple[str, ...] = ()

    @classmethod
    def from_card(cls, card: dict[str, Any]) -> SkillMeta:
        return cls(
            id=str(card.get("id", "")),
            title=str(card.get("title", "") or ""),
            description=str(card.get("description", "") or card.get("summary", "") or ""),
            updated_at=str(card.get("updated_at", "") or ""),
            tags=tuple(card.get("tags") or ()),
        )


@dataclass
class SyncPlan:
    """Planned mutations to converge the target dir on server state."""

    to_add: list[SkillMeta] = field(default_factory=list)
    to_update: list[SkillMeta] = field(default_factory=list)
    to_remove: list[str] = field(default_factory=list)  # prefixed dir names
    unchanged: int = 0
    # Maps server id → resolved dir name (handles duplicate-title collisions).
    # Populated by ``compute_plan`` and consumed by ``apply_plan``.
    dir_names: dict[str, str] = field(default_factory=dict)

    def is_empty(self) -> bool:
        return not (self.to_add or self.to_update or self.to_remove)

    def summary(self) -> dict[str, Any]:
        return {
            "added": len(self.to_add),
            "updated": len(self.to_update),
            "removed": len(self.to_remove),
            "unchanged": self.unchanged,
            "total_server": len(self.to_add) + len(self.to_update) + self.unchanged,
        }


# ---------------------------------------------------------------------------
# Client protocol (so tests can inject a fake without importing httpx)
# ---------------------------------------------------------------------------


class _CatalogClient(Protocol):
    def post(self, path: str, body: dict | None = None) -> Any: ...


# ---------------------------------------------------------------------------
# Slugs, hashes, and stub rendering
# ---------------------------------------------------------------------------


def slugify_for_dir(title: str, *, fallback: str = "skill") -> str:
    """Turn a free-form title into a filesystem-safe, stable slug.

    Keeps lowercase ASCII + digits; collapses every other run into ``-``.
    Strips leading/trailing hyphens. Falls back to ``fallback`` if the title
    slugifies to empty (e.g. pure CJK — the server's slug field is preferred
    for those).
    """
    norm = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()
    slug = _SLUG_RE.sub("-", norm.lower()).strip("-")
    return slug or fallback


def _description_for_frontmatter(desc: str, max_len: int = 400) -> str:
    """Collapse whitespace and cap description so stubs stay tidy."""
    cleaned = " ".join(desc.split())
    if len(cleaned) <= max_len:
        return cleaned
    # Cut on a word boundary where possible.
    clipped = cleaned[: max_len - 1].rstrip()
    if " " in clipped:
        clipped = clipped.rsplit(" ", 1)[0].rstrip()
    return clipped + "…"


def build_stub_markdown(meta: SkillMeta, *, prefix: str = DEFAULT_STUB_PREFIX) -> str:
    """Render the SKILL.md body for a catalog stub.

    The body uses ``!`deepvista skill load <id>` `` for agents that preprocess
    shell commands in skill bodies (Claude Code). A plain-English fallback
    covers agents without that preprocessor — the model reads the body and
    executes the command via the Bash tool.
    """
    name = f"{prefix}{slugify_for_dir(meta.title, fallback=meta.id[:8])}"
    description = _description_for_frontmatter(meta.description) or meta.title

    # YAML frontmatter is written by hand to avoid pulling in PyYAML.
    # `x-deepvista-*` fields are informational; Claude Code ignores unknown keys.
    frontmatter = [
        "---",
        f"name: {name}",
        "license: Apache-2.0",
        f"description: {_yaml_inline_string(description)}",
        f"{STUB_MARKER}: true",
        f"x-deepvista-id: {meta.id}",
    ]
    if meta.updated_at:
        frontmatter.append(f"x-deepvista-updated-at: {meta.updated_at}")
    if meta.tags:
        tag_list = ", ".join(_yaml_inline_string(t) for t in meta.tags)
        frontmatter.append(f"x-deepvista-tags: [{tag_list}]")
    frontmatter.append("---")

    body = f"""\
<!-- DeepVista remote skill. Body is fetched at invocation time.
     Server id: {meta.id} -->

!`deepvista skill load {meta.id}`

If the `!`-command above did not execute (for agents without shell-command
preprocessing in SKILL.md bodies), run the following yourself and follow the
printed instructions:

```
deepvista skill load {meta.id}
```
"""
    return "\n".join(frontmatter) + "\n\n" + body


def _yaml_inline_string(value: str) -> str:
    """Quote a value for safe inline YAML.

    We always double-quote to sidestep special chars (``:``, leading ``-``,
    etc.). Escape embedded backslashes and double quotes.
    """
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def stub_dir_name(meta: SkillMeta, *, prefix: str = DEFAULT_STUB_PREFIX) -> str:
    """Directory name for a stub, including prefix."""
    return f"{prefix}{slugify_for_dir(meta.title, fallback=meta.id[:8])}"


def stub_content_hash(markdown: str) -> str:
    """Stable hash of stub content for diffing."""
    return hashlib.sha256(markdown.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# State file — tracks which stubs we own so we can safely remove them
# ---------------------------------------------------------------------------


def load_state(path: Path = CATALOG_STATE_FILE) -> dict[str, Any]:
    """Load the last-sync state. Returns {} when missing or corrupt."""
    return load_json_state(path)


def save_state(state: dict[str, Any], path: Path = CATALOG_STATE_FILE) -> None:
    """Persist the sync state. Creates parent dirs on demand."""
    save_json_state(path, state)


# ---------------------------------------------------------------------------
# Plan + apply
# ---------------------------------------------------------------------------


def _read_existing_hash(stub_path: Path) -> str | None:
    try:
        return stub_content_hash(stub_path.read_text(encoding="utf-8"))
    except OSError:
        return None


def _resolve_dir_names(server_skills: list[SkillMeta], prefix: str) -> dict[str, str]:
    """Map server skill id → stub dir name, disambiguating duplicate titles.

    Server data occasionally contains two skills with identical titles (e.g.
    a fork or a server-side duplicate). Without disambiguation they'd collide
    into the same dir and one would overwrite the other. On collision we
    append a short ID suffix to the loser's slug.
    """
    resolved: dict[str, str] = {}
    used: set[str] = set()
    for meta in server_skills:
        base = stub_dir_name(meta, prefix=prefix)
        candidate = base
        if candidate in used:
            candidate = f"{base}-{meta.id[:6]}"
        used.add(candidate)
        resolved[meta.id] = candidate
    return resolved


def compute_plan(
    server_skills: list[SkillMeta],
    *,
    target: Path,
    prefix: str,
    state: dict[str, Any],
) -> SyncPlan:
    """Diff server state against on-disk stubs and previous sync state.

    `state["stubs"]` (from a prior sync) lists `{id, dir_name, content_hash}`.
    We intersect server ids, previous ids, and the current target dir to
    figure out what to add, update, and remove.

    Only stubs we've previously written are removed — we never touch skills
    the user installed by hand, even if they share our prefix.
    """
    plan = SyncPlan()
    server_by_id = {s.id: s for s in server_skills}

    previous_stubs: dict[str, dict[str, Any]] = {
        entry["id"]: entry for entry in state.get("stubs", []) if entry.get("id")
    }

    dir_names = _resolve_dir_names(server_skills, prefix)
    plan.dir_names = dir_names

    for meta in server_skills:
        dir_name = dir_names[meta.id]
        stub_path = target / dir_name / "SKILL.md"
        desired = build_stub_markdown(meta, prefix=prefix)
        desired_hash = stub_content_hash(desired)

        prev = previous_stubs.get(meta.id)
        on_disk_hash = _read_existing_hash(stub_path)

        # If the dir changed name (title changed → slug changed), the old
        # stub dir is an orphan that we should remove.
        if prev and prev.get("dir_name") and prev["dir_name"] != dir_name:
            plan.to_remove.append(prev["dir_name"])

        if on_disk_hash is None:
            plan.to_add.append(meta)
        elif on_disk_hash != desired_hash:
            plan.to_update.append(meta)
        else:
            plan.unchanged += 1

    # Stubs we owned last time that the server no longer returns → remove.
    for prev_id, prev in previous_stubs.items():
        if prev_id in server_by_id:
            continue
        dir_name = prev.get("dir_name")
        if dir_name and dir_name not in plan.to_remove:
            plan.to_remove.append(dir_name)

    return plan


def apply_plan(
    plan: SyncPlan,
    *,
    target: Path,
    prefix: str,
    all_server_skills: list[SkillMeta] | None = None,
) -> dict[str, Any]:
    """Apply adds/updates/removes. Returns the new ``stubs`` state list.

    ``all_server_skills`` should be the full server-side catalog so that state
    tracks every stub currently on disk, not just the delta from this sync.
    Without it, state drifts: unchanged stubs get forgotten and a later
    target-switch can't clean them up. Falls back to just the plan's adds +
    updates for callers that only have the diff on hand (tests).
    """
    target.mkdir(parents=True, exist_ok=True)

    touched: set[str] = set()
    new_stubs: list[dict[str, Any]] = []

    for meta in plan.to_add + plan.to_update:
        # Prefer the dir name resolved by compute_plan (which handles
        # duplicate-title collisions). Fall back to the deterministic
        # slug when a caller hand-builds a plan without running diff.
        dir_name = plan.dir_names.get(meta.id) or stub_dir_name(meta, prefix=prefix)
        stub_dir = target / dir_name
        stub_dir.mkdir(parents=True, exist_ok=True)
        content = build_stub_markdown(meta, prefix=prefix)
        (stub_dir / "SKILL.md").write_text(content, encoding="utf-8")
        new_stubs.append(
            {
                "id": meta.id,
                "dir_name": dir_name,
                "title": meta.title,
                "content_hash": stub_content_hash(content),
                "updated_at": meta.updated_at,
            }
        )
        touched.add(meta.id)

    # Record entries for unchanged stubs too so state reflects everything
    # currently on disk — required for correct migration on target change.
    for meta in all_server_skills or []:
        if meta.id in touched:
            continue
        dir_name = plan.dir_names.get(meta.id) or stub_dir_name(meta, prefix=prefix)
        stub_path = target / dir_name / "SKILL.md"
        try:
            existing_hash = stub_content_hash(stub_path.read_text(encoding="utf-8"))
        except OSError:
            continue  # expected file missing — will be added next sync
        new_stubs.append(
            {
                "id": meta.id,
                "dir_name": dir_name,
                "title": meta.title,
                "content_hash": existing_hash,
                "updated_at": meta.updated_at,
            }
        )

    for dir_name in plan.to_remove:
        stub_dir = target / dir_name
        if not stub_dir.exists():
            continue
        if not _is_safe_catalog_dir(stub_dir, prefix):
            # Refuse to delete dirs we don't recognise. Belt-and-braces against
            # accidents where a user renames a stub prefix or points `--target`
            # at the wrong place.
            continue
        shutil.rmtree(stub_dir, ignore_errors=True)

    return {"stubs": new_stubs}


def _is_safe_catalog_dir(path: Path, prefix: str) -> bool:
    """A dir is safe to delete iff it's prefixed AND its SKILL.md carries our marker."""
    if not path.name.startswith(prefix):
        return False
    skill_md = path / "SKILL.md"
    if not skill_md.exists():
        return False
    try:
        head = skill_md.read_text(encoding="utf-8")[:2000]
    except OSError:
        return False
    return STUB_MARKER in head


# ---------------------------------------------------------------------------
# High-level sync orchestration
# ---------------------------------------------------------------------------


def _throttled(state: dict[str, Any], throttle_min: int) -> bool:
    last = state.get("last_sync_epoch")
    if not isinstance(last, int | float):
        return False
    age_min = (time.time() - last) / 60
    return age_min < throttle_min


def _catalog_stubs_missing(target: Path, prefix: str, state: dict[str, Any]) -> bool:
    """True if state expects stubs on disk but the target is empty of them.

    Triggers a re-sync even when throttled — handles cases where an external
    process wiped the target dir (plugin marketplace update, manual cleanup,
    user switched machines, etc.) so the catalog recovers on the next run.
    """
    expected = state.get("stubs") or []
    if not expected:
        return False
    try:
        actual = [p for p in target.iterdir() if p.is_dir() and p.name.startswith(prefix)]
    except OSError:
        return True  # target missing entirely
    return len(actual) < len(expected) // 2  # >50% missing → treat as wiped


def _cleanup_old_target(
    old_target: Path,
    prefix: str,
    previous_stubs: list[dict[str, Any]],
) -> list[str]:
    """Remove catalog stubs from a previous target when the target changes.

    Only deletes dirs that carry our marker, using the same safety check as
    ``apply_plan``. Returns the list of dir names that were actually removed
    (for reporting).
    """
    removed: list[str] = []
    for entry in previous_stubs:
        dir_name = entry.get("dir_name")
        if not dir_name:
            continue
        stub_dir = old_target / dir_name
        if not stub_dir.exists() or not _is_safe_catalog_dir(stub_dir, prefix):
            continue
        shutil.rmtree(stub_dir, ignore_errors=True)
        removed.append(dir_name)
    return removed


def _fetch_server_skills(
    client: _CatalogClient,
    *,
    limit: int,
) -> list[SkillMeta]:
    """Pull up to ``limit`` skills from the server via /get_context_cards.

    Queries `card_type="skill"` — the canonical type for user-installed and
    synthesized skill cards.
    """
    data = client.post(
        "/get_context_cards",
        {"card_type": "skill", "limit": limit, "page_number": 1},
    )
    cards = data.get("cards") or []
    return [SkillMeta.from_card(card) for card in cards if card.get("id")]


def sync_catalog(
    client: _CatalogClient,
    *,
    target: Path = DEFAULT_TARGET_DIR,
    prefix: str = DEFAULT_STUB_PREFIX,
    limit: int = DEFAULT_LIMIT,
    throttle_min: int = DEFAULT_THROTTLE_MIN,
    force: bool = False,
    dry_run: bool = False,
    state_path: Path = CATALOG_STATE_FILE,
) -> dict[str, Any]:
    """Run one sync pass. Returns a structured result dict.

    On skip (throttle), returns ``{"skipped": "throttled", ...}`` without hitting
    the network. Network/API errors are the caller's responsibility — they
    propagate unchanged.
    """
    state = load_state(state_path)

    # Detect a target change since the last sync — e.g. user switched from
    # `~/.claude/skills/` to `${CLAUDE_PLUGIN_ROOT}/skills/`. We clean up the
    # stubs we own in the old location so the catalog doesn't double-register.
    old_target_str = state.get("target")
    target_changed = old_target_str is not None and Path(old_target_str) != target

    # Bypass the throttle if stubs are missing from the target (e.g. marketplace
    # auto-update wiped the plugin dir, or user switched targets).
    reconcile_needed = target_changed or _catalog_stubs_missing(target, prefix, state)

    if not force and not reconcile_needed and _throttled(state, throttle_min):
        return {
            "skipped": "throttled",
            "last_sync_epoch": state.get("last_sync_epoch"),
            "throttle_min": throttle_min,
        }

    server_skills = _fetch_server_skills(client, limit=limit)
    plan = compute_plan(server_skills, target=target, prefix=prefix, state=state)

    if dry_run:
        return {
            "dry_run": True,
            "target": str(target),
            "prefix": prefix,
            "plan": {
                "to_add": [m.title for m in plan.to_add],
                "to_update": [m.title for m in plan.to_update],
                "to_remove": plan.to_remove,
                "unchanged": plan.unchanged,
            },
            "summary": plan.summary(),
        }

    migrated: list[str] = []
    if target_changed and old_target_str:
        migrated = _cleanup_old_target(Path(old_target_str), prefix, state.get("stubs") or [])

    new_state_fragment = apply_plan(plan, target=target, prefix=prefix, all_server_skills=server_skills)

    state.update(new_state_fragment)
    state["last_sync_epoch"] = int(time.time())
    state["target"] = str(target)
    state["prefix"] = prefix
    state["limit"] = limit
    save_state(state, state_path)

    result: dict[str, Any] = {
        "ok": True,
        "target": str(target),
        "prefix": prefix,
        "summary": plan.summary(),
    }
    if migrated:
        result["migrated_from"] = old_target_str
        result["migrated_stubs_removed"] = migrated
    return result


# ---------------------------------------------------------------------------
# Lazy body loading (for `deepvista skill load`)
# ---------------------------------------------------------------------------


def _body_cache_path(skill_id: str, *, root: Path = BODY_CACHE_DIR) -> Path:
    # One file per skill id. The id alone is enough — content is immutable per
    # fetch and cache-bust comes from TTL or `--no-cache`.
    digest = hashlib.sha256(skill_id.encode("utf-8")).hexdigest()[:16]
    return root / f"{digest}.md"


def _cache_fresh(path: Path, ttl_sec: int) -> bool:
    try:
        age = time.time() - path.stat().st_mtime
    except OSError:
        return False
    return age < ttl_sec


def _render_skill_body_markdown(card: dict[str, Any]) -> str:
    """Turn a server skill card into a SKILL.md-style body.

    The server returns the authoritative prose in `description` or `content`.
    We prefer explicit fields but tolerate either. A frontmatter block is
    added so the output is a well-formed SKILL.md if an agent wants to save
    it to disk.
    """
    title = str(card.get("title") or "").strip() or "Skill"
    desc_short = str(card.get("summary") or "").strip()
    body = str(card.get("content") or card.get("description") or "").strip()

    frontmatter = [
        "---",
        f"name: {_yaml_inline_string(title)}",
        f"description: {_yaml_inline_string(_description_for_frontmatter(desc_short or title))}",
        f"x-deepvista-id: {card.get('id', '')}",
        "---",
    ]

    parts = ["\n".join(frontmatter), "", f"# {title}"]
    if body:
        parts.extend(["", body])
    return "\n".join(parts).rstrip() + "\n"


def load_skill_body(
    client: _CatalogClient,
    skill_id: str,
    *,
    use_cache: bool = True,
    ttl_sec: int = DEFAULT_BODY_CACHE_TTL_SEC,
    cache_root: Path = BODY_CACHE_DIR,
) -> str:
    """Return the full SKILL.md body for ``skill_id``.

    Caches the rendered body on disk for ``ttl_sec`` seconds to keep repeated
    invocations of the same skill within a session cheap.
    """
    cache_path = _body_cache_path(skill_id, root=cache_root)
    if use_cache and _cache_fresh(cache_path, ttl_sec):
        try:
            return cache_path.read_text(encoding="utf-8")
        except OSError:
            pass  # fall through to refetch

    data = client.post("/get_context_card", {"card_id": skill_id, "card_type": "skill"})
    card = data.get("card") or data
    rendered = _render_skill_body_markdown(card)

    try:
        cache_root.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(rendered, encoding="utf-8")
    except OSError:
        pass  # cache is best-effort

    return rendered


# ---------------------------------------------------------------------------
# Public helpers re-exported for tests & commands
# ---------------------------------------------------------------------------

__all__ = [
    "BODY_CACHE_DIR",
    "CATALOG_STATE_FILE",
    "DEFAULT_BODY_CACHE_TTL_SEC",
    "DEFAULT_LIMIT",
    "DEFAULT_STUB_PREFIX",
    "DEFAULT_TARGET_DIR",
    "DEFAULT_THROTTLE_MIN",
    "STUB_MARKER",
    "SkillMeta",
    "SyncPlan",
    "apply_plan",
    "build_stub_markdown",
    "compute_plan",
    "load_skill_body",
    "load_state",
    "save_state",
    "slugify_for_dir",
    "stub_content_hash",
    "stub_dir_name",
    "sync_catalog",
]
