"""deepvista recipe — list, get, run, status, export.

Recipes (formerly VistaBooks) are structured checklist workflows stored as
context cards (type=recipe). Recipe Runs are execution instances (type=recipe_run)
linked via a master chat session.

Five resources: card · recipe · memory · chat · skill
"""

from __future__ import annotations

import json
import re

import click

from deepvista_cli.client.http import DeepVistaClient
from deepvista_cli.output.formatter import format_output, output_error

RECIPE_COLUMNS = ["id", "title", "display_status", "updated_at"]


def _client(ctx: click.Context) -> DeepVistaClient:
    return ctx.obj._client


@click.group("recipe")
def recipe_group() -> None:
    """Manage Recipes — structured executable workflows."""


# ---------------------------------------------------------------------------
# Read commands
# ---------------------------------------------------------------------------


@recipe_group.command("list")
@click.option("--limit", default=20, help="Max results (default 20).")
@click.option("--page", "page_number", default=1, help="Page number.")
@click.pass_context
def recipe_list(ctx: click.Context, limit: int, page_number: int) -> None:
    """List all Recipes.

    Read-only — never modifies your Recipes.
    """
    # Support both legacy "vistabook" type and new "recipe" type
    data = _client(ctx).post(
        "/get_context_cards",
        {
            "card_type": "vistabook",
            "limit": limit,
            "page_number": page_number,
        },
    )
    cards = data.get("cards", [])
    result = {"recipes": cards, "count": len(cards), "has_more": data.get("has_more", False)}
    format_output(
        result,
        ctx.obj.output_format,
        columns=RECIPE_COLUMNS,
        title="Recipes",
        entity_type="recipe",
        base_url=ctx.obj.auth_url,
    )


@recipe_group.command("get")
@click.argument("recipe_id")
@click.pass_context
def recipe_get(ctx: click.Context, recipe_id: str) -> None:
    """Get a Recipe by ID.

    Read-only — never modifies the Recipe.
    """
    data = _client(ctx).post("/get_context_card", {"card_id": recipe_id, "card_type": "vistabook"})
    format_output(
        data, ctx.obj.output_format, title=f"Recipe: {recipe_id}", entity_type="recipe", base_url=ctx.obj.auth_url
    )


# ---------------------------------------------------------------------------
# Action commands
# ---------------------------------------------------------------------------


@recipe_group.command("run")
@click.argument("recipe_id")
@click.option("--input", "user_input", default=None, help="Context or instructions for the run.")
@click.pass_context
def recipe_run(ctx: click.Context, recipe_id: str, user_input: str | None) -> None:
    """Run a Recipe — executes the workflow via the chat agent.

    > [!CAUTION] This is a write command — it creates a new Recipe run and sends
    > messages to the chat agent. Confirm with the user before executing.

    Output is NDJSON (one JSON object per line) as the agent streams its response.
    """
    _UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)
    if not _UUID_RE.match(recipe_id):
        output_error(3, "Invalid recipe ID", f"Expected UUID format, got: {recipe_id!r}")

    instruction = user_input or "Run this recipe"
    body: dict = {
        "user_instruction": f"[vistabook:{recipe_id}] {instruction}",
    }

    for event in _client(ctx).stream_sse("/imagine", body):
        click.echo(json.dumps(event, default=str))


@recipe_group.command("status")
@click.argument("run_id", metavar="RUN_CHAT_ID")
@click.pass_context
def recipe_status(ctx: click.Context, run_id: str) -> None:
    """Check the status of a Recipe run.

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


@recipe_group.command("export")
@click.argument("recipe_id")
@click.option(
    "--format", "export_format", type=click.Choice(["skill"]), default="skill", help="Export format (default: skill)."
)
@click.pass_context
def recipe_export(ctx: click.Context, recipe_id: str, export_format: str) -> None:
    """Export a Recipe as a SKILL.md file for use in AI agents.

    Read-only — generates output but does not modify the Recipe.
    """
    data = _client(ctx).post("/export_vistabook_to_skill", {"card_ids": [recipe_id]})
    format_output(
        data, ctx.obj.output_format, title=f"Export: {recipe_id}", entity_type="recipe", base_url=ctx.obj.auth_url
    )


# ---------------------------------------------------------------------------
# Marketplace: Discover & Install
# ---------------------------------------------------------------------------

DISCOVER_COLUMNS = ["id", "title", "category", "version", "installed"]


@recipe_group.command("discover")
@click.option("--search", "-s", default=None, help="Search term to filter recipes.")
@click.option(
    "--category",
    "-c",
    type=click.Choice(["persona", "productivity", "workflow"]),
    default=None,
    help="Filter by category.",
)
@click.option("--limit", default=50, help="Max results (default 50).")
@click.pass_context
def recipe_discover(ctx: click.Context, search: str | None, category: str | None, limit: int) -> None:
    """Discover public recipes from the marketplace.

    Read-only — browse available recipes without installing anything.
    Use `deepvista recipe install <id>` to install a recipe.
    """
    body: dict = {"limit": limit, "offset": 0}
    if search:
        body["search"] = search
    if category:
        body["category"] = category

    data = _client(ctx).post("/discover_recipes", body)
    recipes = data.get("recipes", [])
    result = {"recipes": recipes, "count": len(recipes), "has_more": data.get("has_more", False)}
    format_output(
        result,
        ctx.obj.output_format,
        columns=DISCOVER_COLUMNS,
        title="Marketplace Recipes",
        entity_type="recipe",
        base_url=ctx.obj.auth_url,
    )


@recipe_group.command("install")
@click.argument("recipe_id")
@click.pass_context
def recipe_install(ctx: click.Context, recipe_id: str) -> None:
    """Install a marketplace recipe into your library.

    > [!CAUTION] This is a write command — it creates a new Recipe in your
    > library from the marketplace. Confirm with the user before executing.

    The recipe_id must match an entry in the marketplace registry.
    Use `deepvista recipe discover` to browse available recipes.
    """
    data = _client(ctx).post("/install_marketplace_recipe", {"recipe_id": recipe_id})

    if data.get("already_installed"):
        click.echo(json.dumps({"status": "already_installed", "card": data.get("card", {})}, indent=2, default=str))
    else:
        click.echo(json.dumps({"status": "installed", "card": data.get("card", {})}, indent=2, default=str))
