"""deepvista notes — explicit user-authored knowledge (context cards with type=note).

`notes` is the user-facing surface: hand-written notes, long-form text, "what I
want to remember". The +quick helper creates a note from a single text argument.
The index command triggers entity extraction on notes not yet processed.

For agent-recorded incidental info, use `deepvista card create --type <type>`.
For session transcripts, use the dedicated `deepvista session` group — the
`notes session-*` subcommands are thin aliases that delegate to it (DV-742).
"""

from __future__ import annotations

import json as _json
from typing import Any

import click

from deepvista_cli import session_note as sn
from deepvista_cli.client.http import DeepVistaClient
from deepvista_cli.client.origin import detect_agent_tool
from deepvista_cli.commands import (
    apply_project_override,
    deprecation_warning,
    project_option,
    resolve_content,
)
from deepvista_cli.commands.session import session_finalize, session_init, session_tick
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

    Deprecated — equivalent to `card list --type note`. Use `card` instead.

    Read-only — never modifies your notes.
    """
    deprecation_warning("notes list", "card list --type note")
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

    Deprecated — equivalent to `card get <id>`. Use `card` instead.

    Read-only.
    """
    deprecation_warning("notes get", "card get <id>")
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

    Deprecated — equivalent to `card create --type note` (which now applies the
    same agent tagging). Use `card` instead.

    > [!CAUTION] This is a write command — confirm with the user before executing.
    """
    deprecation_warning("notes create", "card create --type note")
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

    Deprecated — equivalent to `card update <id>`. Use `card` instead.

    > [!CAUTION] This is a write command — confirm with the user before executing.
    """
    deprecation_warning("notes update", "card update <id>")
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

    Deprecated — equivalent to `card delete <id> --type note`. Use `card` instead.

    > [!CAUTION] This is a destructive write command — confirm with the user before executing.
    """
    deprecation_warning("notes delete", "card delete <id> --type note")
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
# index — trigger entity extraction on notes
# ---------------------------------------------------------------------------


@notes_group.command("index")
@click.option(
    "--limit",
    type=click.IntRange(1, 500),
    default=50,
    help="Max notes to re-index (default 50, max 500).",
)
@click.option("--note-id", "note_ids", multiple=True, help="Index specific note(s) by ID. Repeatable.")
@click.option(
    "--all",
    "include_enriched",
    is_flag=True,
    default=False,
    help=(
        "Re-enrich every note up to --limit, not just those with a null embedding. "
        "Ignored when --note-id is set (explicit IDs always re-enrich)."
    ),
)
@click.option("--dry-run", is_flag=True, default=False, help="Preview what would happen without making any changes.")
@click.pass_context
def notes_index(
    ctx: click.Context,
    limit: int,
    note_ids: tuple[str, ...],
    include_enriched: bool,
    dry_run: bool,
) -> None:
    """Trigger entity extraction on notes that need processing.

    Calls the server-side `/index_notes` route. By default, finds notes that
    have never been enriched (null embedding) and enqueues the DeepVista
    agent to extract entities, create graph relationships, and refresh
    embeddings. Pass `--note-id` (repeatable) to target specific cards, or
    `--all` to re-enrich everything up to `--limit`.

    > [!CAUTION] This is a write command — it kicks off background agent runs
    > that may create/update related cards. Confirm before executing.
    """
    # Explicit IDs always bypass the unenriched filter — the user asked for those cards specifically.
    only_unenriched = not include_enriched and not note_ids
    body: dict[str, Any] = {
        "card_type": "note",
        "limit": limit,
        "only_unenriched": only_unenriched,
    }
    if note_ids:
        body["card_ids"] = list(note_ids)

    if dry_run:
        format_output(
            {"dry_run": True, "would": "POST /index_notes", "payload": body},
            ctx.obj.output_format,
            entity_type="note",
            base_url=ctx.obj.auth_url,
            project_id=ctx.obj.project_id,
        )
        return

    data = _client(ctx).post("/index_notes", body)
    format_output(
        data,
        ctx.obj.output_format,
        title="Indexed Notes",
        entity_type="note",
        base_url=ctx.obj.auth_url,
        project_id=ctx.obj.project_id,
    )


# ---------------------------------------------------------------------------
# Session-scoped notes — deprecated aliases (DV-742)
#
# These commands forward to `deepvista session ...`. Kept for one release so
# existing hook scripts keep working; new sessions land as `type='session'`.
# ---------------------------------------------------------------------------


@notes_group.command("session-init")
@click.option("--session-id", required=True, help="Agent session ID (Claude Code session_id).")
@click.option("--transcript", required=True, help="Path to the transcript JSONL.")
@click.option("--cwd", required=True, help="Project working directory the session is running in.")
@click.option("--agent", default=None, help="Agent type. Auto-detected from env/process-tree when omitted.")
@click.option("--agent-version", default=None, help="Agent version string. Auto-detected when omitted.")
@click.option("--dry-run", is_flag=True, default=False, help="Preview what would happen without making any changes.")
@click.pass_context
def notes_session_init(
    ctx: click.Context,
    session_id: str,
    transcript: str,
    cwd: str,
    agent: str | None,
    agent_version: str | None,
    dry_run: bool,
) -> None:
    """Alias for `deepvista session init` (DV-742).

    New session cards are written as ``type='session'``; in-flight rolling notes
    keep ticking through their existing id.

    > [!CAUTION] This is a write command (creates a card on first call).
    """
    deprecation_warning("notes session-init", "session init")
    ctx.invoke(
        session_init,
        session_id=session_id,
        transcript=transcript,
        cwd=cwd,
        agent=agent,
        agent_version=agent_version,
        dry_run=dry_run,
    )


@notes_group.command("session-tick")
@click.option("--session-id", required=True, help="Agent session ID.")
@click.option("--transcript", required=True, help="Path to the transcript JSONL.")
@click.option("--dry-run", is_flag=True, default=False, help="Preview what would happen without making any changes.")
@click.pass_context
def notes_session_tick(ctx: click.Context, session_id: str, transcript: str, dry_run: bool) -> None:
    """Alias for `deepvista session tick` (DV-742).

    > [!CAUTION] This is a write command.
    """
    deprecation_warning("notes session-tick", "session tick")
    ctx.invoke(session_tick, session_id=session_id, transcript=transcript, dry_run=dry_run)


@notes_group.command("session-finalize")
@click.option("--session-id", required=True, help="Agent session ID.")
@click.option("--transcript", default=None, help="Transcript path (final flush). Optional.")
@click.option(
    "--no-enrich", is_flag=True, default=False, help="Skip the notes-index enrich call (useful in tests/offline)."
)
@click.option("--dry-run", is_flag=True, default=False, help="Preview what would happen without making any changes.")
@click.pass_context
def notes_session_finalize(
    ctx: click.Context, session_id: str, transcript: str | None, no_enrich: bool, dry_run: bool
) -> None:
    """Alias for `deepvista session finalize` (DV-742).

    > [!CAUTION] This is a write command.
    """
    deprecation_warning("notes session-finalize", "session finalize")
    ctx.invoke(
        session_finalize,
        session_id=session_id,
        transcript=transcript,
        no_enrich=no_enrich,
        dry_run=dry_run,
    )


# ---------------------------------------------------------------------------
# Version history (DV-449 M2)
# ---------------------------------------------------------------------------


@notes_group.command("history")
@click.argument("note_id")
@click.option("--limit", type=click.IntRange(1, 500), default=50, help="Max versions to list (default 50).")
@click.pass_context
def notes_history(ctx: click.Context, note_id: str, limit: int) -> None:
    """List prior versions of a note (newest first).

    Read-only.
    """
    data = _client(ctx).post("/get_context_card_history", {"card_id": note_id, "limit": limit})
    versions = data.get("versions") or []
    format_output(
        {"note_id": note_id, "versions": versions, "count": len(versions)},
        ctx.obj.output_format,
        columns=["version", "reason", "changed_by", "created_at"],
        title=f"History: {note_id}",
        entity_type="note",
        base_url=ctx.obj.auth_url,
        project_id=ctx.obj.project_id,
    )


@notes_group.command("diff")
@click.argument("note_id")
@click.argument("version_a", type=int)
@click.argument("version_b", type=int)
@click.pass_context
def notes_diff(ctx: click.Context, note_id: str, version_a: int, version_b: int) -> None:
    """Unified diff between two versions of a note.

    Read-only.
    """
    import difflib

    a = _client(ctx).post("/get_context_card_version", {"card_id": note_id, "version": version_a})
    b = _client(ctx).post("/get_context_card_version", {"card_id": note_id, "version": version_b})
    a_text = (a.get("description") or "").splitlines(keepends=True)
    b_text = (b.get("description") or "").splitlines(keepends=True)
    diff = "".join(difflib.unified_diff(a_text, b_text, fromfile=f"v{version_a}", tofile=f"v{version_b}", lineterm=""))
    if ctx.obj.output_format == "json":
        format_output(
            {"note_id": note_id, "from": version_a, "to": version_b, "diff": diff},
            ctx.obj.output_format,
            entity_type="note",
            base_url=ctx.obj.auth_url,
            project_id=ctx.obj.project_id,
        )
    else:
        click.echo(diff or "(no differences)")


@notes_group.command("restore")
@click.argument("note_id")
@click.argument("version", type=int)
@click.option("--yes", "-y", is_flag=True, default=False, help="Skip confirmation.")
@click.option("--dry-run", is_flag=True, default=False, help="Preview what would happen without making any changes.")
@click.pass_context
def notes_restore(ctx: click.Context, note_id: str, version: int, yes: bool, dry_run: bool) -> None:
    """Roll a note back to a previous version.

    The current state is saved as a new version first, so restore is reversible.

    > [!CAUTION] This is a write command — confirm before executing.
    """
    if dry_run:
        format_output(
            {"dry_run": True, "would": "restore note", "note_id": note_id, "version": version},
            ctx.obj.output_format,
            entity_type="note",
            base_url=ctx.obj.auth_url,
            project_id=ctx.obj.project_id,
        )
        return

    if not yes and not click.confirm(f"Restore note {note_id} to version {version}?", default=False):
        output_error(3, "Aborted", "User declined restore.")
        return

    data = _client(ctx).post("/restore_context_card_version", {"card_id": note_id, "version": version})
    format_output(
        {"note_id": note_id, "restored_to": version, "card": data},
        ctx.obj.output_format,
        title=f"Restored: {note_id} → v{version}",
        entity_type="note",
        base_url=ctx.obj.auth_url,
        project_id=ctx.obj.project_id,
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
