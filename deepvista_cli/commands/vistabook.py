"""deepvista vistabook — list, get, +run, +status, +export.

VistaBooks are structured checklist workflows stored as context cards (type=vistabook).
VistaBook Runs are execution instances (type=vistabook_run) linked via a master chat.
"""

from __future__ import annotations

import json

import click

from deepvista_cli.client.http import DeepVistaClient
from deepvista_cli.output.formatter import format_output

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
@click.pass_context
def vistabook_run(ctx: click.Context, vistabook_id: str, user_input: str | None) -> None:
    """Start a VistaBook run — executes the workflow via the chat agent.

    > [!CAUTION] This is a write command — it creates a new VistaBook run and sends
    > messages to the chat agent. Confirm with the user before executing.

    Output is NDJSON (one JSON object per line) as the agent streams its response.
    """
    # Note: context_card_id triggers watch mode on /imagine, NOT chat processing.
    # Pass the vistabook reference in user_instruction instead.
    instruction = user_input or "Run this vistabook"
    body: dict = {
        "user_instruction": f"[vistabook:{vistabook_id}] {instruction}",
    }

    for event in _client(ctx).stream_sse("/imagine", body):
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
