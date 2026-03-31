"""deepvista — CLI entry point.

Usage:
  deepvista <service> <command> [options]
  deepvista <service> +<helper> [args] [options]

Global flags:
  --format json|table   Output format (default: json)
  --verbose             Show HTTP request/response details
  --dry-run             Show what would be sent without executing
  --api-url URL        Override backend URL
  --profile NAME        Use a named config profile (local, staging, etc.)
  --version             Show version and exit
"""

from __future__ import annotations

import click

from deepvista_cli import __version__
from deepvista_cli.client.http import DeepVistaClient
from deepvista_cli.commands.auth import auth_group
from deepvista_cli.commands.chat import chat_group
from deepvista_cli.commands.config import config_group
from deepvista_cli.commands.notes import notes_group
from deepvista_cli.commands.vistabase import vistabase_group
from deepvista_cli.commands.vistabook import vistabook_group
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
    """DeepVista CLI — manage your knowledge base, VistaBooks, notes, and chat."""
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


# Register command groups
cli.add_command(auth_group)
cli.add_command(config_group)
cli.add_command(vistabase_group)
cli.add_command(vistabook_group)
cli.add_command(notes_group)
cli.add_command(chat_group)


if __name__ == "__main__":
    cli()
