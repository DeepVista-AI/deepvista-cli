"""deepvista notes — CRUD for notes (context cards with type=note).

Notes are a special case of context cards with type="note".
The +quick helper creates a note from a single text argument.
"""

from __future__ import annotations

import json as _json

import click

from deepvista_cli.client.http import DeepVistaClient
from deepvista_cli.commands import resolve_content
from deepvista_cli.output.formatter import format_output, output_error

NOTE_COLUMNS = ["id", "title", "display_status", "updated_at"]


def _client(ctx: click.Context) -> DeepVistaClient:
    return ctx.obj._client


@click.group("notes")
def notes_group() -> None:
    """Manage your notes."""


@notes_group.command("list")
@click.option("--limit", default=20, help="Max results (default 20).")
@click.option("--page", "page_number", default=1, help="Page number.")
@click.pass_context
def notes_list(ctx: click.Context, limit: int, page_number: int) -> None:
    """List all notes.

    Read-only — never modifies your notes.
    """
    data = _client(ctx).post(
        "/get_context_cards",
        {
            "card_type": "note",
            "limit": limit,
            "page_number": page_number,
        },
    )
    cards = data.get("cards", [])
    result = {"notes": cards, "count": len(cards), "has_more": data.get("has_more", False)}
    format_output(
        result,
        ctx.obj.output_format,
        columns=NOTE_COLUMNS,
        title="Notes",
        entity_type="note",
        base_url=ctx.obj.auth_url,
    )


@notes_group.command("get")
@click.argument("note_id")
@click.pass_context
def notes_get(ctx: click.Context, note_id: str) -> None:
    """Get a note by ID.

    Read-only.
    """
    data = _client(ctx).post("/get_context_card", {"card_id": note_id, "card_type": "note"})
    format_output(data, ctx.obj.output_format, title=f"Note: {note_id}", entity_type="note", base_url=ctx.obj.auth_url)


@notes_group.command("create")
@click.option("--title", required=True, help="Note title.")
@click.option("--content", "description", default=None, help="Note content (markdown).")
@click.option(
    "--content-file",
    default=None,
    help="Read content from a file path. Use '-' for stdin. Overrides --content.",
)
@click.option("--tags", default=None, help='Tags as JSON array: \'["tag1","tag2"]\'.')
@click.pass_context
def notes_create(
    ctx: click.Context, title: str, description: str | None, content_file: str | None, tags: str | None
) -> None:
    """Create a new note.

    > [!CAUTION] This is a write command — confirm with the user before executing.
    """
    description = resolve_content(description, content_file)
    body: dict = {"card_type": "note", "title": title, "enrich": True}
    if description:
        body["description"] = description
    if tags:
        try:
            body["tags"] = _json.loads(tags)
        except _json.JSONDecodeError:
            output_error(3, "Invalid --tags JSON", f"Got: {tags}")

    data = _client(ctx).post("/create_context_card", body)
    format_output(data, ctx.obj.output_format, title="Created Note", entity_type="note", base_url=ctx.obj.auth_url)


@notes_group.command("update")
@click.argument("note_id")
@click.option("--title", default=None, help="New title.")
@click.option("--content", "description", default=None, help="New content (markdown).")
@click.option(
    "--content-file",
    default=None,
    help="Read content from a file path. Use '-' for stdin. Overrides --content.",
)
@click.option("--tags", default=None, help='Tags as JSON array: \'["tag1","tag2"]\'.')
@click.pass_context
def notes_update(
    ctx: click.Context,
    note_id: str,
    title: str | None,
    description: str | None,
    content_file: str | None,
    tags: str | None,
) -> None:
    """Update a note.

    > [!CAUTION] This is a write command — confirm with the user before executing.
    """
    description = resolve_content(description, content_file)
    body: dict = {"card_id": note_id}
    if title:
        body["title"] = title
    if description:
        body["description"] = description
    if tags:
        try:
            body["tags"] = _json.loads(tags)
        except _json.JSONDecodeError:
            output_error(3, "Invalid --tags JSON", f"Got: {tags}")

    data = _client(ctx).post("/update_context_card", body)
    format_output(
        data, ctx.obj.output_format, title=f"Updated Note: {note_id}", entity_type="note", base_url=ctx.obj.auth_url
    )


@notes_group.command("delete")
@click.argument("note_id")
@click.pass_context
def notes_delete(ctx: click.Context, note_id: str) -> None:
    """Delete a note.

    > [!CAUTION] This is a destructive write command — confirm with the user before executing.
    """
    data = _client(ctx).delete(f"/context_cards/{note_id}", params={"card_type": "note"})
    format_output(data, ctx.obj.output_format, entity_type="note", base_url=ctx.obj.auth_url)


# ---------------------------------------------------------------------------
# Helper: +quick
# ---------------------------------------------------------------------------


@notes_group.command("+quick")
@click.argument("text")
@click.pass_context
def notes_quick(ctx: click.Context, text: str) -> None:
    """Quick-create a note from a single line of text.

    The first ~50 characters become the title; the full text is the content.

    > [!CAUTION] This is a write command — confirm with the user before executing.
    """
    # Derive title from first sentence or first 50 chars
    title = text[:50].split(".")[0].split("\n")[0].strip()
    if len(title) < len(text):
        title = title.rstrip(".") + "..."

    body = {
        "card_type": "note",
        "title": title,
        "description": text,
        "enrich": True,
    }
    data = _client(ctx).post("/create_context_card", body)
    format_output(data, ctx.obj.output_format, title="Quick Note", entity_type="note", base_url=ctx.obj.auth_url)
