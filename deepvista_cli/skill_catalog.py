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
import json
import logging
import re
import shutil
import time
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from deepvista_cli import bundle
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

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


def _trigger_description(card: dict[str, Any]) -> str:
    """The one line an agent reads to decide whether to load this skill.

    Order matters (DV-1869). For a skill card the ``description`` column *is*
    the whole SKILL.md, so taking it verbatim produced a stub whose
    ``description`` opened with flattened YAML — ``"--- name: narrated-browser
    description: … type: tool execution: stateless…"`` — burning the 400-char
    budget on frontmatter punctuation before reaching the real trigger text, and
    trailing off into the ``files:`` manifest.

    The skill's own frontmatter ``description`` is the right answer. The server
    already parses it into ``attributes``, so prefer that; fall back to parsing
    the body, then to the short ``summary``/``snippet``, and only then to the raw
    body for cards with no frontmatter at all.
    """
    attributes = card.get("attributes")
    if isinstance(attributes, dict):
        from_attributes = str(attributes.get("description") or "").strip()
        if from_attributes:
            return from_attributes

    body = str(card.get("description") or card.get("content") or "")
    from_frontmatter = bundle.parse_frontmatter_scalars(body).get("description", "").strip()
    if from_frontmatter:
        return from_frontmatter

    for key in ("summary", "snippet"):
        value = str(card.get(key) or "").strip()
        if value:
            return value
    return body


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
            description=_trigger_description(card),
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

    # `install_bundle_for_skill` hands this client to `bundle.make_fetcher`, which
    # resolves `dv://` refs over GET — so the catalog protocol has to cover both verbs.
    def get(self, path: str, params: dict | None = None) -> Any: ...


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
        remove_stub_dir(target / dir_name, prefix)

    return {"stubs": new_stubs}


def remove_stub_dir(stub_dir: Path, prefix: str) -> bool:
    """Remove a catalog stub. Returns True when the whole dir went away.

    Deliberately **not** ``rmtree`` (DV-1869). A stub dir doubles as a bundle
    root, so a skill's installed ``scripts/`` live alongside its SKILL.md — and
    blowing the dir away took a working install with it. The symptom was ugly: a
    machine installed a skill's scripts successfully, then lost them at the start
    of the next session when a sync relocated the target, leaving the agent to
    invoke a skill whose files were gone.

    So: delete the stub and the files our own marker says we installed — and only
    while they still match what we wrote, since a differing hash means someone
    edited them. Anything else in the dir is not ours to delete, and if anything
    survives, the directory stays.
    """
    if not stub_dir.exists() or not _is_safe_catalog_dir(stub_dir, prefix):
        # Refuse to touch dirs we don't recognise. Belt-and-braces against
        # accidents where a user renames a stub prefix or points `--target`
        # at the wrong place.
        return False

    installed: dict[str, str] = bundle.read_marker(stub_dir).get("files") or {}
    for path, recorded_sha in installed.items():
        try:
            destination = bundle.safe_destination(stub_dir, path)
        except bundle.BundleError:
            continue
        if destination.exists() and bundle.sha256_file(destination) == recorded_sha:
            destination.unlink(missing_ok=True)

    for name in ("SKILL.md", bundle.MARKER_FILENAME):
        (stub_dir / name).unlink(missing_ok=True)

    # Prune directories the bundle created, deepest first; non-empty ones (a
    # preserved local edit, a file the user dropped in) survive untouched.
    for directory in sorted((p for p in stub_dir.rglob("*") if p.is_dir()), key=lambda p: -len(p.parts)):
        try:
            directory.rmdir()
        except OSError:
            pass
    try:
        stub_dir.rmdir()
        return True
    except OSError:
        logger.info("kept %s — it still holds files we did not install", stub_dir)
        return False


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
    *,
    new_target: Path | None = None,
) -> dict[str, list[str]]:
    """Retire catalog stubs from a previous target when the target changes.

    Only touches dirs that carry our marker, using the same safety check as
    ``apply_plan``. Installed bundle files are **moved** to the corresponding
    stub dir under ``new_target`` first (DV-1869) — a relocation is not a
    deletion, and the old behaviour deleted a working install's scripts on the
    next SessionStart, leaving the agent to invoke a skill whose files were
    gone. Returns the dir names removed and the ones whose bundles moved.
    """
    result: dict[str, list[str]] = {"removed": [], "migrated": []}
    for entry in previous_stubs:
        dir_name = entry.get("dir_name")
        if not dir_name:
            continue
        stub_dir = old_target / dir_name
        if not stub_dir.exists() or not _is_safe_catalog_dir(stub_dir, prefix):
            continue
        if new_target is not None and _move_bundle(stub_dir, new_target / dir_name):
            result["migrated"].append(dir_name)
        if remove_stub_dir(stub_dir, prefix):
            result["removed"].append(dir_name)
    return result


def _move_bundle(source_dir: Path, destination_dir: Path) -> bool:
    """Move an installed bundle (marker + its files) between stub dirs.

    Returns True when anything moved. Files already present at the destination
    are left alone — the new target wins, since a fresh install there is at
    least as current as what we're carrying over.
    """
    installed: dict[str, str] = bundle.read_marker(source_dir).get("files") or {}
    if not installed:
        return False

    moved = False
    for path in installed:
        try:
            source = bundle.safe_destination(source_dir, path)
            destination = bundle.safe_destination(destination_dir, path)
        except bundle.BundleError:
            continue
        if not source.exists() or destination.exists():
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.move(str(source), str(destination))
            moved = True
        except OSError:
            logger.info("could not migrate %s to %s", source, destination)

    marker = source_dir / bundle.MARKER_FILENAME
    destination_marker = destination_dir / bundle.MARKER_FILENAME
    if moved and marker.exists() and not destination_marker.exists():
        destination_marker.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copyfile(marker, destination_marker)
        except OSError:
            logger.info("could not carry the bundle marker to %s", destination_marker)
    return moved


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

    retired: dict[str, list[str]] = {"removed": [], "migrated": []}
    if target_changed and old_target_str:
        retired = _cleanup_old_target(
            Path(old_target_str),
            prefix,
            state.get("stubs") or [],
            new_target=target,
        )

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
    if retired["removed"] or retired["migrated"]:
        result["migrated_from"] = old_target_str
        result["migrated_stubs_removed"] = retired["removed"]
        if retired["migrated"]:
            result["migrated_bundles"] = retired["migrated"]
    return result


# ---------------------------------------------------------------------------
# Lazy body loading (for `deepvista skill load`)
# ---------------------------------------------------------------------------


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

    A card body that is *already* a SKILL.md keeps its own frontmatter rather
    than getting a second block wrapped around it (DV-1869). Prepending
    unconditionally produced two frontmatter blocks, a placeholder
    ``description`` above the real one, and a duplicated title — the agent then
    read storage bookkeeping and YAML punctuation as skill content.
    """
    title = str(card.get("title") or "").strip() or "Skill"
    body = str(card.get("content") or card.get("description") or "").strip()

    # The manifest has already been consumed by the installer; it is not prose.
    body = bundle.strip_manifest(body).strip()

    own = bundle.parse_frontmatter_scalars(body)
    if own:
        # Stamp the id onto the body's existing block instead of adding a second
        # one, so the result stays a single well-formed document.
        return _with_deepvista_id(body, str(card.get("id", "")))

    desc_short = str(card.get("summary") or "").strip()
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


def _with_deepvista_id(body: str, skill_id: str) -> str:
    """Add ``x-deepvista-id`` to a body's own frontmatter, idempotently."""
    if not skill_id:
        return body.rstrip() + "\n"
    lines = body.splitlines()
    close = next((i for i, line in enumerate(lines[1:], start=1) if line.strip() == "---"), None)
    if close is None:
        return body.rstrip() + "\n"
    if any(line.startswith("x-deepvista-id:") for line in lines[1:close]):
        return body.rstrip() + "\n"
    stamped = lines[:close] + [f"x-deepvista-id: {skill_id}"] + lines[close:]
    return "\n".join(stamped).rstrip() + "\n"


def _card_cache_path(skill_id: str, *, root: Path = BODY_CACHE_DIR) -> Path:
    # One file per skill id. The id alone is enough — content is immutable per
    # fetch and cache-bust comes from TTL or `--no-cache`.
    digest = hashlib.sha256(skill_id.encode("utf-8")).hexdigest()[:16]
    return root / f"{digest}.card.json"


def load_skill_card(
    client: _CatalogClient,
    skill_id: str,
    *,
    use_cache: bool = True,
    ttl_sec: int = DEFAULT_BODY_CACHE_TTL_SEC,
    cache_root: Path = BODY_CACHE_DIR,
) -> dict[str, Any]:
    """Fetch a skill card, cached on disk for ``ttl_sec`` seconds.

    The raw card is cached rather than the rendered body (DV-1816) because the
    bundle manifest lives in the card's own frontmatter, which
    :func:`_render_skill_body_markdown` doesn't reproduce.
    """
    cache_path = _card_cache_path(skill_id, root=cache_root)
    if use_cache and _cache_fresh(cache_path, ttl_sec):
        try:
            return json.loads(cache_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass  # fall through to refetch

    data = client.post("/get_context_card", {"card_id": skill_id, "card_type": "skill"})
    card = data.get("card") or data

    try:
        cache_root.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(card), encoding="utf-8")
    except OSError:
        pass  # cache is best-effort

    return card


def render_skill_body(card: dict[str, Any]) -> str:
    """Public alias for rendering a fetched card into a SKILL.md body."""
    return _render_skill_body_markdown(card)


def load_skill_body(
    client: _CatalogClient,
    skill_id: str,
    *,
    use_cache: bool = True,
    ttl_sec: int = DEFAULT_BODY_CACHE_TTL_SEC,
    cache_root: Path = BODY_CACHE_DIR,
) -> str:
    """Return the full SKILL.md body for ``skill_id``."""
    card = load_skill_card(client, skill_id, use_cache=use_cache, ttl_sec=ttl_sec, cache_root=cache_root)
    return _render_skill_body_markdown(card)


def synced_target_dir(state_path: Path | None = None) -> Path:
    """Where sync actually last wrote stubs, not where we'd write them by default.

    The two differ in the common install (DV-1869): the plugin's SessionStart
    hook syncs into ``${CLAUDE_PLUGIN_ROOT}/skills``, while
    ``DEFAULT_TARGET_DIR`` is ``~/.claude/skills``. Installing a bundle next to
    a stub that lives somewhere else meant the payload sat in a directory
    nothing pointed at, and the next sync — seeing a target change — cleaned it
    up. Anything resolving a bundle root has to follow the recorded target.
    """
    # Resolved from the module global inside the body, not via a default
    # argument — the default would bind at import and ignore a redirected
    # CONFIG_DIR (or a test's patch).
    recorded = load_state(state_path or CATALOG_STATE_FILE).get("target")
    if isinstance(recorded, str) and recorded:
        return Path(recorded)
    return DEFAULT_TARGET_DIR


def bundle_root_for(
    skill_id: str, card: dict[str, Any], *, target: Path | None = None, prefix: str = DEFAULT_STUB_PREFIX
) -> Path:
    """Where a skill's bundle lands: its stub directory.

    Prefers the dir name a previous sync recorded — that one already resolved
    duplicate-title collisions — and falls back to the deterministic slug.
    Materializing into the stub dir (not a cache dir) is what lets
    ``scripts/render.py`` resolve relative to the SKILL.md the agent is
    reading, with no absolute-path rewriting.
    """
    root = target or synced_target_dir()
    for entry in load_state().get("stubs", []):
        if entry.get("id") == skill_id and entry.get("dir_name"):
            return root / entry["dir_name"]
    title = str(card.get("title") or "skill")
    return root / f"{prefix}{slugify_for_dir(title, fallback=skill_id[:8])}"


def ensure_skill_bundle(
    client: _CatalogClient,
    skill_id: str,
    card: dict[str, Any],
    *,
    target: Path | None = None,
) -> Path | None:
    """Materialize a skill's bundle if it has one. Returns the root, or ``None``.

    Called at *invocation* time rather than sync time, which is what keeps the
    catalog's lazy-loading property intact: sync still writes only stubs, and
    a skill without a bundle costs nothing. Repeat invocations short-circuit on
    the marker file's ``bundle_sha``.

    Never raises. A failed bundle install degrades to "skill body without its
    scripts", which the agent can report — better than turning every skill
    invocation into a hard error.
    """
    from deepvista_cli import bundle as bundle_mod

    body = str(card.get("content") or card.get("description") or "")
    try:
        files = bundle_mod.parse_bundle_files(body)
    except bundle_mod.BundleError:
        logger.warning("skill %s has an invalid bundle manifest; skipping install", skill_id)
        return None
    if not files:
        return None

    root = bundle_root_for(skill_id, card, target=target)
    if bundle_mod.read_marker(root).get("bundle_sha") == bundle_mod.compute_bundle_sha(files):
        return root

    try:
        bundle_mod.materialize_bundle(files, root, bundle_mod.make_fetcher(client, skill_id))
    except Exception:  # noqa: BLE001 — see docstring
        logger.warning("could not materialize bundle for skill %s", skill_id, exc_info=True)
        return None
    return root


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
    "bundle_root_for",
    "ensure_skill_bundle",
    "load_skill_body",
    "load_skill_card",
    "render_skill_body",
    "load_state",
    "save_state",
    "slugify_for_dir",
    "stub_content_hash",
    "stub_dir_name",
    "sync_catalog",
]
