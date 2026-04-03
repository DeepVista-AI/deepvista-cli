"""deepvista auth — login, status, logout."""

from __future__ import annotations

import time

import click

from deepvista_cli.auth.login import login_auto, login_with_code
from deepvista_cli.auth.tokens import delete_tokens, load_tokens
from deepvista_cli.config import credentials_path
from deepvista_cli.output.formatter import format_output, output_error


@click.group("auth")
def auth_group() -> None:
    """Authenticate with DeepVista."""


@auth_group.command("login")
@click.option("--code", default=None, help="One-time auth code from the browser.")
@click.pass_context
def auth_login(ctx: click.Context, code: str | None) -> None:
    """Login to DeepVista.

    \b
    Interactive (opens browser, automatic):
      deepvista auth login

    \b
    Non-interactive (paste code from browser):
      deepvista auth login --code XXXX-XXXX
    """
    creds_path = credentials_path(ctx.obj.profile)

    if code:
        tokens = login_with_code(code, ctx.obj.auth_url, creds_path)
    else:
        tokens = login_auto(ctx.obj.auth_url, creds_path)

    result = {
        "status": "authenticated",
        "email": tokens.email,
        "user_id": tokens.user_id,
    }
    format_output(result, ctx.obj.output_format)
    click.echo(f"  Logged in as {tokens.email or tokens.user_id}", err=True)


@auth_group.command("status")
@click.pass_context
def auth_status(ctx: click.Context) -> None:
    """Show current authentication state."""
    tokens = load_tokens(credentials_path(ctx.obj.profile))
    if tokens is None:
        output_error(2, "Not authenticated. Run: deepvista auth login")
        return

    remaining = max(0, tokens.expires_at - time.time())
    result = {
        "authenticated": True,
        "email": tokens.email,
        "user_id": tokens.user_id,
        "token_expires_in_seconds": int(remaining),
        "token_expired": tokens.is_expired,
    }
    format_output(result, ctx.obj.output_format)


@auth_group.command("logout")
@click.pass_context
def auth_logout(ctx: click.Context) -> None:
    """Clear stored credentials."""
    delete_tokens(credentials_path(ctx.obj.profile))
    result = {"status": "logged_out"}
    format_output(result, ctx.obj.output_format)
    click.echo("  Logged out.", err=True)
