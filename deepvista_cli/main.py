"""deepvista — CLI entry point.

Resources: card · skill · chat
Aliases:   notes     (shorthand for card --type note)
           vistabase (alias for card; hidden from --help)

Usage:
  deepvista <resource> <command> [options]
  deepvista <resource> +<helper> [args] [options]

Global flags:
  --format json|table   Output format (default: json)
  --verbose             Show HTTP request/response details
  --dry-run             Show what would be sent without executing
  --api-url URL         Override backend URL
  --profile NAME        Use a named config profile (local, staging, etc.)
  --version             Show version and exit
"""

from __future__ import annotations

import click

from deepvista_cli import __version__
from deepvista_cli.client.http import DeepVistaClient
from deepvista_cli.commands.agents import agents_group
from deepvista_cli.commands.auth import auth_group
from deepvista_cli.commands.card import card_group
from deepvista_cli.commands.chat import chat_group
from deepvista_cli.commands.config import config_group
from deepvista_cli.commands.notes import notes_group
from deepvista_cli.commands.project import project_group
from deepvista_cli.commands.pull import pull_command
from deepvista_cli.commands.push import push_command
from deepvista_cli.commands.schedule import schedule_group
from deepvista_cli.commands.session import session_group
from deepvista_cli.commands.skill import skill_group
from deepvista_cli.commands.tasks import tasks_group
from deepvista_cli.commands.upgrade import upgrade_command
from deepvista_cli.config import DEFAULT_API_URL, CLIConfig


class _RootGroup(click.Group):
    """Root group that keeps backward-compatible aliases invokable while hiding
    them from the `--help` listing.

    `vistabase` is an alias for `card` (the same knowledge-base commands); showing
    both would clutter help with duplicate rows.
    """

    _HIDDEN_ALIASES = {"vistabase"}

    def list_commands(self, ctx: click.Context) -> list[str]:
        return [name for name in super().list_commands(ctx) if name not in self._HIDDEN_ALIASES]


@click.group(cls=_RootGroup)
@click.version_option(__version__, prog_name="deepvista")
@click.option("--format", "output_format", type=click.Choice(["json", "table"]), default="json", help="Output format.")
@click.option("--verbose", is_flag=True, default=False, help="Show HTTP request/response details.")
@click.option("--dry-run", is_flag=True, default=False, help="Show what would be sent without executing.")
@click.option("--api-url", default=None, help=f"Override backend URL (default: {DEFAULT_API_URL}).")
@click.option("--profile", default="default", help="Use a named config profile (e.g. local, staging).")
@click.option(
    "--project",
    "project_id",
    default=None,
    help="Scope this invocation to a project id or slug (overrides the working project / DEEPVISTA_PROJECT_ID).",
)
@click.pass_context
def cli(
    ctx: click.Context,
    output_format: str,
    verbose: bool,
    dry_run: bool,
    api_url: str | None,
    profile: str,
    project_id: str | None,
) -> None:
    """DeepVista CLI — chat, notes, skills, and knowledge cards from your terminal.

    Resources: project · card · skill · chat

    Requests are scoped to a project: pick one with `deepvista project use <id>`
    (persisted per profile), or override per call with `--project <id>` /
    `DEEPVISTA_PROJECT_ID`. When none is set the backend uses your default project.
    """
    config = CLIConfig(
        output_format=output_format,
        verbose=verbose,
        dry_run=dry_run,
        profile=profile,
    )

    # Apply profile settings (resolves project_id from profile + DEEPVISTA_PROJECT_ID).
    # CLI flags still take precedence below.
    config.apply_profile(profile)

    # CLI flags override everything
    if api_url:
        config.api_url = api_url
    if project_id:
        config.project_id = project_id

    # Attach config + lazy client to context
    ctx.ensure_object(CLIConfig)
    ctx.obj = config
    ctx.obj._client = DeepVistaClient(config)


# Project scoping — pick a working project that scopes every other command.
cli.add_command(project_group)

# Primary resources
# `card` is the canonical knowledge-base command; `vistabase` is a
# backward-compatible alias for the same commands (hidden from --help by _RootGroup).
cli.add_command(card_group)
cli.add_command(card_group, name="vistabase")
cli.add_command(skill_group)
cli.add_command(chat_group)
# DV-1816: materialize a card's bundled files onto this machine.
cli.add_command(pull_command)
# DV-1869: the inverse — upload a skill directory and its files.
cli.add_command(push_command)

# Agent identity heartbeat (used by the Claude Code plugin hooks)
cli.add_command(agents_group)
# Opt-in recurring daily-planning job
cli.add_command(schedule_group)
# Agent session transcripts (DV-742) — `init` / `tick` / `finalize`
cli.add_command(session_group)
# Tasks dispatched to this Machine: web-chat task cards (DV-1247) + the
# pull-based CLI-command / workflow queue (DV-936). Registered as `tasks`.
cli.add_command(tasks_group)
# Supporting commands
cli.add_command(auth_group)
cli.add_command(config_group)
cli.add_command(upgrade_command)

# Legacy aliases for backward compatibility
cli.add_command(notes_group)  # notes = cards with type=note (explicit knowledge layer)


if __name__ == "__main__":
    cli()
