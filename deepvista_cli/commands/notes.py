"""deepvista notes — explicit user-authored knowledge (context cards with type=note).

`notes` is the user-facing surface: hand-written notes, long-form text, "what I
want to remember". The +quick helper creates a note from a single text argument.

Everything here is a thin note-flavored wrapper over the `deepvista card`
commands (same endpoints, ``card_type=note`` preset, ``/notes/<id>`` web
links). Generic card features — version history, restore, entity indexing —
live under `deepvista card`. For session transcripts use `deepvista session`.
"""

from __future__ import annotations

import json as _json

import click

from deepvista_cli import session_note as sn
from deepvista_cli.client.http import DeepVistaClient
from deepvista_cli.client.origin import detect_agent_tool
from deepvista_cli.commands import apply_project_override, project_option, resolve_content
from deepvista_cli.output.formatter import format_output, output_error

NOTE_COLUMNS = ["id", "title", "display_status", "updated_at"]


def _client(ctx: click.Context) -> DeepVistaClient:
    return ctx.obj._client


@click.group("notes")
def notes_group() -> None:
    """Manage your hand-written notes (cards with type=note).

    Use `notes` for content **the user explicitly asked to record**
    (long-form text, manual capture, "what I want to remember"). For agent-
    captured incidental info use `deepvista card`; for session transcripts
    use `deepvista session`.
    """


@notes_group.command("list")
@click.option("--limit", default=20, help="Max results (default 20).")
@click.option("--page", "page_number", default=1, help="Page number.")
@project_option
@click.pass_context
def notes_list(ctx: click.Context, limit: int, page_number: int, project_override: str | None) -> None:
    """List all notes.

    Read-only — never modifies your notes.
    """
    apply_project_override(ctx, project_override)
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
        project_id=ctx.obj.project_id,
    )


@notes_group.command("get")
@click.argument("note_id")
@project_option
@click.pass_context
def notes_get(ctx: click.Context, note_id: str, project_override: str | None) -> None:
    """Get a note by ID.

    Read-only.
    """
    apply_project_override(ctx, project_override)
    data = _client(ctx).post("/get_context_card", {"card_id": note_id, "card_type": "note"})
    format_output(
        data,
        ctx.obj.output_format,
        title=f"Note: {note_id}",
        entity_type="note",
        base_url=ctx.obj.auth_url,
        project_id=ctx.obj.project_id,
    )


@notes_group.command("create")
@click.option("--title", required=True, help="Note title.")
@click.option("--content", "description", default=None, help="Note content (markdown).")
@click.option(
    "--content-file",
    default=None,
    help="Read content from a file path. Use '-' for stdin. Overrides --content.",
)
@click.option("--tags", default=None, help='Tags as JSON array: \'["tag1","tag2"]\'.')
@click.option("--dry-run", is_flag=True, default=False, help="Preview what would happen without making any changes.")
@project_option
@click.pass_context
def notes_create(
    ctx: click.Context,
    title: str,
    description: str | None,
    content_file: str | None,
    tags: str | None,
    dry_run: bool,
    project_override: str | None,
) -> None:
    """Create a new note.

    > [!CAUTION] This is a write command — confirm with the user before executing.
    """
    apply_project_override(ctx, project_override)
    description = resolve_content(description, content_file)

    from deepvista_cli.commands.agents import load_agent_id_for_active_agent

    agent, _ = detect_agent_tool()
    agent_id = load_agent_id_for_active_agent()
    # DV-791: prepend the combined agent tag so notes created here are filterable
    # by the AgentFilter UI alongside +quick / session writes.
    parsed_tags: list[str] = [sn.build_agent_tag(agent, agent_id)]
    if tags:
        try:
            user_tags = _json.loads(tags)
        except _json.JSONDecodeError:
            output_error(3, "Invalid --tags JSON", f"Got: {tags}")
            return
        if not isinstance(user_tags, list):
            output_error(3, "Invalid --tags JSON", "Expected a JSON array of strings.")
            return
        parsed_tags.extend(user_tags)

    body: dict = {"card_type": "note", "title": title, "tags": parsed_tags, "enrich": True}
    if description:
        body["description"] = description

    if dry_run:
        format_output(
            {"dry_run": True, "would": "create note", "payload": body},
            ctx.obj.output_format,
            entity_type="note",
            base_url=ctx.obj.auth_url,
            project_id=ctx.obj.project_id,
        )
        return

    data = _client(ctx).post("/create_context_card", body)
    format_output(
        data,
        ctx.obj.output_format,
        title="Created Note",
        entity_type="note",
        base_url=ctx.obj.auth_url,
        project_id=ctx.obj.project_id,
    )


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
@click.option("--dry-run", is_flag=True, default=False, help="Preview what would happen without making any changes.")
@click.pass_context
def notes_update(
    ctx: click.Context,
    note_id: str,
    title: str | None,
    description: str | None,
    content_file: str | None,
    tags: str | None,
    dry_run: bool,
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

    if dry_run:
        format_output(
            {"dry_run": True, "would": "update note", "payload": body},
            ctx.obj.output_format,
            entity_type="note",
            base_url=ctx.obj.auth_url,
            project_id=ctx.obj.project_id,
        )
        return

    data = _client(ctx).post("/update_context_card", body)
    format_output(
        data,
        ctx.obj.output_format,
        title=f"Updated Note: {note_id}",
        entity_type="note",
        base_url=ctx.obj.auth_url,
        project_id=ctx.obj.project_id,
    )


@notes_group.command("delete")
@click.argument("note_id")
@click.option("--dry-run", is_flag=True, default=False, help="Preview what would happen without making any changes.")
@click.pass_context
def notes_delete(ctx: click.Context, note_id: str, dry_run: bool) -> None:
    """Delete a note.

    > [!CAUTION] This is a destructive write command — confirm with the user before executing.
    """
    if dry_run:
        format_output(
            {"dry_run": True, "would": "delete note", "note_id": note_id},
            ctx.obj.output_format,
            entity_type="note",
            base_url=ctx.obj.auth_url,
            project_id=ctx.obj.project_id,
        )
        return

    data = _client(ctx).delete(f"/context_cards/{note_id}", params={"card_type": "note"})
    format_output(
        data, ctx.obj.output_format, entity_type="note", base_url=ctx.obj.auth_url, project_id=ctx.obj.project_id
    )


# ---------------------------------------------------------------------------
# Helper: +quick
# ---------------------------------------------------------------------------


_QUICK_TITLE_BUDGET = 50


@notes_group.command("+quick")
@click.argument("text")
@click.option("--dry-run", is_flag=True, default=False, help="Preview what would happen without making any changes.")
@click.pass_context
def notes_quick(ctx: click.Context, text: str, dry_run: bool) -> None:
    """Quick-create a note from a single line of text.

    The text is used as both the title and the content. Inputs that exceed
    50 characters, span multiple lines, or contain a period are rejected —
    use ``deepvista notes create --title ... --content ...`` for those, so
    the title isn't silently truncated.

    > [!CAUTION] This is a write command — confirm with the user before executing.
    """
    title = text.strip()
    if len(title) > _QUICK_TITLE_BUDGET or "\n" in title or "." in title:
        raise click.UsageError(
            f"+quick takes a single short line (<= {_QUICK_TITLE_BUDGET} chars, no '.' or newlines) "
            "so the title isn't truncated. Use "
            '`deepvista notes create --title "..." --content "..."` for longer notes.'
        )

    from deepvista_cli.commands.agents import load_agent_id_for_active_agent

    agent, _ = detect_agent_tool()
    agent_id = load_agent_id_for_active_agent()
    # DV-791 (PR review): write a SINGLE combined tag rather than two separate
    # ``agent:<tool>`` and ``agent_id:<uuid>`` entries. The backend now
    # mirrors the same shape, so notes created via the CLI are queryable
    # alongside notes created via the chat-service ``X-DeepVista-Origin``
    # path with a single ``tag_contains`` lookup.
    tags = [sn.build_agent_tag(agent, agent_id)]
    body = {
        "card_type": "note",
        "title": title,
        "description": text,
        "tags": tags,
        "enrich": True,
    }

    if dry_run:
        format_output(
            {"dry_run": True, "would": "create note", "payload": body},
            ctx.obj.output_format,
            entity_type="note",
            base_url=ctx.obj.auth_url,
            project_id=ctx.obj.project_id,
        )
        return

    data = _client(ctx).post("/create_context_card", body)
    format_output(
        data,
        ctx.obj.output_format,
        title="Quick Note",
        entity_type="note",
        base_url=ctx.obj.auth_url,
        project_id=ctx.obj.project_id,
    )
