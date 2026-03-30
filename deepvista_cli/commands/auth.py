"""deepvista auth — login, status, logout."""

from __future__ import annotations

import time

import click

from deepvista_cli.auth.login import login_interactive, login_with_code
from deepvista_cli.auth.tokens import delete_tokens, load_tokens
from deepvista_cli.output.formatter import format_output, output_error


@click.group("auth")
def auth_group() -> None:
    """Authenticate with DeepVista."""


@auth_group.command("login")
@click.option("--code", default=None, help="Auth code from the browser /auth/cli page.")
@click.pass_context
def auth_login(ctx: click.Context, code: str | None) -> None:
    """Login to DeepVista.

    \b
    Step 1 — open the login page:
      deepvista auth login

    \b
    Step 2 — paste the command shown in the browser:
      deepvista auth login --code <base64_code>
    """
    if code:
        tokens = login_with_code(code)
        result = {
            "status": "authenticated",
            "email": tokens.email,
            "user_id": tokens.user_id,
        }
        format_output(result, ctx.obj.output_format)
        click.echo(f"  Logged in as {tokens.email or tokens.user_id}", err=True)
    else:
        login_interactive(site_url=ctx.obj.site_url)


@auth_group.command("status")
@click.pass_context
def auth_status(ctx: click.Context) -> None:
    """Show current authentication state."""
    tokens = load_tokens()
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
    delete_tokens()
    result = {"status": "logged_out"}
    format_output(result, ctx.obj.output_format)
    click.echo("  Logged out.", err=True)
