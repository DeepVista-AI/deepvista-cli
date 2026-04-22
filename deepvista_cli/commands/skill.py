"""deepvista skill — list, get, run, status, export.

Skills (formerly Recipes / VistaBooks) are structured checklist workflows stored as
context cards (type=vistabook). Skill Runs are execution instances (type=vistabook_run)
linked via a master chat session.

Five resources: card · skill · vistabase · chat
"""

from __future__ import annotations

import json
import re
import sys
from typing import Any

import click

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
            "card_type": "vistabook",
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
    data = _client(ctx).post("/get_context_card", {"card_id": skill_id, "card_type": "vistabook"})
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
        "user_instruction": f'<contextCard id="{skill_id}" cardType="vistabook"></contextCard> {instruction}',
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


@skill_group.command("export")
@click.argument("skill_id")
@click.option(
    "--format", "export_format", type=click.Choice(["skill"]), default="skill", help="Export format (default: skill)."
)
@click.pass_context
def skill_export(ctx: click.Context, skill_id: str, export_format: str) -> None:
    """Export a Skill as a SKILL.md file for use in AI agents.

    Read-only — generates output but does not modify the Skill.
    """
    data = _client(ctx).post("/export_vistabook_to_skill", {"card_ids": [skill_id]})
    format_output(
        data, ctx.obj.output_format, title=f"Export: {skill_id}", entity_type="skill", base_url=ctx.obj.auth_url
    )


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


_CREATE_FROM_NOTE_INSTRUCTIONS = {
    "persona": (
        "A **persona skill** named `persona-<interviewee-slug>` that captures the "
        "interviewee's philosophy, voice, and decision-making lens. When loaded, "
        "the agent should respond in their voice and apply their frameworks. "
        "Include: who they are, core mental models drawn from the note, voice/"
        "tone rules, and a 3-5 phase advising sequence using <accordion>/<nli> "
        "shortcodes."
    ),
    "workflow": (
        "A **workflow skill** named `workflow-<topic-slug>` that turns the "
        "interviewee's frameworks or steps into an executable workflow. The user "
        "provides inputs; the workflow classifies, recommends, and returns a "
        "prioritized plan. Include: purpose, **a `## Workflow` section with a "
        "`mermaid` flowchart diagram that visualises the decision graph — "
        "ALWAYS open the fence with the `mermaid` info string (```mermaid) "
        "and use `flowchart TD`**, input schema, 4-6 phases using "
        "<accordion>/<nli> shortcodes, cheat sheet, and output format template. "
        "**Mermaid animation is REQUIRED, not optional.** For every edge in "
        "the flowchart, give it an ID using mermaid v11 syntax "
        "(`A e1@--> B`, `B e2@--> C`, …) and turn animation on with "
        "`e1@{ animation: slow }` for happy-path edges and "
        "`e1@{ animation: fast }` for tight loops. Every edge must have an "
        "ID and every ID must have an animation directive — a static "
        "diagram is a rendering bug, not an acceptable output. "
        "**Node-label rules (critical for rendering): every node label must "
        "be a single short line, ≤ 30 characters. Do NOT use `<br/>`, "
        "`\\n`, `<b>`, `<i>`, or any HTML tags inside `[ ... ]`, `( ... )`, "
        "or `{ ... }`. If you need a sub-description, chain a second node "
        "below instead of stuffing two lines into one node — mermaid's "
        "HTML-label sizing clips wrapped text and multi-line content will "
        "render cut off.** Keep the diagram under ~15 nodes — split into "
        "multiple diagrams if the workflow is larger."
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
    lines.append(
        "**You MUST persist each skill by calling `upsert_context_card` with "
        '`card_type="skill"`.** Do not write the skill content to a local '
        "file, do not paste it in the chat response, do not skip the tool "
        "call. One `upsert_context_card` invocation per skill."
    )
    lines.append("")
    lines.append(
        "For each `upsert_context_card` call: set `title` to the skill name, "
        "put the full SKILL.md body in `description`, add relevant `tags` "
        "including the kind (`persona` or `workflow`), and link every source "
        f"note via `related_context_card_ids={ids_json}`. After each call, "
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
