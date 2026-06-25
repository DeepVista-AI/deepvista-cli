"""deepvista chat — send messages to the DeepVista chat agent.

The +send helper streams the agent's response as NDJSON to stdout.
"""

from __future__ import annotations

import json

import click

from deepvista_cli.client.http import DeepVistaClient
from deepvista_cli.commands import apply_project_override, project_option
from deepvista_cli.output.formatter import format_output


def _client(ctx: click.Context) -> DeepVistaClient:
    return ctx.obj._client


@click.group("chat")
def chat_group() -> None:
    """Chat with DeepVista AI agent."""


@chat_group.command("sessions")
@click.option("--limit", default=10, help="Max results (default 10).")
@click.option("--offset", default=0, help="Offset for pagination.")
@click.option("--search", default=None, help="Search chat summaries.")
@project_option
@click.pass_context
def chat_sessions(
    ctx: click.Context, limit: int, offset: int, search: str | None, project_override: str | None
) -> None:
    """List chat sessions.

    Read-only — never modifies chat sessions.
    """
    apply_project_override(ctx, project_override)
    body: dict = {"limit": limit, "offset": offset}
    if search:
        body["search"] = search

    data = _client(ctx).post("/get_chat_sessions", body)
    sessions = data.get("sessions", [])
    result = {"sessions": sessions, "count": len(sessions), "has_more": data.get("has_more", False)}
    format_output(
        result,
        ctx.obj.output_format,
        columns=["id", "summary", "created_at"],
        title="Chat Sessions",
        entity_type="chat",
        base_url=ctx.obj.auth_url,
        project_id=ctx.obj.project_id,
    )


@chat_group.command("get")
@click.argument("chat_id")
@project_option
@click.pass_context
def chat_get(ctx: click.Context, chat_id: str, project_override: str | None) -> None:
    """Get a chat session with all pages.

    Read-only.
    """
    apply_project_override(ctx, project_override)
    data = _client(ctx).get(f"/chat_sessions/{chat_id}")
    format_output(
        data,
        ctx.obj.output_format,
        title=f"Chat: {chat_id}",
        entity_type="chat",
        base_url=ctx.obj.auth_url,
        project_id=ctx.obj.project_id,
    )


@chat_group.command("delete")
@click.argument("chat_id")
@click.option("--dry-run", is_flag=True, default=False, help="Preview what would happen without making any changes.")
@click.pass_context
def chat_delete(ctx: click.Context, chat_id: str, dry_run: bool) -> None:
    """Delete a chat session.

    > [!CAUTION] This is a destructive write command — confirm with the user before executing.
    """
    if dry_run:
        format_output(
            {"dry_run": True, "would": "delete chat session", "chat_id": chat_id},
            ctx.obj.output_format,
            entity_type="chat",
            base_url=ctx.obj.auth_url,
            project_id=ctx.obj.project_id,
        )
        return

    data = _client(ctx).delete(f"/chat_sessions/{chat_id}")
    format_output(
        data, ctx.obj.output_format, entity_type="chat", base_url=ctx.obj.auth_url, project_id=ctx.obj.project_id
    )


# ---------------------------------------------------------------------------
# Helper: +send
# ---------------------------------------------------------------------------


@chat_group.command("+send")
@click.argument("message")
@click.option("--chat-id", default=None, help="Send to existing chat session.")
@click.option("--new", "new_chat", is_flag=True, default=False, help="Force start a new conversation.")
@click.option("--dry-run", is_flag=True, default=False, help="Preview what would happen without making any changes.")
@project_option
@click.pass_context
def chat_send(
    ctx: click.Context, message: str, chat_id: str | None, new_chat: bool, dry_run: bool, project_override: str | None
) -> None:
    """Send a message to the DeepVista AI agent and stream the response.

    Output is NDJSON (one JSON object per line) — each line is an SSE event
    from the agent's streaming response.

    > [!CAUTION] This is a write command — it creates/updates a chat session
    > and may trigger agent actions (creating cards, searching, etc.).
    """
    apply_project_override(ctx, project_override)
    body: dict = {"user_instruction": message}
    if chat_id and not new_chat:
        body["chat_id"] = chat_id

    if dry_run:
        format_output(
            {"dry_run": True, "would": "send message to DeepVista agent", "payload": body},
            ctx.obj.output_format,
            entity_type="chat",
            base_url=ctx.obj.auth_url,
            project_id=ctx.obj.project_id,
        )
        return

    for event in _client(ctx).stream_sse("/imagine", body):
        click.echo(json.dumps(event, default=str))
