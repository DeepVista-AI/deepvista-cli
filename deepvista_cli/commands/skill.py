"""deepvista skill — list, get, run, status, export.

Skills (formerly Recipes / VistaBooks) are structured checklist workflows stored as
context cards (type=vistabook). Skill Runs are execution instances (type=vistabook_run)
linked via a master chat session.

Five resources: card · skill · vistabase · chat
"""

from __future__ import annotations

import json
import re
from typing import Any

import click

from deepvista_cli.client.http import DeepVistaClient
from deepvista_cli.output.formatter import format_output, output_error

SKILL_COLUMNS = ["id", "title", "display_status", "updated_at"]

SKILL_KINDS = ("persona", "workflow")

_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)


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


@skill_group.command("+catalog")
@click.option("--limit", default=50, help="Max skills to return (default 50).")
@click.pass_context
def skill_catalog(ctx: click.Context, limit: int) -> None:
    """List all Skills as compact catalog entries (id · title · snippet).

    Designed to be called by agents at startup so that all installed Skills
    are available in context without the user having to mention them explicitly.
    Each entry includes only the fields needed for an agent to decide whether
    a Skill is relevant: ``id``, ``title``, and a short ``snippet``.

    Read-only — never modifies your Skills.
    """
    data = _client(ctx).post(
        "/get_context_cards",
        {
            "card_type": "vistabook",
            "limit": limit,
            "page_number": 1,
        },
    )
    cards = data.get("cards", [])
    catalog = [
        {
            "id": c.get("id", ""),
            "title": c.get("title", ""),
            "snippet": c.get("snippet", ""),
        }
        for c in cards
    ]
    result = {"catalog": catalog, "count": len(catalog), "has_more": data.get("has_more", False)}
    format_output(
        result,
        ctx.obj.output_format,
        columns=["id", "title", "snippet"],
        title="Skill Catalog",
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


# ---------------------------------------------------------------------------
# create-from-note — synthesize skills from a source note via the agent
# ---------------------------------------------------------------------------


_CREATE_FROM_NOTE_INSTRUCTIONS = {
    "persona": (
        "A **persona skill** named `persona-<interviewee-slug>` that captures the "
        "interviewee's philosophy, voice, and decision-making lens. When loaded, "
        "the agent should respond in their voice and apply their frameworks. "
        "Include: who they are, core mental models drawn from the note, voice/"
        "tone rules, and a 3-5 phase advising sequence using <accordion>/<nli> "
        "shortcodes."
    ),
    "workflow": (
        "A **workflow skill** named `workflow-<topic-slug>` that turns the "
        "interviewee's frameworks or steps into an executable workflow. The user "
        "provides inputs; the workflow classifies, recommends, and returns a "
        "prioritized plan. Include: purpose, **a `## Workflow` section with a "
        "`mermaid` flowchart diagram that visualises the decision graph — "
        "ALWAYS open the fence with the `mermaid` info string (```mermaid) "
        "and use `flowchart TD`**, input schema, 4-6 phases using "
        "<accordion>/<nli> shortcodes, cheat sheet, and output format template. "
        "**Mermaid animation is REQUIRED, not optional.** For every edge in "
        "the flowchart, give it an ID using mermaid v11 syntax "
        "(`A e1@--> B`, `B e2@--> C`, …) and turn animation on with "
        "`e1@{ animation: slow }` for happy-path edges and "
        "`e1@{ animation: fast }` for tight loops. Every edge must have an "
        "ID and every ID must have an animation directive — a static "
        "diagram is a rendering bug, not an acceptable output. "
        "**Node-label rules (critical for rendering): every node label must "
        "be a single short line, ≤ 30 characters. Do NOT use `<br/>`, "
        "`\\n`, `<b>`, `<i>`, or any HTML tags inside `[ ... ]`, `( ... )`, "
        "or `{ ... }`. If you need a sub-description, chain a second node "
        "below instead of stuffing two lines into one node — mermaid's "
        "HTML-label sizing clips wrapped text and multi-line content will "
        "render cut off.** Keep the diagram under ~15 nodes — split into "
        "multiple diagrams if the workflow is larger."
    ),
}


def _build_create_from_note_prompt(note_id: str, kinds: tuple[str, ...]) -> str:
    lines = [
        f'Look up the note with id "{note_id}" using `read_context_card`. Read '
        "its full content. From that note, generate the skill(s) listed below. "
        "Ground every detail in the note — do not invent frameworks or advice "
        "the note doesn't contain.",
        "",
        "Skills to generate:",
    ]
    for i, kind in enumerate(kinds, 1):
        lines.append(f"{i}. {_CREATE_FROM_NOTE_INSTRUCTIONS[kind]}")
    lines.append("")
    lines.append(
        "**You MUST persist each skill by calling `upsert_context_card` with "
        '`card_type="skill"`.** Do not write the skill content to a local '
        "file, do not paste it in the chat response, do not skip the tool "
        "call. One `upsert_context_card` invocation per skill."
    )
    lines.append("")
    lines.append(
        "For each `upsert_context_card` call: set `title` to the skill name, "
        "put the full SKILL.md body in `description`, add relevant `tags` "
        "including the kind (`persona` or `workflow`), and link the source "
        f'note via `related_context_card_ids=["{note_id}"]`. After each call, '
        "confirm the returned card id in the chat response."
    )
    return "\n".join(lines)


@skill_group.command("create-from-note")
@click.argument("note_id")
@click.option(
    "--kind",
    "kinds",
    type=click.Choice(SKILL_KINDS, case_sensitive=False),
    multiple=True,
    default=SKILL_KINDS,
    help="Which skill kinds to synthesize. Repeatable. Default: persona and workflow.",
)
@click.option("--chat-id", default=None, help="Continue an existing synthesis session.")
@click.option(
    "--yes",
    "-y",
    "assume_yes",
    is_flag=True,
    default=False,
    help="Skip the write confirmation prompt. Use only in scripts/batch conversion.",
)
@click.option("--dry-run", is_flag=True, default=False, help="Preview the prompt without calling the agent.")
@click.pass_context
def skill_create_from_note(
    ctx: click.Context,
    note_id: str,
    kinds: tuple[str, ...],
    chat_id: str | None,
    assume_yes: bool,
    dry_run: bool,
) -> None:
    """Synthesize skill card(s) from a note via the DeepVista agent.

    Reads the note identified by `note_id` and invokes the agent with a curated
    prompt that produces one `persona` skill (interviewee's voice + frameworks)
    and/or one `workflow` skill (executable steps), grounded in the note's
    content. Each generated skill is stored as a context card of `type=skill`.

    Designed for batch-converting podcast / interview notes into reusable
    skills. Streams NDJSON identical to `chat +send` and `skill run`.

    > [!CAUTION] This is a write command — the agent creates skill cards in
    > the user's project. Confirm before executing.
    """
    if not _UUID_RE.match(note_id):
        output_error(3, "Invalid note ID", f"Expected UUID format, got: {note_id!r}")

    # Empty tuple shouldn't happen with default, but guard anyway.
    selected = kinds or SKILL_KINDS
    # De-dup while preserving order.
    seen: set[str] = set()
    selected = tuple(k for k in selected if not (k in seen or seen.add(k)))

    prompt = _build_create_from_note_prompt(note_id, selected)
    body: dict[str, Any] = {"user_instruction": prompt}
    if chat_id:
        body["chat_id"] = chat_id

    if dry_run:
        format_output(
            {
                "dry_run": True,
                "would": "synthesize skills from note via DeepVista agent",
                "note_id": note_id,
                "kinds": list(selected),
                "payload": body,
            },
            ctx.obj.output_format,
            entity_type="skill",
            base_url=ctx.obj.auth_url,
        )
        return

    if not assume_yes:
        click.confirm(
            f"The agent will create {len(selected)} skill card(s) from note {note_id}. Continue?",
            abort=True,
        )

    try:
        for event in _client(ctx).stream_sse("/imagine", body):
            click.echo(json.dumps(event, default=str))
    except (KeyboardInterrupt, click.Abort):
        click.echo(json.dumps({"type": "interrupted", "message": "skill synthesis aborted by user"}), err=True)
        raise
    except Exception as exc:
        click.echo(
            json.dumps({"type": "error", "message": f"skill synthesis stream failed: {exc}"}),
            err=True,
        )
        raise
