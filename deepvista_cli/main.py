"""deepvista — CLI entry point.

Resources: card · skill · vistabase · chat
Aliases:   notes (shorthand for card --type note)
           memory (deprecated alias for vistabase)

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
from deepvista_cli.commands.lint import lint_command
from deepvista_cli.commands.memory import vistabase_group
from deepvista_cli.commands.notes import notes_group
from deepvista_cli.commands.session import session_group
from deepvista_cli.commands.skill import skill_group
from deepvista_cli.commands.upgrade import upgrade_command
from deepvista_cli.config import DEFAULT_API_URL, CLIConfig


@click.group()
@click.version_option(__version__, prog_name="deepvista")
@click.option("--format", "output_format", type=click.Choice(["json", "table"]), default="json", help="Output format.")
@click.option("--verbose", is_flag=True, default=False, help="Show HTTP request/response details.")
@click.option("--dry-run", is_flag=True, default=False, help="Show what would be sent without executing.")
@click.option("--api-url", default=None, help=f"Override backend URL (default: {DEFAULT_API_URL}).")
@click.option("--profile", default="default", help="Use a named config profile (e.g. local, staging).")
@click.pass_context
def cli(
    ctx: click.Context, output_format: str, verbose: bool, dry_run: bool, api_url: str | None, profile: str
) -> None:
    """DeepVista CLI — chat, notes, skills, and vistabase from your terminal.

    Resources: card · skill · vistabase · chat
    """
    config = CLIConfig(
        output_format=output_format,
        verbose=verbose,
        dry_run=dry_run,
        profile=profile,
    )

    # Apply profile settings (env vars and CLI flags still take precedence)
    config.apply_profile(profile)

    # CLI flag overrides everything
    if api_url:
        config.api_url = api_url

    # Attach config + lazy client to context
    ctx.ensure_object(CLIConfig)
    ctx.obj = config
    ctx.obj._client = DeepVistaClient(config)


# Primary resources (five resources)
cli.add_command(card_group)
cli.add_command(skill_group)
cli.add_command(vistabase_group)
cli.add_command(chat_group)

# Make `vistabase` a synonym for `card` — all card subcommands work under `vistabase` too
for _name, _cmd in card_group.commands.items():
    if _name not in vistabase_group.commands:
        vistabase_group.add_command(_cmd, name=_name)

# Backward compatibility: `memory` is a deprecated alias for `vistabase`
cli.add_command(vistabase_group, name="memory")
# Agent orchestration
cli.add_command(agents_group)
# Agent session transcripts (DV-742) — `init` / `tick` / `finalize`
cli.add_command(session_group)
# Supporting commands
cli.add_command(auth_group)
cli.add_command(config_group)
cli.add_command(upgrade_command)
cli.add_command(lint_command)

# Legacy aliases for backward compatibility
cli.add_command(notes_group)  # notes = cards with type=note (explicit knowledge layer)


@cli.command("ui")
@click.pass_context
def launch_ui(ctx: click.Context) -> None:
    """Launch the DeepVista terminal UI (TUI).

    Requires: pip install 'deepvista-cli[ui]'
    """
    try:
        from deepvista_cli.tui.app import DeepVistaApp
    except ImportError:
        raise click.ClickException(
            "TUI dependencies not installed.\n"
            "Run: pip install 'deepvista-cli[ui]'\n"
            "  or: uv pip install 'deepvista-cli[ui]'"
        )

    app = DeepVistaApp(cli_config=ctx.obj)
    app.run()


if __name__ == "__main__":
    cli()
