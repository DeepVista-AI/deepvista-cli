"""deepvista card — CRUD + file-ops for context cards (knowledge base).

`card` is the agent-facing surface for **incidental** info recorded
mid-conversation — people, orgs, todos, key points, file refs, etc. Use the
sibling groups for more specific lifecycles:

  * `deepvista notes …`   — explicit user-authored content (long-form notes).
  * `deepvista session …` — rolling conversation transcripts (DV-742).

Endpoints:
  POST /get_context_cards      -> list / search
  POST /get_context_card       -> get by id
  POST /create_context_card    -> create
  POST /update_context_card    -> update
  POST /edit_context_card      -> targeted string replacement (file-ops Edit)
  POST /search_context_cards   -> hybrid tsvector + embedding content search
  DELETE /context_cards/{id}   -> delete
  POST /list_card_comments     -> list a card's comments (DV-1308)
  POST /create_card_comment    -> add a comment to a card
  POST /update_card_comment    -> edit a comment (author only)
  DELETE /card_comments/{id}   -> delete a comment (author only)
"""

from __future__ import annotations

import click

from deepvista_cli.client.http import DeepVistaClient
from deepvista_cli.commands import apply_project_override, project_option, resolve_content
from deepvista_cli.output.formatter import format_output, output_error

# Mirrors the backend's vista_common.models.context_card.CardType enum
# (types are enforced at the API layer, not in the DB). `note` is reserved
# for human-authored notes; `artifact` (DV-1573) is the agent's fallback for
# its own output when no structured type fits. The deprecated `skill_run`
# type (superseded by `run_log`, DV-1130) is intentionally absent.
CARD_TYPES = [
    "person",
    "organization",
    "message",
    "email",
    "todo",
    "topic",
    "keypoint",
    "file",
    "note",
    "session",
    "skill",
    "run_log",
    "schedule_job",
    "task",
    "conversation_starter",
    "artifact",
]

CARD_COLUMNS = ["id", "type", "title", "display_status", "updated_at"]

COMMENT_COLUMNS = ["id", "commenter_type", "commenter_name", "comment", "created_at"]


def _client(ctx: click.Context) -> DeepVistaClient:
    return ctx.obj._client


@click.group("card")
def card_group() -> None:
    """Manage knowledge cards (context cards).

    Use `card` for incidental info an agent records mid-conversation
    (`--type person|organization|todo|keypoint|topic|file|email|message`).
    For explicit user notes use `deepvista notes`; for session transcripts
    use `deepvista session`.
    """


# ---------------------------------------------------------------------------
# CRUD commands
# ---------------------------------------------------------------------------


@card_group.command("list")
@click.option(
    "--type",
    "card_type",
    type=click.Choice(CARD_TYPES, case_sensitive=False),
    default=None,
    help="Filter by card type.",
)
@click.option(
    "--status",
    "display_status",
    type=click.Choice(["pinned", "archived", "normal"]),
    default=None,
    help="Filter by display status.",
)
@click.option("--limit", default=20, help="Max results (default 20).")
@click.option("--page", "page_number", default=1, help="Page number (default 1).")
@click.option("--order-by", type=click.Choice(["created_at", "updated_at"]), default=None)
@click.option("--order", "order_direction", type=click.Choice(["asc", "desc"]), default=None)
@project_option
@click.pass_context
def card_list(
    ctx: click.Context,
    card_type: str | None,
    display_status: str | None,
    limit: int,
    page_number: int,
    order_by: str | None,
    order_direction: str | None,
    project_override: str | None,
) -> None:
    """List context cards with optional filtering."""
    apply_project_override(ctx, project_override)
    body: dict = {"limit": limit, "page_number": page_number}
    if card_type:
        body["card_type"] = card_type
    if display_status:
        body["display_status"] = display_status
    if order_by:
        body["order_by"] = order_by
    if order_direction:
        body["order_direction"] = order_direction

    data = _client(ctx).post("/get_context_cards", body)
    cards = data.get("cards", [])
    result = {
        "cards": cards,
        "page": data.get("page_number", page_number),
        "has_more": data.get("has_more", False),
        "count": len(cards),
    }
    format_output(
        result,
        ctx.obj.output_format,
        columns=CARD_COLUMNS,
        title="Cards",
        entity_type="card",
        base_url=ctx.obj.auth_url,
        project_id=ctx.obj.project_id,
    )


@card_group.command("get")
@click.argument("card_id")
@project_option
@click.pass_context
def card_get(ctx: click.Context, card_id: str, project_override: str | None) -> None:
    """Get a context card by ID."""
    apply_project_override(ctx, project_override)
    data = _client(ctx).post("/get_context_card", {"card_id": card_id})
    format_output(
        data,
        ctx.obj.output_format,
        title=f"Card: {card_id}",
        entity_type="card",
        base_url=ctx.obj.auth_url,
        project_id=ctx.obj.project_id,
    )


@card_group.command("create")
@click.option(
    "--type", "card_type", type=click.Choice(CARD_TYPES, case_sensitive=False), required=True, help="Card type."
)
@click.option("--title", required=True, help="Card title.")
@click.option("--content", "description", default=None, help="Card content/description (markdown).")
@click.option(
    "--content-file",
    default=None,
    help="Read content from a file path. Use '-' for stdin. Overrides --content.",
)
@click.option("--tags", default=None, help='Tags as JSON array: \'["tag1","tag2"]\'.')
@click.option("--no-enrich", is_flag=True, default=False, help="Skip entity enrichment.")
@click.option("--dry-run", is_flag=True, default=False, help="Preview what would happen without making any changes.")
@project_option
@click.pass_context
def card_create(
    ctx: click.Context,
    card_type: str,
    title: str,
    description: str | None,
    content_file: str | None,
    tags: str | None,
    no_enrich: bool,
    dry_run: bool,
    project_override: str | None,
) -> None:
    """Create a new context card.

    > [!CAUTION] This is a write command — confirm with the user before executing.
    """
    import json as _json

    apply_project_override(ctx, project_override)
    description = resolve_content(description, content_file)
    body: dict = {
        "card_type": card_type,
        "title": title,
        "enrich": not no_enrich,
    }
    if description:
        body["description"] = description
    if tags:
        try:
            body["tags"] = _json.loads(tags)
        except _json.JSONDecodeError:
            output_error(3, "Invalid --tags JSON", f"Got: {tags}")

    if dry_run:
        format_output(
            {"dry_run": True, "would": "create card", "payload": body},
            ctx.obj.output_format,
            entity_type="card",
            base_url=ctx.obj.auth_url,
            project_id=ctx.obj.project_id,
        )
        return

    data = _client(ctx).post("/create_context_card", body)
    format_output(
        data,
        ctx.obj.output_format,
        title="Created Card",
        entity_type="card",
        base_url=ctx.obj.auth_url,
        project_id=ctx.obj.project_id,
    )


@card_group.command("update")
@click.argument("card_id")
@click.option("--title", default=None, help="New title.")
@click.option("--content", "description", default=None, help="New content/description.")
@click.option(
    "--content-file",
    default=None,
    help="Read content from a file path. Use '-' for stdin. Overrides --content.",
)
@click.option("--type", "card_type", type=click.Choice(CARD_TYPES, case_sensitive=False), default=None)
@click.option("--tags", default=None, help='Tags as JSON array: \'["tag1","tag2"]\'.')
@click.option("--status", "display_status", type=click.Choice(["pinned", "archived"]), default=None)
@click.option("--dry-run", is_flag=True, default=False, help="Preview what would happen without making any changes.")
@click.pass_context
def card_update(
    ctx: click.Context,
    card_id: str,
    title: str | None,
    description: str | None,
    content_file: str | None,
    card_type: str | None,
    tags: str | None,
    display_status: str | None,
    dry_run: bool,
) -> None:
    """Update a context card.

    > [!CAUTION] This is a write command — confirm with the user before executing.
    """
    import json as _json

    description = resolve_content(description, content_file)
    body: dict = {"card_id": card_id}
    if title:
        body["title"] = title
    if description:
        body["description"] = description
    if card_type:
        body["card_type"] = card_type
    if display_status:
        body["display_status"] = display_status
    if tags:
        try:
            body["tags"] = _json.loads(tags)
        except _json.JSONDecodeError:
            output_error(3, "Invalid --tags JSON", f"Got: {tags}")

    if dry_run:
        format_output(
            {"dry_run": True, "would": "update card", "payload": body},
            ctx.obj.output_format,
            entity_type="card",
            base_url=ctx.obj.auth_url,
            project_id=ctx.obj.project_id,
        )
        return

    data = _client(ctx).post("/update_context_card", body)
    format_output(
        data,
        ctx.obj.output_format,
        title=f"Updated Card: {card_id}",
        entity_type="card",
        base_url=ctx.obj.auth_url,
        project_id=ctx.obj.project_id,
    )


@card_group.command("edit")
@click.argument("card_id")
@click.option("--old-string", required=True, help="The exact text to find in the card content.")
@click.option("--new-string", required=True, help="The replacement text.")
@click.option(
    "--replace-all", is_flag=True, default=False, help="Replace all occurrences (default: unique match only)."
)
@click.option("--dry-run", is_flag=True, default=False, help="Preview what would happen without making any changes.")
@click.pass_context
def card_edit(
    ctx: click.Context,
    card_id: str,
    old_string: str,
    new_string: str,
    replace_all: bool,
    dry_run: bool,
) -> None:
    """Targeted string replacement in a card's content.

    Like Claude Code's Edit tool — finds old_string in the card description
    and replaces it with new_string. By default, old_string must appear
    exactly once (provide more context to disambiguate).

    > [!CAUTION] This is a write command — confirm with the user before executing.
    """
    body: dict = {
        "card_id": card_id,
        "old_string": old_string,
        "new_string": new_string,
        "replace_all": replace_all,
    }

    if dry_run:
        format_output(
            {"dry_run": True, "would": "edit card content", "payload": body},
            ctx.obj.output_format,
            entity_type="card",
            base_url=ctx.obj.auth_url,
            project_id=ctx.obj.project_id,
        )
        return

    data = _client(ctx).post("/edit_context_card", body)
    format_output(
        data,
        ctx.obj.output_format,
        title=f"Edited Card: {card_id}",
        entity_type="card",
        base_url=ctx.obj.auth_url,
        project_id=ctx.obj.project_id,
    )


@card_group.command("delete")
@click.argument("card_id")
@click.option("--type", "card_type", default=None, help="Card type hint (optional, speeds up deletion).")
@click.option("--dry-run", is_flag=True, default=False, help="Preview what would happen without making any changes.")
@click.pass_context
def card_delete(ctx: click.Context, card_id: str, card_type: str | None, dry_run: bool) -> None:
    """Delete a context card.

    > [!CAUTION] This is a destructive write command — confirm with the user before executing.
    """
    if dry_run:
        payload: dict = {"card_id": card_id}
        if card_type:
            payload["card_type"] = card_type
        format_output(
            {"dry_run": True, "would": "delete card", "payload": payload},
            ctx.obj.output_format,
            entity_type="card",
            base_url=ctx.obj.auth_url,
            project_id=ctx.obj.project_id,
        )
        return

    params = {}
    if card_type:
        params["card_type"] = card_type
    data = _client(ctx).delete(f"/context_cards/{card_id}", params=params)
    format_output(
        data, ctx.obj.output_format, entity_type="card", base_url=ctx.obj.auth_url, project_id=ctx.obj.project_id
    )


# ---------------------------------------------------------------------------
# index — trigger entity extraction / enrichment
# ---------------------------------------------------------------------------


@card_group.command("index")
@click.option(
    "--type",
    "card_type",
    type=click.Choice(CARD_TYPES, case_sensitive=False),
    default="note",
    show_default=True,
    help="Card type to index.",
)
@click.option(
    "--limit",
    type=click.IntRange(1, 500),
    default=50,
    help="Max cards to re-index (default 50, max 500).",
)
@click.option("--card-id", "card_ids", multiple=True, help="Index specific card(s) by ID. Repeatable.")
@click.option(
    "--all",
    "include_enriched",
    is_flag=True,
    default=False,
    help=(
        "Re-enrich every card up to --limit, not just those with a null embedding. "
        "Ignored when --card-id is set (explicit IDs always re-enrich)."
    ),
)
@click.option("--dry-run", is_flag=True, default=False, help="Preview what would happen without making any changes.")
@click.pass_context
def card_index(
    ctx: click.Context,
    card_type: str,
    limit: int,
    card_ids: tuple[str, ...],
    include_enriched: bool,
    dry_run: bool,
) -> None:
    """Trigger entity extraction on cards that need processing.

    Calls the server-side `/index_notes` route. By default, finds cards that
    have never been enriched (null embedding) and enqueues the DeepVista
    agent to extract entities, create graph relationships, and refresh
    embeddings. Pass `--card-id` (repeatable) to target specific cards, or
    `--all` to re-enrich everything up to `--limit`.

    > [!CAUTION] This is a write command — it kicks off background agent runs
    > that may create/update related cards. Confirm before executing.
    """
    # Explicit IDs always bypass the unenriched filter — the user asked for those cards specifically.
    only_unenriched = not include_enriched and not card_ids
    body: dict = {
        "card_type": card_type,
        "limit": limit,
        "only_unenriched": only_unenriched,
    }
    if card_ids:
        body["card_ids"] = list(card_ids)

    if dry_run:
        format_output(
            {"dry_run": True, "would": "POST /index_notes", "payload": body},
            ctx.obj.output_format,
            entity_type="card",
            base_url=ctx.obj.auth_url,
            project_id=ctx.obj.project_id,
        )
        return

    data = _client(ctx).post("/index_notes", body)
    format_output(
        data,
        ctx.obj.output_format,
        title="Indexed Cards",
        entity_type="card",
        base_url=ctx.obj.auth_url,
        project_id=ctx.obj.project_id,
    )


# ---------------------------------------------------------------------------
# Version history (DV-449 M2)
# ---------------------------------------------------------------------------


@card_group.command("history")
@click.argument("card_id")
@click.option("--limit", type=click.IntRange(1, 500), default=50, help="Max versions to list (default 50).")
@click.pass_context
def card_history(ctx: click.Context, card_id: str, limit: int) -> None:
    """List prior versions of a card (newest first).

    Read-only.
    """
    data = _client(ctx).post("/get_context_card_history", {"card_id": card_id, "limit": limit})
    versions = data.get("versions") or []
    format_output(
        {"card_id": card_id, "versions": versions, "count": len(versions)},
        ctx.obj.output_format,
        columns=["version", "reason", "changed_by", "created_at"],
        title=f"History: {card_id}",
        entity_type="card",
        base_url=ctx.obj.auth_url,
        project_id=ctx.obj.project_id,
    )


@card_group.command("diff")
@click.argument("card_id")
@click.argument("version_a", type=int)
@click.argument("version_b", type=int)
@click.pass_context
def card_diff(ctx: click.Context, card_id: str, version_a: int, version_b: int) -> None:
    """Unified diff between two versions of a card.

    Read-only.
    """
    import difflib

    a = _client(ctx).post("/get_context_card_version", {"card_id": card_id, "version": version_a})
    b = _client(ctx).post("/get_context_card_version", {"card_id": card_id, "version": version_b})
    a_text = (a.get("description") or "").splitlines(keepends=True)
    b_text = (b.get("description") or "").splitlines(keepends=True)
    diff = "".join(difflib.unified_diff(a_text, b_text, fromfile=f"v{version_a}", tofile=f"v{version_b}", lineterm=""))
    if ctx.obj.output_format == "json":
        format_output(
            {"card_id": card_id, "from": version_a, "to": version_b, "diff": diff},
            ctx.obj.output_format,
            entity_type="card",
            base_url=ctx.obj.auth_url,
            project_id=ctx.obj.project_id,
        )
    else:
        click.echo(diff or "(no differences)")


@card_group.command("restore")
@click.argument("card_id")
@click.argument("version", type=int)
@click.option("--yes", "-y", is_flag=True, default=False, help="Skip confirmation.")
@click.option("--dry-run", is_flag=True, default=False, help="Preview what would happen without making any changes.")
@click.pass_context
def card_restore(ctx: click.Context, card_id: str, version: int, yes: bool, dry_run: bool) -> None:
    """Roll a card back to a previous version.

    The current state is saved as a new version first, so restore is reversible.

    > [!CAUTION] This is a write command — confirm before executing.
    """
    if dry_run:
        format_output(
            {"dry_run": True, "would": "restore card", "card_id": card_id, "version": version},
            ctx.obj.output_format,
            entity_type="card",
            base_url=ctx.obj.auth_url,
            project_id=ctx.obj.project_id,
        )
        return

    if not yes and not click.confirm(f"Restore card {card_id} to version {version}?", default=False):
        output_error(3, "Aborted", "User declined restore.")
        return

    data = _client(ctx).post("/restore_context_card_version", {"card_id": card_id, "version": version})
    format_output(
        {"card_id": card_id, "restored_to": version, "card": data},
        ctx.obj.output_format,
        title=f"Restored: {card_id} → v{version}",
        entity_type="card",
        base_url=ctx.obj.auth_url,
        project_id=ctx.obj.project_id,
    )


# ---------------------------------------------------------------------------
# Helper commands (+search, +similar, +pin, +archive)
# ---------------------------------------------------------------------------


@card_group.command("+search")
@click.argument("query")
@click.option("--type", "card_type", type=click.Choice(CARD_TYPES, case_sensitive=False), default=None)
@click.option("--limit", default=10, help="Max results (default 10).")
@click.pass_context
def card_search(ctx: click.Context, query: str, card_type: str | None, limit: int) -> None:
    """Search your knowledge base with hybrid vector + keyword search.

    Read-only — never modifies your knowledge base.
    """
    body: dict = {"query_text": query, "limit": limit}
    if card_type:
        body["card_type"] = card_type

    data = _client(ctx).post("/get_context_cards", body)
    cards = data.get("cards", [])
    result = {"query": query, "results": cards, "count": len(cards)}
    format_output(
        result,
        ctx.obj.output_format,
        columns=CARD_COLUMNS,
        title=f"Search: {query}",
        entity_type="card",
        base_url=ctx.obj.auth_url,
        project_id=ctx.obj.project_id,
    )


@card_group.command("+similar")
@click.argument("card_id")
@click.option("--limit", default=5, help="Max results (default 5).")
@click.pass_context
def card_similar(ctx: click.Context, card_id: str, limit: int) -> None:
    """Find context cards similar to a given card.

    Read-only — never modifies your knowledge base.
    """
    card = _client(ctx).post("/get_context_card", {"card_id": card_id})
    title = card.get("title", "")
    snippet = card.get("snippet", "")
    query = f"{title} {snippet}".strip()

    if not query:
        output_error(3, "Card has no content for similarity search", f"Card: {card_id}")

    body: dict = {"query_text": query, "limit": limit}
    data = _client(ctx).post("/get_context_cards", body)
    cards = [c for c in data.get("cards", []) if c.get("id") != card_id]
    result = {"source_card_id": card_id, "similar": cards, "count": len(cards)}
    format_output(
        result,
        ctx.obj.output_format,
        columns=CARD_COLUMNS,
        title=f"Similar to: {card_id}",
        entity_type="card",
        base_url=ctx.obj.auth_url,
        project_id=ctx.obj.project_id,
    )


@card_group.command("+pin")
@click.argument("card_id")
@click.option("--dry-run", is_flag=True, default=False, help="Preview what would happen without making any changes.")
@click.pass_context
def card_pin(ctx: click.Context, card_id: str, dry_run: bool) -> None:
    """Pin a context card.

    > [!CAUTION] This is a write command.
    """
    if dry_run:
        format_output(
            {"dry_run": True, "would": "pin card", "card_id": card_id},
            ctx.obj.output_format,
            entity_type="card",
            base_url=ctx.obj.auth_url,
            project_id=ctx.obj.project_id,
        )
        return

    data = _client(ctx).post("/update_context_card", {"card_id": card_id, "display_status": "pinned"})
    format_output(
        data, ctx.obj.output_format, entity_type="card", base_url=ctx.obj.auth_url, project_id=ctx.obj.project_id
    )


@card_group.command("+archive")
@click.argument("card_id")
@click.option("--dry-run", is_flag=True, default=False, help="Preview what would happen without making any changes.")
@click.pass_context
def card_archive(ctx: click.Context, card_id: str, dry_run: bool) -> None:
    """Archive a context card.

    > [!CAUTION] This is a write command.
    """
    if dry_run:
        format_output(
            {"dry_run": True, "would": "archive card", "card_id": card_id},
            ctx.obj.output_format,
            entity_type="card",
            base_url=ctx.obj.auth_url,
            project_id=ctx.obj.project_id,
        )
        return

    data = _client(ctx).post("/update_context_card", {"card_id": card_id, "display_status": "archived"})
    format_output(
        data, ctx.obj.output_format, entity_type="card", base_url=ctx.obj.auth_url, project_id=ctx.obj.project_id
    )


@card_group.command("+search-content")
@click.argument("query", required=False, default="")
@click.option("--type", "card_type", type=click.Choice(CARD_TYPES, case_sensitive=False), default=None)
@click.option("--limit", default=20, help="Max cards to return (default 20).")
@click.pass_context
def card_search_content(
    ctx: click.Context,
    query: str,
    card_type: str | None,
    limit: int,
) -> None:
    """Hybrid full-text + semantic search, ranked by combined score.

    Different from +search — this ranks against card content (not just
    title/keywords) via the search_vector + embedding hybrid. Omit query
    to browse cards of --type, most-recently-updated first.

    Read-only — never modifies your knowledge base.
    """
    body: dict = {"query": query, "limit": limit}
    if card_type:
        body["card_type"] = card_type

    data = _client(ctx).post("/search_context_cards", body)
    format_output(
        data,
        ctx.obj.output_format,
        title=f"Search: {query}" if query else "Browse",
        entity_type="card",
        base_url=ctx.obj.auth_url,
        project_id=ctx.obj.project_id,
    )


# ---------------------------------------------------------------------------
# Comments (DV-1308 / DV-1496) — flat, markdown comment thread on a card
# ---------------------------------------------------------------------------


@card_group.group("comment")
def comment_group() -> None:
    """Add / read / edit / delete comments on a context card.

    Comments are a flat, markdown thread attached to a card — use them for
    enrichment and running commentary instead of editing the card body. The CLI
    posts as the authenticated user (`commenter_type=human`); you can only edit
    or delete your own comments.
    """


@comment_group.command("list")
@click.argument("card_id")
@click.option("--limit", default=50, help="Max comments to return (default 50).")
@project_option
@click.pass_context
def comment_list(ctx: click.Context, card_id: str, limit: int, project_override: str | None) -> None:
    """List a card's comments (oldest first).

    Read-only.
    """
    apply_project_override(ctx, project_override)
    comments = _client(ctx).post("/list_card_comments", {"card_id": card_id})
    comments = comments if isinstance(comments, list) else []
    format_output(
        {"card_id": card_id, "comments": comments[:limit], "count": len(comments[:limit])},
        ctx.obj.output_format,
        columns=COMMENT_COLUMNS,
        title=f"Comments: {card_id}",
        entity_type="card",
        base_url=ctx.obj.auth_url,
        project_id=ctx.obj.project_id,
    )


@comment_group.command("add")
@click.argument("card_id")
@click.option("--content", "comment", default=None, help="Comment body (markdown).")
@click.option(
    "--content-file",
    default=None,
    help="Read the comment from a file path. Use '-' for stdin. Overrides --content.",
)
@click.option("--dry-run", is_flag=True, default=False, help="Preview what would happen without making any changes.")
@project_option
@click.pass_context
def comment_add(
    ctx: click.Context,
    card_id: str,
    comment: str | None,
    content_file: str | None,
    dry_run: bool,
    project_override: str | None,
) -> None:
    """Add a comment to a context card.

    > [!CAUTION] This is a write command — confirm with the user before executing.
    """
    apply_project_override(ctx, project_override)
    comment = resolve_content(comment, content_file)
    if not comment or not comment.strip():
        output_error(3, "Comment must not be empty", "Pass --content or --content-file.")

    body: dict = {"card_id": card_id, "comment": comment}
    if dry_run:
        format_output(
            {"dry_run": True, "would": "create card comment", "payload": body},
            ctx.obj.output_format,
            entity_type="card",
            base_url=ctx.obj.auth_url,
            project_id=ctx.obj.project_id,
        )
        return

    data = _client(ctx).post("/create_card_comment", body)
    format_output(
        data,
        ctx.obj.output_format,
        title=f"Commented on: {card_id}",
        entity_type="card",
        base_url=ctx.obj.auth_url,
        project_id=ctx.obj.project_id,
    )


@comment_group.command("edit")
@click.argument("comment_id")
@click.option("--content", "comment", default=None, help="New comment body (markdown).")
@click.option(
    "--content-file",
    default=None,
    help="Read the comment from a file path. Use '-' for stdin. Overrides --content.",
)
@click.option("--dry-run", is_flag=True, default=False, help="Preview what would happen without making any changes.")
@click.pass_context
def comment_edit(
    ctx: click.Context,
    comment_id: str,
    comment: str | None,
    content_file: str | None,
    dry_run: bool,
) -> None:
    """Edit one of your own comments.

    > [!CAUTION] This is a write command — confirm with the user before executing.
    """
    comment = resolve_content(comment, content_file)
    if not comment or not comment.strip():
        output_error(3, "Comment must not be empty", "Pass --content or --content-file.")

    body: dict = {"comment_id": comment_id, "comment": comment}
    if dry_run:
        format_output(
            {"dry_run": True, "would": "update card comment", "payload": body},
            ctx.obj.output_format,
            entity_type="card",
            base_url=ctx.obj.auth_url,
            project_id=ctx.obj.project_id,
        )
        return

    data = _client(ctx).post("/update_card_comment", body)
    format_output(
        data,
        ctx.obj.output_format,
        title=f"Edited comment: {comment_id}",
        entity_type="card",
        base_url=ctx.obj.auth_url,
        project_id=ctx.obj.project_id,
    )


@comment_group.command("delete")
@click.argument("comment_id")
@click.option("--dry-run", is_flag=True, default=False, help="Preview what would happen without making any changes.")
@click.pass_context
def comment_delete(ctx: click.Context, comment_id: str, dry_run: bool) -> None:
    """Delete one of your own comments.

    > [!CAUTION] This is a destructive write command — confirm with the user before executing.
    """
    if dry_run:
        format_output(
            {"dry_run": True, "would": "delete card comment", "comment_id": comment_id},
            ctx.obj.output_format,
            entity_type="card",
            base_url=ctx.obj.auth_url,
            project_id=ctx.obj.project_id,
        )
        return

    data = _client(ctx).delete(f"/card_comments/{comment_id}")
    format_output(
        data, ctx.obj.output_format, entity_type="card", base_url=ctx.obj.auth_url, project_id=ctx.obj.project_id
    )
