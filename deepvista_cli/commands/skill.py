"""deepvista skill — list, get, run, status.

Skills are structured checklist workflows stored as context cards (type=skill).
Skill Runs are execution instances (type=skill_run) linked via a master chat session.

Five resources: card · skill · vistabase · chat
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

import click

from deepvista_cli import skill_catalog
from deepvista_cli.client.http import DeepVistaClient
from deepvista_cli.output.formatter import format_output, output_error

SKILL_COLUMNS = ["id", "title", "display_status", "updated_at"]

SKILL_KINDS = ("persona", "workflow")

# Cap applied when a selector returns a large set so a single synthesis run stays
# within the agent's usable context. Overridable via --limit.
_DEFAULT_MULTI_NOTE_LIMIT = 5

# Upper cap when scanning `/get_context_cards` for tag filtering — tags are filtered
# client-side since the list endpoint has no native tag filter.
_TAG_SCAN_LIMIT = 200

_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)


def _client(ctx: click.Context) -> DeepVistaClient:
    return ctx.obj._client


@click.group("skill")
def skill_group() -> None:
    """Manage Skills — structured executable workflows."""


# ---------------------------------------------------------------------------
# Read commands
# ---------------------------------------------------------------------------


@skill_group.command("list")
@click.option("--limit", default=20, help="Max results (default 20).")
@click.option("--page", "page_number", default=1, help="Page number.")
@click.pass_context
def skill_list(ctx: click.Context, limit: int, page_number: int) -> None:
    """List all Skills.

    Read-only — never modifies your Skills.
    """
    data = _client(ctx).post(
        "/get_context_cards",
        {
            "card_type": "skill",
            "limit": limit,
            "page_number": page_number,
        },
    )
    cards = data.get("cards", [])
    result = {"skills": cards, "count": len(cards), "has_more": data.get("has_more", False)}
    format_output(
        result,
        ctx.obj.output_format,
        columns=SKILL_COLUMNS,
        title="Skills",
        entity_type="skill",
        base_url=ctx.obj.auth_url,
    )


@skill_group.command("get")
@click.argument("skill_id")
@click.pass_context
def skill_get(ctx: click.Context, skill_id: str) -> None:
    """Get a Skill by ID.

    Read-only — never modifies the Skill.
    """
    data = _client(ctx).post("/get_context_card", {"card_id": skill_id, "card_type": "skill"})
    format_output(
        data, ctx.obj.output_format, title=f"Skill: {skill_id}", entity_type="skill", base_url=ctx.obj.auth_url
    )


# ---------------------------------------------------------------------------
# Action commands
# ---------------------------------------------------------------------------


@skill_group.command("run")
@click.argument("skill_id")
@click.option("--input", "user_input", default=None, help="Context or instructions for the run.")
@click.option("--dry-run", is_flag=True, default=False, help="Preview what would happen without making any changes.")
@click.pass_context
def skill_run(ctx: click.Context, skill_id: str, user_input: str | None, dry_run: bool) -> None:
    """Run a Skill — executes the workflow via the chat agent.

    > [!CAUTION] This is a write command — it creates a new Skill run and sends
    > messages to the chat agent. Confirm with the user before executing.

    Output is NDJSON (one JSON object per line) as the agent streams its response.
    """
    if not _UUID_RE.match(skill_id):
        output_error(3, "Invalid skill ID", f"Expected UUID format, got: {skill_id!r}")

    instruction = user_input or "Run this skill"
    body: dict = {
        "user_instruction": f'<contextCard id="{skill_id}" cardType="skill"></contextCard> {instruction}',
    }

    if dry_run:
        format_output(
            {"dry_run": True, "would": "start Skill run", "skill_id": skill_id, "instruction": instruction},
            ctx.obj.output_format,
            entity_type="skill",
            base_url=ctx.obj.auth_url,
        )
        return

    for event in _client(ctx).stream_sse("/imagine", body):
        click.echo(json.dumps(event, default=str))


@skill_group.command("status")
@click.argument("run_id", metavar="RUN_CHAT_ID")
@click.pass_context
def skill_status(ctx: click.Context, run_id: str) -> None:
    """Check the status of a Skill run.

    Read-only — uses the chat session endpoint to check run state.
    """
    data = _client(ctx).get(f"/chat_sessions/{run_id}")
    session = data.get("session", data)
    result = {
        "id": run_id,  # Use 'id' so URL generation works
        "chat_id": run_id,
        "summary": session.get("summary", ""),
        "run_status": session.get("run_status", ""),
        "visibility": session.get("visibility", ""),
        "created_at": session.get("created_at", ""),
    }
    format_output(result, ctx.obj.output_format, title=f"Run: {run_id}", entity_type="chat", base_url=ctx.obj.auth_url)


# ---------------------------------------------------------------------------
# Catalog: remote-managed skills distributed as thin SKILL.md stubs
# ---------------------------------------------------------------------------


@skill_group.command("sync")
@click.option(
    "--target",
    type=click.Path(file_okay=False, resolve_path=True),
    default=None,
    help=("Skills directory to write stubs into. Default: ~/.claude/skills (also read by opencode, Cursor, Codex)."),
)
@click.option(
    "--prefix",
    default=skill_catalog.DEFAULT_STUB_PREFIX,
    show_default=True,
    help="Namespace prefix for stub dir names (keeps user-authored skills untouched).",
)
@click.option(
    "--limit",
    type=click.IntRange(1, 200),
    default=skill_catalog.DEFAULT_LIMIT,
    show_default=True,
    help="Cap number of skills fetched. Honors server-side ordering (pinned → recent).",
)
@click.option(
    "--throttle-min",
    type=int,
    default=skill_catalog.DEFAULT_THROTTLE_MIN,
    show_default=True,
    help="Skip sync if last successful sync was newer than N minutes.",
)
@click.option("--force", is_flag=True, default=False, help="Ignore the throttle and sync now.")
@click.option("--dry-run", is_flag=True, default=False, help="Compute diff, print summary, exit without writing.")
@click.option("--quiet", is_flag=True, default=False, help="Suppress stdout; communicate via exit code only.")
@click.pass_context
def skill_sync(
    ctx: click.Context,
    target: str | None,
    prefix: str,
    limit: int,
    throttle_min: int,
    force: bool,
    dry_run: bool,
    quiet: bool,
) -> None:
    """Sync thin DeepVista catalog stubs into an agent skills directory.

    Each stub is a minimal ``SKILL.md`` — frontmatter plus a lazy-load
    directive. The real skill body is fetched at invocation time via
    ``deepvista skill load <id>``. Re-runs are idempotent and throttled.

    Read/write — writes stub files but never calls remote write endpoints.
    Safe to wire into a SessionStart hook (it exits 0 on any network failure
    and previous sync state remains usable).
    """
    target_path = Path(target) if target else skill_catalog.DEFAULT_TARGET_DIR

    try:
        result = skill_catalog.sync_catalog(
            _client(ctx),
            target=target_path,
            prefix=prefix,
            limit=limit,
            throttle_min=throttle_min,
            force=force,
            dry_run=dry_run,
        )
    # Same SystemExit rationale as `skill load`: a hook must never fail the
    # session, so we swallow auth/API/network errors raised as sys.exit too.
    except (Exception, SystemExit) as exc:  # noqa: BLE001
        if not quiet:
            click.echo(json.dumps({"error": {"code": 1, "message": f"sync failed: {exc}"}}), err=True)
        sys.exit(0)

    if quiet:
        return

    format_output(result, ctx.obj.output_format, title="Skill catalog sync", entity_type="skill")


@skill_group.command("load")
@click.argument("skill_id")
@click.option("--no-cache", is_flag=True, default=False, help="Bypass the on-disk body cache.")
@click.option(
    "--ttl",
    type=int,
    default=skill_catalog.DEFAULT_BODY_CACHE_TTL_SEC,
    show_default=True,
    help="Body cache TTL in seconds.",
)
@click.pass_context
def skill_load(ctx: click.Context, skill_id: str, no_cache: bool, ttl: int) -> None:
    """Print the full SKILL.md body for a catalog skill.

    Called by stub SKILL.md bodies at invocation time (`` !`deepvista skill
    load <id>` ``). The output replaces the preprocessor placeholder so the
    invoking agent receives the real instructions.

    Read-only. Output is raw Markdown on stdout — global ``--format`` is
    deliberately ignored so shell preprocessing works regardless of profile.
    """
    if not _UUID_RE.match(skill_id):
        output_error(3, "Invalid skill ID", f"Expected UUID format, got: {skill_id!r}")

    try:
        body = skill_catalog.load_skill_body(
            _client(ctx),
            skill_id,
            use_cache=not no_cache,
            ttl_sec=ttl,
        )
    # Catch SystemExit too — the HTTP client calls sys.exit on API/auth
    # errors, but at skill-invocation time we'd rather return a readable
    # error body than bubble a raw exit code into the agent's context.
    except (Exception, SystemExit) as exc:  # noqa: BLE001
        reason = "API error" if isinstance(exc, SystemExit) else str(exc) or type(exc).__name__
        click.echo(
            "---\n"
            'name: "deepvista-skill-load-error"\n'
            'description: "DeepVista skill body could not be loaded."\n'
            "---\n\n"
            f"# Could not load skill `{skill_id}`\n\n"
            f"Reason: {reason}\n\n"
            "Fix: run `deepvista auth status` and `deepvista skill sync --force`, then retry.\n"
        )
        sys.exit(0)

    click.echo(body)


# ---------------------------------------------------------------------------
# Marketplace: Discover & Install
# ---------------------------------------------------------------------------

DISCOVER_COLUMNS = ["id", "title", "category", "version", "installed"]


@skill_group.command("discover")
@click.option("--search", "-s", default=None, help="Search term to filter skills.")
@click.option(
    "--category",
    "-c",
    type=click.Choice(["persona", "productivity", "workflow"]),
    default=None,
    help="Filter by category.",
)
@click.option("--limit", default=50, help="Max results (default 50).")
@click.pass_context
def skill_discover(ctx: click.Context, search: str | None, category: str | None, limit: int) -> None:
    """Discover public skills from the marketplace.

    Read-only — browse available skills without installing anything.
    Use `deepvista skill install <id>` to install a skill.
    """
    body: dict = {"limit": limit, "offset": 0}
    if search:
        body["search"] = search
    if category:
        body["category"] = category

    data = _client(ctx).post("/discover_skills", body)
    skills = data.get("skills", [])
    result = {"skills": skills, "count": len(skills), "has_more": data.get("has_more", False)}
    format_output(
        result,
        ctx.obj.output_format,
        columns=DISCOVER_COLUMNS,
        title="Marketplace Skills",
        entity_type="skill",
        base_url=ctx.obj.auth_url,
    )


@skill_group.command("install")
@click.argument("skill_id")
@click.option("--dry-run", is_flag=True, default=False, help="Preview what would happen without making any changes.")
@click.pass_context
def skill_install(ctx: click.Context, skill_id: str, dry_run: bool) -> None:
    """Install a marketplace skill into your library.

    > [!CAUTION] This is a write command — it creates a new Skill in your
    > library from the marketplace. Confirm with the user before executing.

    The skill_id must match an entry in the marketplace registry.
    Use `deepvista skill discover` to browse available skills.
    """
    if dry_run:
        format_output(
            {"dry_run": True, "would": "install marketplace skill", "skill_id": skill_id},
            ctx.obj.output_format,
            entity_type="skill",
            base_url=ctx.obj.auth_url,
        )
        return

    data = _client(ctx).post("/install_marketplace_skill", {"skill_id": skill_id})

    if data.get("already_installed"):
        click.echo(json.dumps({"status": "already_installed", "card": data.get("card", {})}, indent=2, default=str))
    else:
        click.echo(json.dumps({"status": "installed", "card": data.get("card", {})}, indent=2, default=str))


# ---------------------------------------------------------------------------
# create-from-note — synthesize skills from a source note via the agent
# ---------------------------------------------------------------------------


_FRONTMATTER_REQUIREMENT = (
    "**The SKILL.md body you put in `description` MUST start with a valid YAML "
    "frontmatter block — three dashes, the keys below, three dashes — before "
    "anything else. No prose, no heading, no blank line before the opening "
    "`---`. A skill without frontmatter is a broken skill and will be rejected.**\n"
    "\n"
    "Required frontmatter keys:\n"
    "- `name` — the skill slug (matches the `title` you pass to `upsert_context_card`)\n"
    "- `description` — one sentence (≤ 200 chars) describing when to load this skill\n"
    "- `type` — exactly `persona` or `workflow` (matches the kind being generated)\n"
    "- `execution` — `stateless` for personas, `stateful` for workflows\n"
    "\n"
    "Exact template (copy the structure, fill in the values):\n"
    "\n"
    "```\n"
    "---\n"
    "name: <skill-slug>\n"
    'description: "<one-sentence trigger — when should the agent load this?>"\n'
    "type: <persona|workflow>\n"
    "execution: <stateless|stateful>\n"
    "---\n"
    "\n"
    "# <Title>\n"
    "...\n"
    "```\n"
)

_CREATE_FROM_NOTE_INSTRUCTIONS = {
    "persona": (
        "A **persona skill** named `persona-<interviewee-slug>` that captures the "
        "interviewee's philosophy, voice, and decision-making lens. When loaded, "
        "the agent should respond in their voice and apply their frameworks. "
        "Frontmatter: `type: persona`, `execution: stateless`. Body sections (in "
        "this order, all required): `## Purpose` (one-paragraph who-they-are), "
        "`## Core mental models` (3-6 bullets drawn from the note, each citing "
        "the note), `## Voice & tone` (do/don't list), `## Advising sequence` "
        "(3-5 phases the persona walks the user through, using `<accordion>` "
        "shortcodes and standard markdown ordered lists)."
    ),
    "workflow": (
        "A **workflow skill** named `workflow-<topic-slug>` that turns the "
        "interviewee's frameworks or steps into an executable workflow. The user "
        "provides inputs; the workflow classifies, recommends, and returns a "
        "prioritized plan. Frontmatter: `type: workflow`, `execution: stateful`.\n"
        "\n"
        "Body sections — emit them in this exact order, all required:\n"
        "1. `## Purpose` — one paragraph: what this workflow does, for whom, "
        "when to load it.\n"
        "2. `## Inputs` — the input schema the user must provide "
        "(bullet list of fields, each with a one-line description).\n"
        "3. `## Workflow` — a single `mermaid` flowchart that visualises "
        "the decision graph. **The `## Workflow` section without a "
        "rendered mermaid diagram is a rejected output.**\n"
        "4. `## Phases` — 4-6 phases broken out using `<accordion>` "
        "shortcodes and standard markdown ordered lists, one accordion per phase, each phase "
        "containing the steps, decisions, and exit criteria.\n"
        "5. `## Cheat sheet` — a compact table or bullet list the user "
        "can scan during execution.\n"
        "6. `## Output format` — a template the agent fills in at the end "
        "of the run (markdown skeleton with placeholders).\n"
        "\n"
        "Mermaid rules for the `## Workflow` diagram:\n"
        "- Open the fence with the `mermaid` info string (```` ```mermaid ````) "
        "and use `flowchart TD`.\n"
        "- **Mermaid animation is REQUIRED, not optional.** Every edge gets "
        "an ID using mermaid v11 syntax (`A e1@--> B`, `B e2@--> C`, …) and "
        "an animation directive: `e1@{ animation: slow }` for happy-path "
        "edges, `e1@{ animation: fast }` for tight loops. Every edge must "
        "have an ID; every ID must have an animation directive. A static "
        "diagram is a rendering bug, not an acceptable output.\n"
        "- **Node-label rules (critical for rendering): every node label "
        "must be a single short line, ≤ 30 characters. Do NOT use "
        "`<br/>`, `\\n`, `<b>`, `<i>`, or any HTML tags inside `[ ... ]`, "
        "`( ... )`, or `{ ... }`.** If you need a sub-description, chain a "
        "second node below instead of stuffing two lines into one node — "
        "mermaid's HTML-label sizing clips wrapped text.\n"
        "- Keep the diagram under ~15 nodes — split into multiple diagrams "
        "if the workflow is larger."
    ),
}


def _build_create_from_note_prompt(notes: list[tuple[str, str]], kinds: tuple[str, ...]) -> str:
    """Build the synthesis prompt for 1..N source notes.

    ``notes`` is a list of ``(note_id, title)`` tuples; ``title`` may be empty
    when the caller couldn't resolve it cheaply. The prompt stays compatible
    with the single-note wording when ``len(notes) == 1`` so existing agents
    keep producing the same output shape.
    """
    if not notes:
        raise ValueError("at least one note is required")

    ids_json = json.dumps([nid for nid, _ in notes])

    if len(notes) == 1:
        note_id = notes[0][0]
        lines = [
            f'Look up the note with id "{note_id}" using `read_context_card`. Read '
            "its full content. From that note, generate the skill(s) listed below. "
            "Ground every detail in the note — do not invent frameworks or advice "
            "the note doesn't contain.",
        ]
    else:
        bullets = []
        for nid, title in notes:
            label = f'"{title}" ({nid})' if title else nid
            bullets.append(f"- {label}")
        lines = [
            f"Look up each of the following {len(notes)} source notes using "
            "`read_context_card` and read their full content:",
            "",
            *bullets,
            "",
            "From those notes **together**, generate the skill(s) listed below. "
            "Ground every detail in the notes — do not invent frameworks or advice "
            "they don't contain. When the notes agree, state the shared principle "
            "and cite each note that supports it. When they disagree, surface the "
            "tension explicitly and let the user pick. Prefer synthesis over "
            "averaging: the goal is a skill that is stronger than any single note.",
        ]

    lines.append("")
    lines.append("Skills to generate:")
    for i, kind in enumerate(kinds, 1):
        lines.append(f"{i}. {_CREATE_FROM_NOTE_INSTRUCTIONS[kind]}")
    lines.append("")
    lines.append(_FRONTMATTER_REQUIREMENT)
    lines.append("")
    lines.append(
        "**You MUST persist each skill by calling `upsert_context_card` with "
        '`card_type="skill"`.** Do not write the skill content to a local '
        "file, do not paste it in the chat response, do not skip the tool "
        "call. One `upsert_context_card` invocation per skill."
    )
    lines.append("")
    lines.append(
        "For each `upsert_context_card` call: set `title` to the skill name "
        "(matching the frontmatter `name`); put the full SKILL.md body — "
        "**starting with the YAML frontmatter block** — in `description`; "
        "add relevant `tags` including the kind (`persona` or `workflow`); "
        f"and link every source note via "
        f"`related_context_card_ids={ids_json}`. Before calling, verify the "
        "first three characters of `description` are exactly `---` — if not, "
        "you forgot the frontmatter and must regenerate. After each call, "
        "confirm the returned card id in the chat response."
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Selector resolution — turn flags into a concrete list of note IDs
# ---------------------------------------------------------------------------


def _read_ids_from_file(path: str) -> list[str]:
    """Read one ID per line from a file. ``-`` means stdin."""
    if path == "-":
        raw = sys.stdin.read()
    else:
        try:
            with open(path, encoding="utf-8") as fh:
                raw = fh.read()
        except OSError as exc:
            output_error(4, "Cannot read --from-file", str(exc))
            return []  # unreachable; output_error exits

    ids: list[str] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # Tolerate `jq -r '.notes[].id'` style or whitespace-separated tokens.
        ids.extend(tok for tok in line.split() if tok and not tok.startswith("#"))
    return ids


def _cards_to_pairs(cards: list[dict], *, skip_id: str | None = None) -> list[tuple[str, str]]:
    """Extract ``(id, title)`` pairs from an API card list, dropping ``skip_id``."""
    pairs: list[tuple[str, str]] = []
    for card in cards:
        cid = card.get("id")
        if not cid or cid == skip_id:
            continue
        pairs.append((cid, card.get("title", "") or ""))
    return pairs


def _resolve_from_search(client: DeepVistaClient, query: str, limit: int) -> list[tuple[str, str]]:
    body = {"query_text": query, "card_type": "note", "limit": limit}
    data = client.post("/get_context_cards", body)
    return _cards_to_pairs(data.get("cards", []))


def _resolve_from_similar(client: DeepVistaClient, seed_id: str, limit: int) -> list[tuple[str, str]]:
    """Find notes related to a seed card via hybrid search on its title + snippet.

    Matches the behaviour of `card +similar` (card.py) so results feel consistent.
    """
    seed = client.post("/get_context_card", {"card_id": seed_id})
    title = seed.get("title", "") or ""
    snippet = seed.get("snippet", "") or ""
    query = f"{title} {snippet}".strip()
    if not query:
        output_error(3, "Seed card has no content for similarity search", f"Card: {seed_id}")
    # Ask for one extra so we can drop the seed itself and still satisfy --limit.
    body = {"query_text": query, "card_type": "note", "limit": limit + 1}
    data = client.post("/get_context_cards", body)
    return _cards_to_pairs(data.get("cards", []), skip_id=seed_id)[:limit]


def _resolve_from_tag(client: DeepVistaClient, tag: str, limit: int) -> list[tuple[str, str]]:
    """Filter notes by tag (client-side — the list endpoint has no tag filter)."""
    body = {"card_type": "note", "limit": _TAG_SCAN_LIMIT, "page_number": 1}
    data = client.post("/get_context_cards", body)
    matched = [c for c in data.get("cards", []) if tag in (c.get("tags") or [])]
    return _cards_to_pairs(matched)[:limit]


def _resolve_from_grep(client: DeepVistaClient, pattern: str, limit: int) -> list[tuple[str, str]]:
    """Regex-match note content via `/grep_context_cards`."""
    body = {
        "pattern": pattern,
        "case_insensitive": False,
        "limit": limit,
        "context_lines": 0,
        "card_type": "note",
    }
    data = client.post("/grep_context_cards", body)
    # The grep endpoint returns `matches` grouped by card; we only need ids+titles.
    pairs: list[tuple[str, str]] = []
    seen: set[str] = set()
    for match in data.get("matches", data.get("results", [])):
        cid = match.get("card_id") or match.get("id")
        if not cid or cid in seen:
            continue
        seen.add(cid)
        pairs.append((cid, match.get("title", "") or ""))
    return pairs[:limit]


def _dedupe_pairs(pairs: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """De-duplicate while preserving first-seen order. Prefer non-empty titles."""
    seen: dict[str, str] = {}
    order: list[str] = []
    for cid, title in pairs:
        if cid not in seen:
            seen[cid] = title
            order.append(cid)
        elif not seen[cid] and title:
            seen[cid] = title
    return [(cid, seen[cid]) for cid in order]


def _resolve_note_ids(
    client: DeepVistaClient | None,
    *,
    positional: tuple[str, ...],
    extra: tuple[str, ...],
    from_file: str | None,
    from_search: str | None,
    from_similar: str | None,
    from_tag: str | None,
    from_grep: str | None,
    limit: int,
) -> list[tuple[str, str]]:
    """Merge every source of note IDs into a single ordered, capped list.

    ``client`` may be ``None`` when the caller only supplies explicit IDs (tests
    rely on this). Selectors that need the API will fail loudly if it's missing.
    """
    pairs: list[tuple[str, str]] = [(nid, "") for nid in positional]
    pairs.extend((nid, "") for nid in extra)
    if from_file is not None:
        pairs.extend((nid, "") for nid in _read_ids_from_file(from_file))

    def require_client() -> DeepVistaClient:
        if client is None:
            raise RuntimeError("API client is required for search/similar/tag/grep selectors")
        return client

    if from_search:
        pairs.extend(_resolve_from_search(require_client(), from_search, limit))
    if from_similar:
        if not _UUID_RE.match(from_similar):
            output_error(3, "Invalid --from-similar seed", f"Expected UUID, got: {from_similar!r}")
        pairs.extend(_resolve_from_similar(require_client(), from_similar, limit))
    if from_tag:
        pairs.extend(_resolve_from_tag(require_client(), from_tag, limit))
    if from_grep:
        pairs.extend(_resolve_from_grep(require_client(), from_grep, limit))

    pairs = _dedupe_pairs(pairs)
    return pairs[:limit]


@skill_group.command("create-from-note")
@click.argument("note_ids_positional", metavar="[NOTE_ID]...", nargs=-1)
@click.option(
    "--note-id",
    "note_id_flags",
    multiple=True,
    help="Source note by ID. Repeatable — pass multiple to synthesize across notes.",
)
@click.option(
    "--from-file",
    default=None,
    metavar="PATH",
    help="Read note IDs (one per line) from a file. Use '-' for stdin.",
)
@click.option(
    "--from-search",
    default=None,
    metavar="QUERY",
    help="Resolve source notes via hybrid search (same backend as `card +search`).",
)
@click.option(
    "--from-similar",
    default=None,
    metavar="SEED_NOTE_ID",
    help="Resolve source notes related to a seed note (graph-style neighbours).",
)
@click.option(
    "--from-tag",
    default=None,
    metavar="TAG",
    help="Resolve source notes whose tags list contains TAG.",
)
@click.option(
    "--from-grep",
    default=None,
    metavar="REGEX",
    help="Resolve source notes whose content matches a regex.",
)
@click.option(
    "--limit",
    type=click.IntRange(1, 25),
    default=_DEFAULT_MULTI_NOTE_LIMIT,
    help=f"Cap resolved source notes (default {_DEFAULT_MULTI_NOTE_LIMIT}, max 25).",
)
@click.option(
    "--kind",
    "kinds",
    type=click.Choice(SKILL_KINDS, case_sensitive=False),
    multiple=True,
    default=SKILL_KINDS,
    help="Which skill kinds to synthesize. Repeatable. Default: persona and workflow.",
)
@click.option("--chat-id", default=None, help="Continue an existing synthesis session.")
@click.option(
    "--yes",
    "-y",
    "assume_yes",
    is_flag=True,
    default=False,
    help="Skip the write confirmation prompt. Use only in scripts/batch conversion.",
)
@click.option("--dry-run", is_flag=True, default=False, help="Preview the prompt without calling the agent.")
@click.pass_context
def skill_create_from_note(
    ctx: click.Context,
    note_ids_positional: tuple[str, ...],
    note_id_flags: tuple[str, ...],
    from_file: str | None,
    from_search: str | None,
    from_similar: str | None,
    from_tag: str | None,
    from_grep: str | None,
    limit: int,
    kinds: tuple[str, ...],
    chat_id: str | None,
    assume_yes: bool,
    dry_run: bool,
) -> None:
    """Synthesize skill card(s) from one or more notes via the DeepVista agent.

    Pass a single note UUID positionally for the original single-note behaviour,
    or combine multiple notes via repeated positionals, `--note-id`, `--from-file`
    (including stdin via `-`), `--from-search`, `--from-similar`, `--from-tag`,
    and `--from-grep`. The agent produces one `persona` skill (voice + frameworks)
    and/or one `workflow` skill (executable steps), grounded in the union of all
    resolved notes and linked back to every source.

    Streams NDJSON identical to `chat +send` and `skill run`.

    > [!CAUTION] This is a write command — the agent creates skill cards in
    > the user's project. Confirm before executing.
    """
    # Validate any directly-supplied IDs up front — cheap + gives a useful error.
    for nid in (*note_ids_positional, *note_id_flags):
        if not _UUID_RE.match(nid):
            output_error(3, "Invalid note ID", f"Expected UUID format, got: {nid!r}")

    # Selectors that require API access skip in dry-run with no client yet? We still
    # want to dry-run from real data to show the exact prompt the agent will see,
    # so the client is always built lazily on first access.
    selectors_used = any([from_file, from_search, from_similar, from_tag, from_grep])
    api_needed = bool(from_search or from_similar or from_tag or from_grep)

    client = _client(ctx) if api_needed else None
    resolved = _resolve_note_ids(
        client,
        positional=note_ids_positional,
        extra=note_id_flags,
        from_file=from_file,
        from_search=from_search,
        from_similar=from_similar,
        from_tag=from_tag,
        from_grep=from_grep,
        limit=limit,
    )

    if not resolved:
        hint = (
            "pass a NOTE_ID or a selector (--note-id, --from-file, --from-search, "
            "--from-similar, --from-tag, --from-grep)"
        )
        output_error(3, "No source notes resolved", hint if not selectors_used else "selectors returned zero notes")

    # De-dup `--kind` while preserving order. Empty tuple shouldn't happen (has default).
    seen_k: set[str] = set()
    selected = tuple(k for k in (kinds or SKILL_KINDS) if not (k in seen_k or seen_k.add(k)))

    prompt = _build_create_from_note_prompt(resolved, selected)
    body: dict[str, Any] = {"user_instruction": prompt}
    if chat_id:
        body["chat_id"] = chat_id

    if dry_run:
        format_output(
            {
                "dry_run": True,
                "would": "synthesize skills from note(s) via DeepVista agent",
                "note_ids": [nid for nid, _ in resolved],
                "resolved_notes": [{"id": nid, "title": title} for nid, title in resolved],
                "kinds": list(selected),
                "payload": body,
            },
            ctx.obj.output_format,
            entity_type="skill",
            base_url=ctx.obj.auth_url,
        )
        return

    if not assume_yes:
        click.confirm(
            (
                f"The agent will create {len(selected)} skill card(s) synthesized from "
                f"{len(resolved)} source note(s). Continue?"
            ),
            abort=True,
        )

    try:
        active_client = client or _client(ctx)
        for event in active_client.stream_sse("/imagine", body):
            click.echo(json.dumps(event, default=str))
    except (KeyboardInterrupt, click.Abort):
        click.echo(json.dumps({"type": "interrupted", "message": "skill synthesis aborted by user"}), err=True)
        raise
    except Exception as exc:
        click.echo(
            json.dumps({"type": "error", "message": f"skill synthesis stream failed: {exc}"}),
            err=True,
        )
        raise
