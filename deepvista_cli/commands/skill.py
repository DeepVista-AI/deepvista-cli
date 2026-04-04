"""deepvista skill — manage and run AI agent skills.

Skills are reusable agent capabilities stored in SKILL.md format.
They can be exported from Recipes or created manually.

Five resources: card · recipe · memory · chat · skill

Endpoints:
  POST /get_context_cards      -> list skills (card_type=skill)
  POST /get_context_card       -> get skill by id
  POST /export_vistabook_to_skill -> export recipe as skill
"""

from __future__ import annotations

import json

import click

from deepvista_cli.client.http import DeepVistaClient
from deepvista_cli.output.formatter import format_output

SKILL_COLUMNS = ["id", "title", "display_status", "updated_at"]


def _client(ctx: click.Context) -> DeepVistaClient:
    return ctx.obj._client


@click.group("skill")
def skill_group() -> None:
    """Manage AI agent skills."""


@skill_group.command("list")
@click.option("--limit", default=20, help="Max results (default 20).")
@click.option("--page", "page_number", default=1, help="Page number.")
@click.pass_context
def skill_list(ctx: click.Context, limit: int, page_number: int) -> None:
    """List all available Skills.

    Read-only.
    """
    data = _client(ctx).post(
        "/get_context_cards",
        {
            "card_type": "skill",
            "limit": limit,
            "page_number": page_number,
        },
    )
    cards = data.get("cards", [])
    result = {"skills": cards, "count": len(cards), "has_more": data.get("has_more", False)}
    format_output(result, ctx.obj.output_format, columns=SKILL_COLUMNS, title="Skills")


@skill_group.command("get")
@click.argument("skill_id")
@click.pass_context
def skill_get(ctx: click.Context, skill_id: str) -> None:
    """Get a Skill by ID.

    Read-only.
    """
    data = _client(ctx).post("/get_context_card", {"card_id": skill_id, "card_type": "skill"})
    format_output(data, ctx.obj.output_format, title=f"Skill: {skill_id}")


@skill_group.command("run")
@click.argument("skill_id")
@click.option("--input", "user_input", default=None, help="Context or input for the skill.")
@click.pass_context
def skill_run(ctx: click.Context, skill_id: str, user_input: str | None) -> None:
    """Run a Skill via the chat agent.

    > [!CAUTION] This is a write command — it invokes the skill through Chat.
    Confirm with the user before executing.

    Output is NDJSON (one JSON object per line) as the agent streams its response.
    """
    instruction = user_input or "Run this skill"
    body: dict = {
        "user_instruction": f"[skill:{skill_id}] {instruction}",
    }

    for event in _client(ctx).stream_sse("/imagine", body):
        click.echo(json.dumps(event, default=str))
