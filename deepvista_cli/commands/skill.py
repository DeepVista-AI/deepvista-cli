"""deepvista skill — list, get, run, status, export.

Skills (formerly Recipes / VistaBooks) are structured checklist workflows stored as
context cards (type=vistabook). Skill Runs are execution instances (type=vistabook_run)
linked via a master chat session.

Five resources: card · skill · vistabase · chat
"""

from __future__ import annotations

import json
import re

import click

from deepvista_cli.client.http import DeepVistaClient
from deepvista_cli.output.formatter import format_output, output_error

SKILL_COLUMNS = ["id", "title", "display_status", "updated_at"]


def _client(ctx: click.Context) -> DeepVistaClient:
    return ctx.obj._client


@click.group("skill")
def skill_group() -> None:
    """Manage Skills — structured executable workflows."""


# ---------------------------------------------------------------------------
# Read commands
# ---------------------------------------------------------------------------


@skill_group.command("list")
@click.option("--limit", default=20, help="Max results (default 20).")
@click.option("--page", "page_number", default=1, help="Page number.")
@click.pass_context
def skill_list(ctx: click.Context, limit: int, page_number: int) -> None:
    """List all Skills.

    Read-only — never modifies your Skills.
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
    result = {"skills": cards, "count": len(cards), "has_more": data.get("has_more", False)}
    format_output(
        result,
        ctx.obj.output_format,
        columns=SKILL_COLUMNS,
        title="Skills",
        entity_type="skill",
        base_url=ctx.obj.auth_url,
    )


@skill_group.command("get")
@click.argument("skill_id")
@click.pass_context
def skill_get(ctx: click.Context, skill_id: str) -> None:
    """Get a Skill by ID.

    Read-only — never modifies the Skill.
    """
    data = _client(ctx).post("/get_context_card", {"card_id": skill_id, "card_type": "vistabook"})
    format_output(
        data, ctx.obj.output_format, title=f"Skill: {skill_id}", entity_type="skill", base_url=ctx.obj.auth_url
    )


# ---------------------------------------------------------------------------
# Action commands
# ---------------------------------------------------------------------------


@skill_group.command("run")
@click.argument("skill_id")
@click.option("--input", "user_input", default=None, help="Context or instructions for the run.")
@click.option("--dry-run", is_flag=True, default=False, help="Preview what would happen without making any changes.")
@click.pass_context
def skill_run(ctx: click.Context, skill_id: str, user_input: str | None, dry_run: bool) -> None:
    """Run a Skill — executes the workflow via the chat agent.

    > [!CAUTION] This is a write command — it creates a new Skill run and sends
    > messages to the chat agent. Confirm with the user before executing.

    Output is NDJSON (one JSON object per line) as the agent streams its response.
    """
    _UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)
    if not _UUID_RE.match(skill_id):
        output_error(3, "Invalid skill ID", f"Expected UUID format, got: {skill_id!r}")

    instruction = user_input or "Run this skill"
    body: dict = {
        "user_instruction": f'<contextCard id="{skill_id}" cardType="vistabook"></contextCard> {instruction}',
    }

    if dry_run:
        format_output(
            {"dry_run": True, "would": "start Skill run", "skill_id": skill_id, "instruction": instruction},
            ctx.obj.output_format,
            entity_type="skill",
            base_url=ctx.obj.auth_url,
        )
        return

    for event in _client(ctx).stream_sse("/imagine", body):
        click.echo(json.dumps(event, default=str))


@skill_group.command("status")
@click.argument("run_id", metavar="RUN_CHAT_ID")
@click.pass_context
def skill_status(ctx: click.Context, run_id: str) -> None:
    """Check the status of a Skill run.

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


@skill_group.command("export")
@click.argument("skill_id")
@click.option(
    "--format", "export_format", type=click.Choice(["skill"]), default="skill", help="Export format (default: skill)."
)
@click.pass_context
def skill_export(ctx: click.Context, skill_id: str, export_format: str) -> None:
    """Export a Skill as a SKILL.md file for use in AI agents.

    Read-only — generates output but does not modify the Skill.
    """
    data = _client(ctx).post("/export_vistabook_to_skill", {"card_ids": [skill_id]})
    format_output(
        data, ctx.obj.output_format, title=f"Export: {skill_id}", entity_type="skill", base_url=ctx.obj.auth_url
    )


# ---------------------------------------------------------------------------
# Marketplace: Discover & Install
# ---------------------------------------------------------------------------

DISCOVER_COLUMNS = ["id", "title", "category", "version", "installed"]


@skill_group.command("discover")
@click.option("--search", "-s", default=None, help="Search term to filter skills.")
@click.option(
    "--category",
    "-c",
    type=click.Choice(["persona", "productivity", "workflow"]),
    default=None,
    help="Filter by category.",
)
@click.option("--limit", default=50, help="Max results (default 50).")
@click.pass_context
def skill_discover(ctx: click.Context, search: str | None, category: str | None, limit: int) -> None:
    """Discover public skills from the marketplace.

    Read-only — browse available skills without installing anything.
    Use `deepvista skill install <id>` to install a skill.
    """
    body: dict = {"limit": limit, "offset": 0}
    if search:
        body["search"] = search
    if category:
        body["category"] = category

    data = _client(ctx).post("/discover_skills", body)
    skills = data.get("skills", [])
    result = {"skills": skills, "count": len(skills), "has_more": data.get("has_more", False)}
    format_output(
        result,
        ctx.obj.output_format,
        columns=DISCOVER_COLUMNS,
        title="Marketplace Skills",
        entity_type="skill",
        base_url=ctx.obj.auth_url,
    )


@skill_group.command("install")
@click.argument("skill_id")
@click.option("--dry-run", is_flag=True, default=False, help="Preview what would happen without making any changes.")
@click.pass_context
def skill_install(ctx: click.Context, skill_id: str, dry_run: bool) -> None:
    """Install a marketplace skill into your library.

    > [!CAUTION] This is a write command — it creates a new Skill in your
    > library from the marketplace. Confirm with the user before executing.

    The skill_id must match an entry in the marketplace registry.
    Use `deepvista skill discover` to browse available skills.
    """
    if dry_run:
        format_output(
            {"dry_run": True, "would": "install marketplace skill", "skill_id": skill_id},
            ctx.obj.output_format,
            entity_type="skill",
            base_url=ctx.obj.auth_url,
        )
        return

    data = _client(ctx).post("/install_marketplace_skill", {"skill_id": skill_id})

    if data.get("already_installed"):
        click.echo(json.dumps({"status": "already_installed", "card": data.get("card", {})}, indent=2, default=str))
    else:
        click.echo(json.dumps({"status": "installed", "card": data.get("card", {})}, indent=2, default=str))
