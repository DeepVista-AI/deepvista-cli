"""deepvista vistabase — CRUD + search for context cards (knowledge base).

Endpoints:
  POST /get_context_cards      -> list / search
  POST /get_context_card       -> get by id
  POST /create_context_card    -> create
  POST /update_context_card    -> update
  DELETE /context_cards/{id}   -> delete
"""

from __future__ import annotations

import click

from deepvista_cli.client.http import DeepVistaClient
from deepvista_cli.output.formatter import format_output, output_error

CARD_TYPES = [
    "person",
    "organization",
    "message",
    "todo",
    "topic",
    "keypoint",
    "file",
    "note",
    "vistabook",
    "vistabook_run",
]

CARD_COLUMNS = ["id", "type", "title", "display_status", "updated_at"]


def _client(ctx: click.Context) -> DeepVistaClient:
    return ctx.obj._client


@click.group("vistabase")
def vistabase_group() -> None:
    """Manage your VistaBase knowledge cards."""


# ---------------------------------------------------------------------------
# CRUD commands
# ---------------------------------------------------------------------------


@vistabase_group.command("list")
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
@click.pass_context
def vistabase_list(
    ctx: click.Context,
    card_type: str | None,
    display_status: str | None,
    limit: int,
    page_number: int,
    order_by: str | None,
    order_direction: str | None,
) -> None:
    """List context cards with optional filtering."""
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
    format_output(result, ctx.obj.output_format, columns=CARD_COLUMNS, title="VistaBase Cards", entity_type="vistabase")


@vistabase_group.command("get")
@click.argument("card_id")
@click.pass_context
def vistabase_get(ctx: click.Context, card_id: str) -> None:
    """Get a context card by ID."""
    data = _client(ctx).post("/get_context_card", {"card_id": card_id})
    format_output(data, ctx.obj.output_format, title=f"Card: {card_id}", entity_type="vistabase")


@vistabase_group.command("create")
@click.option(
    "--type", "card_type", type=click.Choice(CARD_TYPES, case_sensitive=False), required=True, help="Card type."
)
@click.option("--title", required=True, help="Card title.")
@click.option("--content", "description", default=None, help="Card content/description (markdown).")
@click.option("--tags", default=None, help='Tags as JSON array: \'["tag1","tag2"]\'.')
@click.option("--no-enrich", is_flag=True, default=False, help="Skip entity enrichment.")
@click.pass_context
def vistabase_create(
    ctx: click.Context,
    card_type: str,
    title: str,
    description: str | None,
    tags: str | None,
    no_enrich: bool,
) -> None:
    """Create a new context card.

    > [!CAUTION] This is a write command — confirm with the user before executing.
    """
    import json as _json

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

    data = _client(ctx).post("/create_context_card", body)
    format_output(data, ctx.obj.output_format, title="Created Card", entity_type="vistabase")


@vistabase_group.command("update")
@click.argument("card_id")
@click.option("--title", default=None, help="New title.")
@click.option("--content", "description", default=None, help="New content/description.")
@click.option("--type", "card_type", type=click.Choice(CARD_TYPES, case_sensitive=False), default=None)
@click.option("--tags", default=None, help='Tags as JSON array: \'["tag1","tag2"]\'.')
@click.option("--status", "display_status", type=click.Choice(["pinned", "archived"]), default=None)
@click.pass_context
def vistabase_update(
    ctx: click.Context,
    card_id: str,
    title: str | None,
    description: str | None,
    card_type: str | None,
    tags: str | None,
    display_status: str | None,
) -> None:
    """Update a context card.

    > [!CAUTION] This is a write command — confirm with the user before executing.
    """
    import json as _json

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

    data = _client(ctx).post("/update_context_card", body)
    format_output(data, ctx.obj.output_format, title=f"Updated Card: {card_id}", entity_type="vistabase")


@vistabase_group.command("delete")
@click.argument("card_id")
@click.option("--type", "card_type", default=None, help="Card type hint (optional, speeds up deletion).")
@click.pass_context
def vistabase_delete(ctx: click.Context, card_id: str, card_type: str | None) -> None:
    """Delete a context card.

    > [!CAUTION] This is a destructive write command — confirm with the user before executing.
    """
    params = {}
    if card_type:
        params["card_type"] = card_type
    data = _client(ctx).delete(f"/context_cards/{card_id}", params=params)
    format_output(data, ctx.obj.output_format, entity_type="vistabase")


# ---------------------------------------------------------------------------
# Helper commands (+search, +similar, +pin, +archive)
# ---------------------------------------------------------------------------


@vistabase_group.command("+search")
@click.argument("query")
@click.option("--type", "card_type", type=click.Choice(CARD_TYPES, case_sensitive=False), default=None)
@click.option("--limit", default=10, help="Max results (default 10).")
@click.pass_context
def vistabase_search(ctx: click.Context, query: str, card_type: str | None, limit: int) -> None:
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
        result, ctx.obj.output_format, columns=CARD_COLUMNS, title=f"Search: {query}", entity_type="vistabase"
    )


@vistabase_group.command("+similar")
@click.argument("card_id")
@click.option("--limit", default=5, help="Max results (default 5).")
@click.pass_context
def vistabase_similar(ctx: click.Context, card_id: str, limit: int) -> None:
    """Find context cards similar to a given card.

    Read-only — never modifies your knowledge base.
    """
    # Fetch the card first to get its content for similarity search
    card = _client(ctx).post("/get_context_card", {"card_id": card_id})
    title = card.get("title", "")
    snippet = card.get("snippet", "")
    query = f"{title} {snippet}".strip()

    if not query:
        output_error(3, "Card has no content for similarity search", f"Card: {card_id}")

    body: dict = {"query_text": query, "limit": limit}
    data = _client(ctx).post("/get_context_cards", body)
    # Filter out the source card itself
    cards = [c for c in data.get("cards", []) if c.get("id") != card_id]
    result = {"source_card_id": card_id, "similar": cards, "count": len(cards)}
    format_output(
        result, ctx.obj.output_format, columns=CARD_COLUMNS, title=f"Similar to: {card_id}", entity_type="vistabase"
    )


@vistabase_group.command("+pin")
@click.argument("card_id")
@click.pass_context
def vistabase_pin(ctx: click.Context, card_id: str) -> None:
    """Pin a context card.

    > [!CAUTION] This is a write command.
    """
    data = _client(ctx).post("/update_context_card", {"card_id": card_id, "display_status": "pinned"})
    format_output(data, ctx.obj.output_format, entity_type="vistabase")


@vistabase_group.command("+archive")
@click.argument("card_id")
@click.pass_context
def vistabase_archive(ctx: click.Context, card_id: str) -> None:
    """Archive a context card.

    > [!CAUTION] This is a write command.
    """
    data = _client(ctx).post("/update_context_card", {"card_id": card_id, "display_status": "archived"})
    format_output(data, ctx.obj.output_format, entity_type="vistabase")
