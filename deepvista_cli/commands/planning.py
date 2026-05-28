"""deepvista planning — daily planning notes that orchestrate the subagents (DV-853).

A *Daily Planning* note is a per-user, per-day note (``type=note``, title
``Daily Planning YYYYMMDD``) that lists the work each role-specialist subagent
is responsible for that day. The Claude Code ``/deepvista run`` slash command
reads the latest planning note and dispatches each role's section to its
matching ``@<role>`` subagent (``@marketing``, ``@engineering``, ``@gtm``…).
After the subagents finish, the main agent appends a summary back onto the
note via ``deepvista planning append-summary``.

Subcommands
-----------
``daily-note``       Create today's planning note if it doesn't exist.
``today``            Print today's planning note (id, title, markdown).
``append-summary``   Append a markdown summary block to a planning note.
``roles``            List the role sections a planning note carries.

This module is intentionally idempotent so SessionStart hooks and cron-style
schedulers can call it safely without producing duplicates.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any

import click

from deepvista_cli import session_note as sn
from deepvista_cli.client.http import DeepVistaClient
from deepvista_cli.client.origin import detect_agent_tool
from deepvista_cli.output.formatter import format_output, output_error

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PLANNING_TAG = "daily-planning"
DEFAULT_ROLES: tuple[str, ...] = ("marketing", "engineering", "gtm")
TITLE_PREFIX = "Daily Planning"


def _client(ctx: click.Context) -> DeepVistaClient:
    return ctx.obj._client


def _today_yyyymmdd() -> str:
    return _dt.date.today().strftime("%Y%m%d")


def _planning_title(date_str: str) -> str:
    return f"{TITLE_PREFIX} {date_str}"


def _planning_tags(date_str: str) -> list[str]:
    """Tags applied to every planning note: agent tag + date + bucket."""
    agent, _ = detect_agent_tool()
    from deepvista_cli.commands.agents import load_agent_id_for_active_agent

    agent_id = load_agent_id_for_active_agent()
    return [
        sn.build_agent_tag(agent, agent_id),
        PLANNING_TAG,
        f"date:{date_str}",
    ]


def _seed_markdown(roles: tuple[str, ...], date_str: str) -> str:
    """Initial markdown for a freshly-created daily planning note.

    Each role gets a level-2 section the matching ``@<role>`` subagent reads
    and acts on. The ``Workflow today`` section is for cross-cutting tasks
    that the main agent runs directly (rather than delegating).
    """
    lines = [
        f"# {_planning_title(date_str)}",
        "",
        "_Tasks for each role specialist. Each `## <role>` section is dispatched to the",
        f"matching `@<role>` subagent when you run `/deepvista run`. (Generated {date_str}.)_",
        "",
        "## Workflow today",
        "",
        "- _List cross-cutting workflows to run today._",
        "",
    ]
    for role in roles:
        lines.extend(
            [
                f"## {role}",
                "",
                f"- _Task brief for `@{role}` — what should the {role} specialist accomplish today?_",
                "",
            ]
        )
    lines.extend(["## Summary", "", "_Subagent results land here after `/deepvista run` finishes._", ""])
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Lookup
# ---------------------------------------------------------------------------


def _find_planning_note(client: DeepVistaClient, date_str: str) -> dict[str, Any] | None:
    """Return the planning note for ``date_str`` if one already exists.

    Uses tag-based filtering rather than title matching so subsequent edits to
    the title (e.g. localisation) don't break idempotency.
    """
    data = client.post(
        "/get_context_cards",
        {
            "card_type": "note",
            "limit": 50,
            "tag_contains": f"date:{date_str}",
        },
    )
    for card in data.get("cards") or []:
        tags = card.get("tags") or []
        if PLANNING_TAG in tags and f"date:{date_str}" in tags:
            return card
    # Fall back to title match in case tag_contains is not honoured by the server.
    title_target = _planning_title(date_str)
    for card in data.get("cards") or []:
        if str(card.get("title") or "").strip() == title_target:
            return card
    return None


# ---------------------------------------------------------------------------
# Click group
# ---------------------------------------------------------------------------


@click.group("planning")
def planning_group() -> None:
    """Daily planning notes that orchestrate the role specialist subagents.

    A planning note is one note per user per day carrying a section per role
    (``marketing`` / ``engineering`` / ``gtm`` by default). ``/deepvista run``
    dispatches each section to the matching ``@<role>`` subagent and appends
    a summary at the end.
    """


@planning_group.command("daily-note")
@click.option("--date", "date_str", default=None, help="YYYYMMDD (default: today).")
@click.option(
    "--roles",
    default=None,
    help='Comma-separated roles to seed (default: "marketing,engineering,gtm").',
)
@click.option(
    "--force",
    is_flag=True,
    default=False,
    help="Recreate the note even if one already exists for that date.",
)
@click.option("--dry-run", is_flag=True, default=False, help="Preview what would happen without making any changes.")
@click.pass_context
def planning_daily_note(
    ctx: click.Context,
    date_str: str | None,
    roles: str | None,
    force: bool,
    dry_run: bool,
) -> None:
    """Create today's daily planning note (idempotent).

    By default this is a no-op when today's note already exists — safe to call
    from a SessionStart hook or a cron job. Pass ``--force`` to create a fresh
    note anyway (the previous one is left in place; both will coexist).

    > [!CAUTION] This is a write command — confirm with the user before executing.
    """
    date_str = date_str or _today_yyyymmdd()
    if len(date_str) != 8 or not date_str.isdigit():
        output_error(3, "Invalid --date", f"Expected YYYYMMDD, got: {date_str}")
        return

    role_list = tuple(r.strip() for r in (roles or ",".join(DEFAULT_ROLES)).split(",") if r.strip())
    if not role_list:
        output_error(3, "Invalid --roles", "Provide at least one non-empty role.")
        return

    client = _client(ctx)
    existing = None if force else _find_planning_note(client, date_str)
    if existing is not None:
        result = {
            "created": False,
            "reason": "already_exists",
            "note": existing,
            "date": date_str,
        }
        format_output(
            result,
            ctx.obj.output_format,
            title=f"Daily Planning {date_str} (existing)",
            entity_type="note",
            base_url=ctx.obj.auth_url,
        )
        return

    body = {
        "card_type": "note",
        "title": _planning_title(date_str),
        "description": _seed_markdown(role_list, date_str),
        "tags": _planning_tags(date_str),
        "enrich": True,
    }

    if dry_run:
        format_output(
            {"dry_run": True, "would": "create planning note", "payload": body},
            ctx.obj.output_format,
            entity_type="note",
            base_url=ctx.obj.auth_url,
        )
        return

    created = client.post("/create_context_card", body)
    format_output(
        {"created": True, "note": created, "date": date_str, "roles": list(role_list)},
        ctx.obj.output_format,
        title=f"Daily Planning {date_str}",
        entity_type="note",
        base_url=ctx.obj.auth_url,
    )


@planning_group.command("today")
@click.option("--date", "date_str", default=None, help="YYYYMMDD (default: today).")
@click.pass_context
def planning_today(ctx: click.Context, date_str: str | None) -> None:
    """Print today's planning note (id, title, markdown body).

    Read-only. Returns a structured result with the full ``description`` so
    the ``/deepvista run`` slash command can parse the per-role sections.
    Exits non-zero (via ``output_error``) when no note exists for the date.
    """
    date_str = date_str or _today_yyyymmdd()
    if len(date_str) != 8 or not date_str.isdigit():
        output_error(3, "Invalid --date", f"Expected YYYYMMDD, got: {date_str}")
        return

    note = _find_planning_note(_client(ctx), date_str)
    if note is None:
        output_error(
            4,
            f"No planning note for {date_str}",
            "Run `deepvista planning daily-note` to create one.",
        )
        return

    sections = _parse_role_sections(note.get("description") or "")
    result = {
        "date": date_str,
        "note_id": note.get("id"),
        "title": note.get("title"),
        "description": note.get("description"),
        "roles": list(sections.keys()),
        "sections": sections,
    }
    format_output(
        result,
        ctx.obj.output_format,
        title=f"Daily Planning {date_str}",
        entity_type="note",
        base_url=ctx.obj.auth_url,
    )


@planning_group.command("append-summary")
@click.option("--note-id", required=True, help="Planning note id to append to.")
@click.option("--summary", default=None, help="Summary markdown to append.")
@click.option(
    "--summary-file",
    default=None,
    help="Read summary markdown from a file path. Use '-' for stdin. Overrides --summary.",
)
@click.option("--dry-run", is_flag=True, default=False, help="Preview what would happen without making any changes.")
@click.pass_context
def planning_append_summary(
    ctx: click.Context,
    note_id: str,
    summary: str | None,
    summary_file: str | None,
    dry_run: bool,
) -> None:
    """Append a ``## Summary`` block to a planning note.

    Used by the ``/deepvista run`` slash command after every subagent has
    returned: the main agent collects each role specialist's deliverable and
    appends them under a single timestamped summary, so the planning note
    becomes the day's standup record.

    > [!CAUTION] This is a write command — confirm with the user before executing.
    """
    from deepvista_cli.commands import resolve_content

    summary_text = resolve_content(summary, summary_file)
    if not summary_text or not summary_text.strip():
        output_error(3, "Missing summary", "Provide --summary or --summary-file.")
        return

    client = _client(ctx)
    note = client.post("/get_context_card", {"card_id": note_id, "card_type": "note"})
    card = note.get("card") or note
    existing = str(card.get("description") or "")
    stamp = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    appended = existing.rstrip() + (f"\n\n## Summary — {stamp}\n\n{summary_text.strip()}\n")

    body: dict[str, Any] = {"card_id": note_id, "description": appended}

    if dry_run:
        format_output(
            {"dry_run": True, "would": "append summary", "note_id": note_id, "summary_chars": len(summary_text)},
            ctx.obj.output_format,
            entity_type="note",
            base_url=ctx.obj.auth_url,
        )
        return

    updated = client.post("/update_context_card", body)
    format_output(
        {"appended": True, "note_id": note_id, "card": updated},
        ctx.obj.output_format,
        title=f"Appended summary to {note_id}",
        entity_type="note",
        base_url=ctx.obj.auth_url,
    )


@planning_group.command("roles")
@click.option("--date", "date_str", default=None, help="YYYYMMDD (default: today).")
@click.pass_context
def planning_roles(ctx: click.Context, date_str: str | None) -> None:
    """List the role sections present in today's planning note.

    Read-only. Useful for the slash command: given the role list it knows
    which ``@<role>`` subagents to invoke.
    """
    date_str = date_str or _today_yyyymmdd()
    note = _find_planning_note(_client(ctx), date_str)
    if note is None:
        format_output(
            {"date": date_str, "roles": []},
            ctx.obj.output_format,
            entity_type="note",
            base_url=ctx.obj.auth_url,
        )
        return

    sections = _parse_role_sections(note.get("description") or "")
    format_output(
        {"date": date_str, "note_id": note.get("id"), "roles": list(sections.keys())},
        ctx.obj.output_format,
        entity_type="note",
        base_url=ctx.obj.auth_url,
    )


# ---------------------------------------------------------------------------
# Section parser
# ---------------------------------------------------------------------------

_RESERVED_SECTIONS = {"workflow today", "summary"}


def _parse_role_sections(markdown: str) -> dict[str, str]:
    """Extract ``## <role>`` blocks from a planning note's markdown.

    Returns a mapping ``{role_lowercased: section_body}``. Reserved sections
    (``Workflow today`` / ``Summary``) are excluded so the slash command can
    iterate ``sections`` as the role-dispatch list without filtering.
    """
    sections: dict[str, str] = {}
    current: str | None = None
    buf: list[str] = []
    for line in markdown.splitlines():
        if line.startswith("## "):
            if current is not None and current.lower() not in _RESERVED_SECTIONS:
                sections[current.lower()] = "\n".join(buf).strip()
            current = line[3:].strip()
            buf = []
        elif current is not None:
            buf.append(line)
    if current is not None and current.lower() not in _RESERVED_SECTIONS:
        sections[current.lower()] = "\n".join(buf).strip()
    return sections


# Re-export the JSON parser so tests / other modules can build on it without
# importing private names.
__all__ = [
    "DEFAULT_ROLES",
    "PLANNING_TAG",
    "TITLE_PREFIX",
    "planning_group",
]
