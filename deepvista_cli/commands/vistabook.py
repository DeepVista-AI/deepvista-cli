"""deepvista vistabook — list, get, +run, +status, +export.

VistaBooks are structured checklist workflows stored as context cards (type=vistabook).
VistaBook Runs are execution instances (type=vistabook_run) linked via a master chat.
"""

from __future__ import annotations

import json
import re

import click

from deepvista_cli.client.http import DeepVistaClient
from deepvista_cli.output.formatter import format_output, output_error

VISTABOOK_COLUMNS = ["id", "title", "display_status", "updated_at"]


def _client(ctx: click.Context) -> DeepVistaClient:
    return ctx.obj._client


@click.group("vistabook")
def vistabook_group() -> None:
    """Manage VistaBook workflows — templates and runs."""


# ---------------------------------------------------------------------------
# Read commands
# ---------------------------------------------------------------------------


@vistabook_group.command("list")
@click.option("--limit", default=20, help="Max results (default 20).")
@click.option("--page", "page_number", default=1, help="Page number.")
@click.pass_context
def vistabook_list(ctx: click.Context, limit: int, page_number: int) -> None:
    """List all VistaBooks.

    Read-only — never modifies your VistaBooks.
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
    result = {"vistabooks": cards, "count": len(cards), "has_more": data.get("has_more", False)}
    format_output(result, ctx.obj.output_format, columns=VISTABOOK_COLUMNS, title="VistaBooks")


@vistabook_group.command("get")
@click.argument("vistabook_id")
@click.pass_context
def vistabook_get(ctx: click.Context, vistabook_id: str) -> None:
    """Get a VistaBook by ID.

    Read-only — never modifies the VistaBook.
    """
    data = _client(ctx).post("/get_context_card", {"card_id": vistabook_id, "card_type": "vistabook"})
    format_output(data, ctx.obj.output_format, title=f"VistaBook: {vistabook_id}")


# ---------------------------------------------------------------------------
# Helper commands
# ---------------------------------------------------------------------------


@vistabook_group.command("+run")
@click.argument("vistabook_id")
@click.option("--input", "user_input", default=None, help="Context or instructions for the run.")
@click.option(
    "--no-stream",
    "no_stream",
    is_flag=True,
    default=False,
    help="Wait for completion and return a single JSON result instead of streaming.",
)
@click.pass_context
def vistabook_run(ctx: click.Context, vistabook_id: str, user_input: str | None, no_stream: bool) -> None:
    """Start a VistaBook run — executes the workflow via the chat agent.

    > [!CAUTION] This is a write command — it creates a new VistaBook run and sends
    > messages to the chat agent. Confirm with the user before executing.

    By default, output is NDJSON (one JSON object per line) with simplified
    agent-friendly events: chat_session, tool start/done, text, and done.

    With --no-stream, waits for the full response and prints a single JSON
    object: {"result": "...", "chat_id": "...", "created_card_id": "..."}.
    """
    _UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)
    if not _UUID_RE.match(vistabook_id):
        output_error(3, "Invalid vistabook ID", f"Expected UUID format, got: {vistabook_id!r}")

    # Pass the vistabook reference in the instruction so the agent loads the card.
    instruction = f"[vistabook:{vistabook_id}] {user_input or 'Run this vistabook'}"
    body: dict = {"instruction": instruction, "stream": not no_stream}

    if no_stream:
        data = _client(ctx).post_long("/run", body)
        click.echo(json.dumps(data, default=str))
    else:
        for event in _client(ctx).stream_sse("/run", body):
            click.echo(json.dumps(event, default=str))


@vistabook_group.command("+status")
@click.argument("run_id", metavar="RUN_CHAT_ID")
@click.pass_context
def vistabook_status(ctx: click.Context, run_id: str) -> None:
    """Check the status of a VistaBook run.

    Read-only — uses the chat session endpoint to check run state.
    """
    data = _client(ctx).get(f"/chat_sessions/{run_id}")
    session = data.get("session", data)
    result = {
        "chat_id": run_id,
        "summary": session.get("summary", ""),
        "run_status": session.get("run_status", ""),
        "visibility": session.get("visibility", ""),
        "created_at": session.get("created_at", ""),
    }
    format_output(result, ctx.obj.output_format, title=f"Run: {run_id}")


@vistabook_group.command("+export")
@click.argument("vistabook_id")
@click.option(
    "--format", "export_format", type=click.Choice(["skill"]), default="skill", help="Export format (default: skill)."
)
@click.pass_context
def vistabook_export(ctx: click.Context, vistabook_id: str, export_format: str) -> None:
    """Export a VistaBook as a SKILL.md file for use in AI agents.

    Read-only — generates output but does not modify the VistaBook.
    """
    data = _client(ctx).post("/export_vistabook_to_skill", {"card_ids": [vistabook_id]})
    format_output(data, ctx.obj.output_format, title=f"Export: {vistabook_id}")
