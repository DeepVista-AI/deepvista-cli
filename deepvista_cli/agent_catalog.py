"""Export DeepVista managed agents as Claude Code plugin agent definitions.

DV-836: a Claude Code plugin discovers subagents from ``agents/<name>.md`` files
(frontmatter + a system prompt body). Each registered DeepVista managed agent
becomes one runtime subagent so the user can call it inline:

    @my-agent summarize the DeepVista marketing progress this week

This module mirrors :mod:`deepvista_cli.skill_catalog`: it fetches server state,
diffs it against the files we wrote last time, and converges the target dir —
idempotently, throttled, and safe to wire into a SessionStart hook (the command
wrapper swallows all errors and exits 0).

Generated files are named ``<prefix><slug>.md`` (default prefix ``dv-``) so they
are namespaced away from any hand-curated agent the plugin ships, and so a
``.gitignore`` of ``dv-*.md`` keeps them out of plugin PR diffs. The invocation
handle (frontmatter ``name``) is the bare slug. A curated agent that already
claims a name always wins — we never overwrite or delete files we didn't author.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from deepvista_cli.config import CONFIG_DIR

DEFAULT_TARGET_DIR = Path.home() / ".claude" / "agents"
DEFAULT_PREFIX = "dv-"
DEFAULT_LIMIT = 50
DEFAULT_THROTTLE_MIN = 60

AGENT_DEFS_STATE_FILE = CONFIG_DIR / "agent-defs-state.json"

# Marker embedded in every generated definition so we can tell DeepVista-managed
# agents apart from hand-curated ones that happen to share our filename prefix.
AGENT_MARKER = "x-deepvista-agent"

_SLUG_RE = re.compile(r"[^a-z0-9]+")
_NAME_RE = re.compile(r"^name:\s*(.+?)\s*$", re.MULTILINE)

_DEFAULT_COLOR = "pink"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AgentDefMeta:
    """One managed agent, ready to render as a subagent."""

    agent_name: str
    agent_id: str
    agent_type: str = ""
    updated_at: str = ""
    # Plain-text system prompt baked verbatim as the subagent body. Sourced
    # from the managed agent's ``config.system_prompt`` (preferred) or its
    # older ``config.soul`` (fallback).
    system_prompt: str = ""

    @property
    def slug(self) -> str:
        """Filesystem- and handle-safe slug (the subagent ``name``)."""
        return slugify(self.agent_name, fallback=self.agent_id[:8] or "agent")


@dataclass
class SyncPlan:
    """Planned mutations to converge the target dir on server state."""

    to_add: list[AgentDefMeta] = field(default_factory=list)
    to_update: list[AgentDefMeta] = field(default_factory=list)
    to_remove: list[str] = field(default_factory=list)  # prefixed file names
    skipped_curated: list[str] = field(default_factory=list)  # slugs a curated file owns
    unchanged: int = 0

    def is_empty(self) -> bool:
        return not (self.to_add or self.to_update or self.to_remove)

    def summary(self) -> dict[str, Any]:
        return {
            "added": len(self.to_add),
            "updated": len(self.to_update),
            "removed": len(self.to_remove),
            "unchanged": self.unchanged,
            "skipped_curated": len(self.skipped_curated),
        }


class _AgentClient(Protocol):
    def get(self, path: str, params: dict | None = None) -> Any: ...


# ---------------------------------------------------------------------------
# Slugs, hashes, and definition rendering
# ---------------------------------------------------------------------------


def slugify(value: str, *, fallback: str = "agent") -> str:
    """Lowercase ASCII slug; collapse other runs into ``-``; strip edges."""
    norm = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    slug = _SLUG_RE.sub("-", norm.lower()).strip("-")
    return slug or fallback


def file_name(meta: AgentDefMeta, *, prefix: str = DEFAULT_PREFIX) -> str:
    """Definition filename including prefix, e.g. ``dv-my-agent.md``."""
    return f"{prefix}{meta.slug}.md"


def _yaml_inline_string(value: str) -> str:
    """Double-quote a value for safe inline YAML."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def build_agent_markdown(meta: AgentDefMeta) -> str:
    """Render the full subagent definition for one managed agent.

    Frontmatter drives Claude Code's auto-delegation (``description``) and the
    invocation handle (``name`` == bare slug). The ``x-deepvista-*`` keys are
    informational; Claude Code ignores unknown keys but we read ``AGENT_MARKER``
    back to decide what we may safely delete.
    """
    display = meta.agent_name.strip() or meta.slug
    description = (
        f"DeepVista managed agent “{display}”. Use PROACTIVELY for tasks this agent "
        "is configured to handle. Grounds every deliverable in real DeepVista notes "
        "and knowledge-base cards before acting."
    )

    frontmatter = [
        "---",
        f"name: {meta.slug}",
        f"description: {_yaml_inline_string(description)}",
        "tools: Read, Write, Edit, Bash, WebFetch, WebSearch",
        "model: sonnet",
        f"color: {_DEFAULT_COLOR}",
        "maxTurns: 25",
        "skills: deepvista",
        f"{AGENT_MARKER}: true",
        f"x-deepvista-agent-name: {_yaml_inline_string(display)}",
    ]
    if meta.agent_id:
        frontmatter.append(f"x-deepvista-agent-id: {meta.agent_id}")
    if meta.updated_at:
        frontmatter.append(f"x-deepvista-updated-at: {meta.updated_at}")
    frontmatter.append("---")

    if meta.system_prompt.strip():
        prompt_body = (
            "<!-- Generated by `deepvista agents export` from the configured system\n"
            f"     prompt of your “{display}” managed agent · agent id: {meta.agent_id or 'n/a'}.\n"
            "     Edit it in DeepVista — local changes are overwritten on the next sync. -->\n\n"
            f"{meta.system_prompt.strip()}\n"
        )
        return "\n".join(frontmatter) + "\n\n" + prompt_body

    body = f"""\
<!-- Generated by `deepvista agents export` from a DeepVista managed agent.
     Do not edit by hand — changes are overwritten on the next sync.
     Agent: {display} · agent id: {meta.agent_id or "n/a"} -->

You are **{display}**, a DeepVista managed agent working as an isolated
subagent. You receive one task, complete it end to end in your own context, and
return a single self-contained result to the main agent.

The `deepvista` skill is preloaded into your context — use it as the source of
truth for the CLI. Prefer grounding work in the user's own material (notes,
knowledge-base cards) over inventing claims.

## Operating procedure

1. **Frame.** State the goal in one line. If the task is ambiguous on a detail
   that changes the outcome, make the most reasonable assumption and flag it —
   do not stall (you cannot ask the user mid-run).
2. **Research.** Pull relevant context before acting:
   - `deepvista notes list` and `deepvista kb grep "<term>"` for existing facts,
     prior decisions, and context.
   - `deepvista chat "<question>"` to ask the DeepVista agent for grounded
     background when notes are thin.
   - `WebSearch` / `WebFetch` only to verify external facts.
3. **Work.** Produce the deliverable. Be concrete and specific.
4. **Self-review.** Cut anything that does not earn its place. Verify every
   factual claim traces to a note, a knowledge-base card, or a cited source.
5. **Capture.** Save any reusable, durable fact you established back with
   `deepvista notes +quick "<fact>"` so future runs inherit it.

## Output format

Return, in this order:
1. **Frame** — one line (goal), plus any assumption you flagged.
2. **Deliverable** — the result, ready to use.
3. **Sources** — notes / KB cards / URLs the claims rest on.
4. **Captured** — any `deepvista notes +quick` facts you saved (or "none").

Keep the result skimmable; the main agent will relay it to the user.
"""
    return "\n".join(frontmatter) + "\n\n" + body


def content_hash(markdown: str) -> str:
    """Stable hash of a rendered definition for diffing."""
    return hashlib.sha256(markdown.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Server fetch
# ---------------------------------------------------------------------------


def metas_from_agents(agents: list[dict[str, Any]]) -> list[AgentDefMeta]:
    """Map managed agents to export metadata, one entry per agent."""
    result: list[AgentDefMeta] = []
    for agent in agents:
        agent_id = str(agent.get("id") or "").strip()
        if not agent_id:
            continue
        config = agent.get("config") or {}
        prompt_body = str(config.get("system_prompt") or config.get("soul") or "").strip()
        result.append(
            AgentDefMeta(
                agent_name=str(agent.get("name") or ""),
                agent_id=agent_id,
                agent_type=str(agent.get("agent_type") or ""),
                updated_at=str(agent.get("updated_at") or ""),
                system_prompt=prompt_body,
            )
        )
    return sorted(result, key=lambda m: m.slug)


def _fetch_server_agents(client: _AgentClient, *, limit: int) -> list[AgentDefMeta]:
    """Pull managed agents via ``GET /agents``."""
    data = client.get("/agents", params={"limit": limit})
    agents = data.get("agents") or []
    return metas_from_agents(agents)


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------


def load_state(path: Path = AGENT_DEFS_STATE_FILE) -> dict[str, Any]:
    """Load the last-sync state. Returns {} when missing or corrupt."""
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_state(state: dict[str, Any], path: Path = AGENT_DEFS_STATE_FILE) -> None:
    """Persist the sync state. Creates parent dirs on demand."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Curated-file detection + safety
# ---------------------------------------------------------------------------


def _is_ours(path: Path, prefix: str) -> bool:
    """True iff ``path`` is a definition we authored (prefix + our marker)."""
    if not (path.name.startswith(prefix) and path.suffix == ".md"):
        return False
    try:
        head = path.read_text(encoding="utf-8")[:2000]
    except OSError:
        return False
    return AGENT_MARKER in head


def curated_names(target: Path, prefix: str) -> set[str]:
    """Names claimed by hand-curated (non-generated) agent files in ``target``.

    We read each ``*.md`` that we did not author and collect its frontmatter
    ``name``. Generation skips any slug that collides with one of these.
    """
    names: set[str] = set()
    try:
        entries = list(target.glob("*.md"))
    except OSError:
        return names
    for path in entries:
        try:
            head = path.read_text(encoding="utf-8")[:2000]
        except OSError:
            continue
        if AGENT_MARKER in head:
            continue  # one of ours, not curated
        match = _NAME_RE.search(head)
        if match:
            names.add(match.group(1).strip().strip("\"'").lower())
    return names


# ---------------------------------------------------------------------------
# Plan + apply
# ---------------------------------------------------------------------------


def _read_existing_hash(path: Path) -> str | None:
    try:
        return content_hash(path.read_text(encoding="utf-8"))
    except OSError:
        return None


def compute_plan(
    server_metas: list[AgentDefMeta],
    *,
    target: Path,
    prefix: str,
    state: dict[str, Any],
) -> SyncPlan:
    """Diff server agents against on-disk files and the previous sync state.

    Only files we previously wrote are removed — curated agents and unrelated
    files are never touched, even if they share our prefix.
    """
    plan = SyncPlan()
    reserved = curated_names(target, prefix)
    previous: dict[str, dict[str, Any]] = {e["agent_id"]: e for e in state.get("defs", []) if e.get("agent_id")}
    server_ids = {m.agent_id for m in server_metas}

    for meta in server_metas:
        if meta.slug in reserved:
            plan.skipped_curated.append(meta.slug)
            continue
        path = target / file_name(meta, prefix=prefix)
        desired_hash = content_hash(build_agent_markdown(meta))
        on_disk = _read_existing_hash(path)
        if on_disk is None:
            plan.to_add.append(meta)
        elif on_disk != desired_hash:
            plan.to_update.append(meta)
        else:
            plan.unchanged += 1

    skipped = set(plan.skipped_curated)
    for agent_id, entry in previous.items():
        fname = entry.get("file_name")
        if not fname:
            continue
        slug = slugify(entry.get("agent_name") or "", fallback=agent_id[:8] or "agent")
        gone = agent_id not in server_ids
        now_curated = slug in skipped
        if (gone or now_curated) and fname not in plan.to_remove:
            plan.to_remove.append(fname)

    return plan


def apply_plan(
    plan: SyncPlan,
    *,
    target: Path,
    prefix: str,
    all_server_metas: list[AgentDefMeta] | None = None,
) -> dict[str, Any]:
    """Apply adds/updates/removes. Returns the new ``defs`` state list."""
    target.mkdir(parents=True, exist_ok=True)

    touched: set[str] = set()
    new_defs: list[dict[str, Any]] = []

    for meta in plan.to_add + plan.to_update:
        fname = file_name(meta, prefix=prefix)
        content = build_agent_markdown(meta)
        (target / fname).write_text(content, encoding="utf-8")
        new_defs.append(
            {
                "agent_id": meta.agent_id,
                "agent_name": meta.agent_name,
                "file_name": fname,
                "content_hash": content_hash(content),
                "updated_at": meta.updated_at,
            }
        )
        touched.add(meta.agent_id)

    for meta in all_server_metas or []:
        if meta.agent_id in touched or meta.slug in plan.skipped_curated:
            continue
        path = target / file_name(meta, prefix=prefix)
        existing = _read_existing_hash(path)
        if existing is None:
            continue
        new_defs.append(
            {
                "agent_id": meta.agent_id,
                "agent_name": meta.agent_name,
                "file_name": file_name(meta, prefix=prefix),
                "content_hash": existing,
                "updated_at": meta.updated_at,
            }
        )

    for fname in plan.to_remove:
        path = target / fname
        if not path.exists():
            continue
        if not _is_ours(path, prefix):
            continue
        path.unlink()

    return {"defs": new_defs}


# ---------------------------------------------------------------------------
# High-level orchestration
# ---------------------------------------------------------------------------


def _throttled(state: dict[str, Any], throttle_min: int) -> bool:
    last = state.get("last_sync_epoch")
    if not isinstance(last, int | float):
        return False
    return (time.time() - last) / 60 < throttle_min


def _defs_missing(target: Path, prefix: str, state: dict[str, Any]) -> bool:
    """True if state expects files on disk but the target lost most of them."""
    expected = state.get("defs") or []
    if not expected:
        return False
    try:
        actual = [p for p in target.glob(f"{prefix}*.md") if _is_ours(p, prefix)]
    except OSError:
        return True
    return len(actual) < len(expected) // 2


def sync_agent_defs(
    client: _AgentClient,
    *,
    target: Path = DEFAULT_TARGET_DIR,
    prefix: str = DEFAULT_PREFIX,
    limit: int = DEFAULT_LIMIT,
    throttle_min: int = DEFAULT_THROTTLE_MIN,
    force: bool = False,
    dry_run: bool = False,
    state_path: Path = AGENT_DEFS_STATE_FILE,
) -> dict[str, Any]:
    """Run one export pass. Returns a structured result dict."""
    state = load_state(state_path)
    reconcile = _defs_missing(target, prefix, state)

    if not force and not reconcile and _throttled(state, throttle_min):
        return {
            "skipped": "throttled",
            "last_sync_epoch": state.get("last_sync_epoch"),
            "throttle_min": throttle_min,
        }

    server_metas = _fetch_server_agents(client, limit=limit)
    plan = compute_plan(server_metas, target=target, prefix=prefix, state=state)

    if dry_run:
        return {
            "dry_run": True,
            "target": str(target),
            "prefix": prefix,
            "plan": {
                "to_add": [m.slug for m in plan.to_add],
                "to_update": [m.slug for m in plan.to_update],
                "to_remove": plan.to_remove,
                "skipped_curated": plan.skipped_curated,
                "unchanged": plan.unchanged,
            },
            "summary": plan.summary(),
        }

    new_state_fragment = apply_plan(plan, target=target, prefix=prefix, all_server_metas=server_metas)

    state.update(new_state_fragment)
    state["last_sync_epoch"] = int(time.time())
    state["target"] = str(target)
    state["prefix"] = prefix
    save_state(state, state_path)

    return {
        "ok": True,
        "target": str(target),
        "prefix": prefix,
        "summary": plan.summary(),
    }
