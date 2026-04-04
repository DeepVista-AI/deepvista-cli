"""deepvista memory — view and search implicit memory context.

Memory is the implicit context layer — automatically accumulated from Chat
sessions, never directly editable by users. It surfaces in Chat when relevant.

Five resources: card · recipe · memory · chat · skill

Endpoints:
  GET  /memory/summary         -> memory overview
  POST /memory/search          -> search memory entries
"""

from __future__ import annotations

import click

from deepvista_cli.client.http import DeepVistaClient
from deepvista_cli.output.formatter import format_output

MEMORY_COLUMNS = ["id", "summary", "source", "created_at"]


def _client(ctx: click.Context) -> DeepVistaClient:
    return ctx.obj._client


@click.group("memory")
def memory_group() -> None:
    """View implicit memory context accumulated from your conversations."""


@memory_group.command("show")
@click.option("--limit", default=20, help="Max memory entries to show (default 20).")
@click.pass_context
def memory_show(ctx: click.Context, limit: int) -> None:
    """Show a summary of your accumulated memory context.

    Memory is automatically built from your Chat conversations.
    Read-only — memory can only be updated through Chat interactions.
    """
    data = _client(ctx).get("/memory/summary", params={"limit": limit})
    format_output(data, ctx.obj.output_format, columns=MEMORY_COLUMNS, title="Memory Context")


@memory_group.command("search")
@click.argument("query")
@click.option("--limit", default=10, help="Max results (default 10).")
@click.pass_context
def memory_search(ctx: click.Context, query: str, limit: int) -> None:
    """Search through your memory context.

    Read-only — never modifies memory.
    """
    body: dict = {"query": query, "limit": limit}
    data = _client(ctx).post("/memory/search", body)
    entries = data.get("entries", data.get("results", []))
    result = {"query": query, "results": entries, "count": len(entries)}
    format_output(result, ctx.obj.output_format, columns=MEMORY_COLUMNS, title=f"Memory: {query}")
