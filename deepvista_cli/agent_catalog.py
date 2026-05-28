"""Export DeepVista managed agents as Claude Code plugin agent definitions.

DV-836: a Claude Code plugin discovers subagents from ``agents/<name>.md`` files
(frontmatter + a system prompt body). Each registered DeepVista managed agent
carries an open-text ``agent_role`` (DV-832) — ``marketing``, ``sales``,
``engineering``, … — and we turn each distinct role into one runtime subagent
so the user can call it inline:

    @marketing summarize the DeepVista marketing progress this week

This module mirrors :mod:`deepvista_cli.skill_catalog`: it fetches server state,
diffs it against the files we wrote last time, and converges the target dir —
idempotently, throttled, and safe to wire into a SessionStart hook (the command
wrapper swallows all errors and exits 0).

Generated files are named ``<prefix><role>.md`` (default prefix ``dv-``) so they
are namespaced away from any hand-curated agent the plugin ships, and so a
``.gitignore`` of ``dv-*.md`` keeps them out of plugin PR diffs. The invocation
handle (frontmatter ``name``) is the bare role, so ``@marketing`` works
regardless of the filename prefix. A curated agent that already claims a role's
name always wins — we never overwrite or delete files we didn't author.
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

# Roles we never turn into a subagent. ``misc`` is the DV-832 default sentinel
# for "no specific role" — an `@misc` handle is noise, not a specialist.
SKIP_ROLES = frozenset({"misc", ""})

_SLUG_RE = re.compile(r"[^a-z0-9]+")
_NAME_RE = re.compile(r"^name:\s*(.+?)\s*$", re.MULTILINE)

# DV-853: a managed agent's ``config.system_prompt`` may carry a reference to a
# persona Skill context card instead of (or in addition to) the inline
# ``config.soul``. The export resolves the card body and inlines it as the
# subagent's system prompt — same routing/tools frontmatter, persona content
# sourced from the catalog so it's editable from DeepVista without re-syncing.
_PERSONA_REF_RE = re.compile(r"^(?:skill|persona)\s*:\s*([A-Za-z0-9_\-]{4,})\s*$", re.IGNORECASE)

# Per-role persona seed: (title, focus blurb, frontmatter color). The focus
# blurb feeds both the auto-delegation `description` and the body intro. Unknown
# free-text roles fall back to a generic specialist (agent_role is open-text).
ROLE_SPECS: dict[str, tuple[str, str, str]] = {
    "sales": (
        "Sales specialist",
        "pipeline tracking, prospect research, outreach drafts, call prep, and deal-note follow-ups",
        "green",
    ),
    "marketing": (
        "Marketing specialist",
        "launch announcements, landing-page and social copy, positioning, blog posts, and email campaigns",
        "purple",
    ),
    "product": (
        "Product specialist",
        "product specs, roadmap notes, user-research synthesis, release notes, and feature briefs",
        "blue",
    ),
    "engineering": (
        "Engineering specialist",
        "technical design notes, architecture decisions, code-review prep, and incident write-ups",
        "cyan",
    ),
    "hiring": (
        "Hiring specialist",
        "role scorecards, job descriptions, candidate-evaluation notes, and interview kits",
        "orange",
    ),
    "content": (
        "Content specialist",
        "long-form drafts, editing passes, content calendars, and repurposing source material",
        "yellow",
    ),
}
_GENERIC_COLOR = "pink"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AgentRoleMeta:
    """One distinct managed-agent role, ready to render as a subagent."""

    role: str  # raw agent_role, e.g. "marketing"
    agent_name: str  # representative managed-agent display name
    agent_id: str  # representative managed-agent id
    agent_type: str = ""  # e.g. "claude-code"
    updated_at: str = ""
    count: int = 1  # how many managed agents share this role
    system_prompt: str = ""  # custom prompt from the agent's config.soul (DV-836); baked as the body
    # DV-853: optional persona skill-card id resolved at export time. When set,
    # the resolved card body wins over ``system_prompt`` (a persona card is
    # treated as the authoritative source). The id is kept in metadata for
    # provenance even after resolution.
    persona_card_id: str = ""

    @property
    def slug(self) -> str:
        """Filesystem- and handle-safe role slug (the subagent ``name``)."""
        return slugify(self.role, fallback=self.agent_id[:8] or "agent")


@dataclass
class SyncPlan:
    """Planned mutations to converge the target dir on server state."""

    to_add: list[AgentRoleMeta] = field(default_factory=list)
    to_update: list[AgentRoleMeta] = field(default_factory=list)
    to_remove: list[str] = field(default_factory=list)  # prefixed file names
    skipped_curated: list[str] = field(default_factory=list)  # role names a curated file owns
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
    def post(self, path: str, body: dict | None = None) -> Any: ...


def parse_persona_ref(value: str) -> str:
    """Return the persona card id when ``value`` is a persona reference, else ''.

    Accepts two forms (case-insensitive prefix):

    - ``skill:<card_id>`` — explicit reference to a skill context card.
    - ``persona:<card_id>`` — equivalent, kinder vocabulary for non-engineers.

    Anything else (free-text system prompt, empty string) returns ``""`` —
    callers fall back to treating the string as the inline prompt body. The
    regex requires at least 4 characters of id so a stray ``skill:foo`` typo
    is treated as inline text, not a broken reference.
    """
    if not value:
        return ""
    match = _PERSONA_REF_RE.match(value.strip())
    return match.group(1) if match else ""


def _fetch_persona_body(client: _AgentClient, card_id: str) -> str:
    """Resolve a persona Skill context card → its rendered system-prompt body.

    Persona cards live in the same ``type=skill`` namespace as workflow skills.
    The export sub-command fetches the card and inlines its body as the
    subagent's system prompt so editing the persona in DeepVista propagates to
    every Claude Code session on the next sync — no plugin rebuild needed.

    Returns an empty string on any failure (network, missing card, malformed
    payload). The caller falls back to ``config.soul`` / templated body.
    """
    try:
        data = client.post("/get_context_card", {"card_id": card_id, "card_type": "skill"})
    except Exception:  # pragma: no cover — network/HTTP errors swallowed by design
        return ""
    card = data.get("card") or data or {}
    # Prefer ``description`` (the rendered markdown body); fall back to
    # ``summary`` so we still produce *something* if the card is summary-only.
    body = str(card.get("description") or card.get("summary") or "").strip()
    return body


# ---------------------------------------------------------------------------
# Slugs, hashes, and definition rendering
# ---------------------------------------------------------------------------


def slugify(value: str, *, fallback: str = "agent") -> str:
    """Lowercase ASCII slug; collapse other runs into ``-``; strip edges."""
    norm = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    slug = _SLUG_RE.sub("-", norm.lower()).strip("-")
    return slug or fallback


def file_name(meta: AgentRoleMeta, *, prefix: str = DEFAULT_PREFIX) -> str:
    """Definition filename including prefix, e.g. ``dv-marketing.md``."""
    return f"{prefix}{meta.slug}.md"


def _yaml_inline_string(value: str) -> str:
    """Double-quote a value for safe inline YAML."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _spec_for(role: str) -> tuple[str, str, str]:
    spec = ROLE_SPECS.get(role.strip().lower())
    if spec:
        return spec
    pretty = role.strip().title() or "Generalist"
    return (
        f"{pretty} specialist",
        f"{role.strip().lower()} tasks grounded in DeepVista notes and the knowledge base",
        _GENERIC_COLOR,
    )


def build_agent_markdown(meta: AgentRoleMeta) -> str:
    """Render the full ``<role>.md`` subagent definition.

    Frontmatter drives Claude Code's auto-delegation (``description``) and the
    invocation handle (``name`` == bare role, so ``@marketing`` resolves). The
    ``x-deepvista-*`` keys are informational; Claude Code ignores unknown keys
    but we read ``AGENT_MARKER`` back to decide what we may safely delete.
    """
    title, focus, color = _spec_for(meta.role)
    description = (
        f"{title} for DeepVista. Use PROACTIVELY for {focus}. "
        "Grounds every deliverable in real DeepVista notes and knowledge-base cards before acting."
    )

    frontmatter = [
        "---",
        f"name: {meta.slug}",
        f"description: {_yaml_inline_string(description)}",
        "tools: Read, Write, Edit, Bash, WebFetch, WebSearch",
        "model: sonnet",
        f"color: {color}",
        "maxTurns: 25",
        "skills: deepvista",
        f"{AGENT_MARKER}: true",
        f"x-deepvista-role: {_yaml_inline_string(meta.role)}",
    ]
    if meta.agent_id:
        frontmatter.append(f"x-deepvista-agent-id: {meta.agent_id}")
    if meta.updated_at:
        frontmatter.append(f"x-deepvista-updated-at: {meta.updated_at}")
    if meta.persona_card_id:
        # DV-853: persona Skill context card the body was sourced from. Edit
        # the card in DeepVista (`deepvista skill ...`) — local edits here are
        # overwritten on the next sync.
        frontmatter.append(f"x-deepvista-persona-card-id: {meta.persona_card_id}")
    frontmatter.append("---")

    # A custom system prompt (config.soul or a resolved persona Skill card) is
    # authoritative — bake it in as the body verbatim. Frontmatter (routing,
    # tools, model, preloaded skill) stays templated.
    if meta.system_prompt.strip():
        if meta.persona_card_id:
            source = f"persona Skill context card · id: {meta.persona_card_id}"
        else:
            source = "configured system prompt (config.soul)"
        prompt_body = (
            f"<!-- Generated by `deepvista agents export` from the {source}\n"
            f"     of your “{meta.agent_name}” managed agent · role: {meta.role}\n"
            f"     · agent id: {meta.agent_id or 'n/a'}. Edit it in DeepVista — local changes\n"
            "     are overwritten on the next sync. -->\n\n"
            f"{meta.system_prompt.strip()}\n"
        )
        return "\n".join(frontmatter) + "\n\n" + prompt_body

    backing = f" (backed by your “{meta.agent_name}” managed agent)" if meta.agent_name else ""
    body = f"""\
<!-- Generated by `deepvista agents export` from a DeepVista managed agent.
     Do not edit by hand — changes are overwritten on the next sync.
     Role: {meta.role} · agent id: {meta.agent_id or "n/a"} -->

You are the **{title.lower()}** for DeepVista{backing}, working as an isolated
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
3. **Work.** Produce the deliverable for {focus}. Be concrete and specific.
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
# Server fetch + grouping
# ---------------------------------------------------------------------------


def metas_from_agents(agents: list[dict[str, Any]]) -> list[AgentRoleMeta]:
    """Collapse a list of managed agents into one meta per distinct role.

    Roles in :data:`SKIP_ROLES` (and empties) are dropped. When several agents
    share a role we keep the most recently updated as the representative and
    record the count. Ordering of the result is by role slug for stable output.
    """
    by_role: dict[str, AgentRoleMeta] = {}
    for agent in agents:
        raw_role = str(agent.get("agent_role") or "").strip()
        if raw_role.lower() in SKIP_ROLES:
            continue
        slug = slugify(raw_role, fallback="")
        if not slug:
            continue
        updated = str(agent.get("updated_at") or "")
        config = agent.get("config") or {}
        soul = str(config.get("soul") or "").strip()
        # DV-853: ``config.system_prompt`` is the public field that lets a
        # managed agent name a persona Skill context card. We carry the parsed
        # id here and resolve it once on the way out (see ``_fetch_server_agents``).
        raw_system_prompt = str(config.get("system_prompt") or "").strip()
        persona_id = parse_persona_ref(raw_system_prompt)
        # When the field is *inline text* (not a reference), prefer it over soul
        # — system_prompt is the newer, role-scoped knob.
        prompt_body = soul if persona_id else (raw_system_prompt or soul)
        candidate = AgentRoleMeta(
            role=raw_role,
            agent_name=str(agent.get("name") or ""),
            agent_id=str(agent.get("id") or ""),
            agent_type=str(agent.get("agent_type") or ""),
            updated_at=updated,
            count=1,
            system_prompt=prompt_body,
            persona_card_id=persona_id,
        )
        existing = by_role.get(slug)
        if existing is None:
            by_role[slug] = candidate
        else:
            # Keep the freshest representative; carry the running count forward.
            winner = candidate if updated > existing.updated_at else existing
            by_role[slug] = AgentRoleMeta(
                role=winner.role,
                agent_name=winner.agent_name,
                agent_id=winner.agent_id,
                agent_type=winner.agent_type,
                updated_at=winner.updated_at,
                count=existing.count + 1,
                system_prompt=winner.system_prompt,
                persona_card_id=winner.persona_card_id,
            )
    return [by_role[k] for k in sorted(by_role)]


def _resolve_personas(client: _AgentClient, metas: list[AgentRoleMeta]) -> list[AgentRoleMeta]:
    """Inline persona Skill context card bodies into role metas.

    Runs once per role at most: distinct ids are fetched in a single pass and
    cached locally for the call. A failed lookup leaves ``system_prompt``
    untouched, so a missing or misnamed persona card degrades gracefully to
    the templated body.
    """
    cache: dict[str, str] = {}
    resolved: list[AgentRoleMeta] = []
    for meta in metas:
        if not meta.persona_card_id:
            resolved.append(meta)
            continue
        body = cache.get(meta.persona_card_id)
        if body is None:
            body = _fetch_persona_body(client, meta.persona_card_id)
            cache[meta.persona_card_id] = body
        if not body:
            resolved.append(meta)
            continue
        resolved.append(
            AgentRoleMeta(
                role=meta.role,
                agent_name=meta.agent_name,
                agent_id=meta.agent_id,
                agent_type=meta.agent_type,
                updated_at=meta.updated_at,
                count=meta.count,
                system_prompt=body,
                persona_card_id=meta.persona_card_id,
            )
        )
    return resolved


def _fetch_server_agents(client: _AgentClient, *, limit: int) -> list[AgentRoleMeta]:
    """Pull managed agents via ``GET /agents``, group by role, resolve personas.

    Persona Skill context card refs (``config.system_prompt = "skill:<id>"``)
    are resolved here so the rest of the pipeline — plan computation, hashing,
    rendering — sees a fully populated ``system_prompt`` body. That keeps the
    sync state stable: a persona card edit on the server flips the hash and
    triggers an update on the next sync, exactly like a ``config.soul`` edit.
    """
    data = client.get("/agents", params={"limit": limit})
    agents = data.get("agents") or []
    metas = metas_from_agents(agents)
    return _resolve_personas(client, metas)


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
    ``name``. Generation skips any role whose slug collides with one of these,
    so a curated agent (e.g. a polished ``marketing.md``) always wins.
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
    server_metas: list[AgentRoleMeta],
    *,
    target: Path,
    prefix: str,
    state: dict[str, Any],
) -> SyncPlan:
    """Diff server roles against on-disk files and the previous sync state.

    Only files we previously wrote are removed — curated agents and unrelated
    files are never touched, even if they share our prefix.
    """
    plan = SyncPlan()
    reserved = curated_names(target, prefix)
    previous: dict[str, dict[str, Any]] = {e["role"]: e for e in state.get("defs", []) if e.get("role")}
    server_roles = {m.role for m in server_metas}

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

    # Files we owned last time that the server no longer returns (role deleted
    # or renamed), or that a curated agent now claims → remove. A role still
    # served and not curated is kept, whether it changed this run or not.
    skipped = set(plan.skipped_curated)
    for role, entry in previous.items():
        fname = entry.get("file_name")
        if not fname:
            continue
        gone = role not in server_roles
        now_curated = slugify(role) in skipped
        if (gone or now_curated) and fname not in plan.to_remove:
            plan.to_remove.append(fname)

    return plan


def apply_plan(
    plan: SyncPlan,
    *,
    target: Path,
    prefix: str,
    all_server_metas: list[AgentRoleMeta] | None = None,
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
                "role": meta.role,
                "file_name": fname,
                "agent_id": meta.agent_id,
                "content_hash": content_hash(content),
                "updated_at": meta.updated_at,
            }
        )
        touched.add(meta.role)

    # Record unchanged defs too so state reflects everything on disk.
    for meta in all_server_metas or []:
        if meta.role in touched or meta.slug in plan.skipped_curated:
            continue
        path = target / file_name(meta, prefix=prefix)
        existing = _read_existing_hash(path)
        if existing is None:
            continue
        new_defs.append(
            {
                "role": meta.role,
                "file_name": file_name(meta, prefix=prefix),
                "agent_id": meta.agent_id,
                "content_hash": existing,
                "updated_at": meta.updated_at,
            }
        )

    for fname in plan.to_remove:
        path = target / fname
        if not path.exists():
            continue
        if not _is_ours(path, prefix):
            # Belt-and-braces: never delete a file we don't recognise.
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
    """True if state expects files on disk but the target lost most of them.

    Triggers a re-sync even when throttled — handles a plugin marketplace
    update or manual cleanup wiping the dir.
    """
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
    """Run one export pass. Returns a structured result dict.

    On throttle skip, returns ``{"skipped": "throttled", ...}`` without hitting
    the network. Network/API errors propagate to the caller (the CLI wrapper
    swallows them so a SessionStart hook never fails the session).
    """
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
