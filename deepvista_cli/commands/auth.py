"""deepvista auth — login, status, logout, and multi-account management."""

from __future__ import annotations

import time

import click

from deepvista_cli.auth.login import login_auto, login_with_code
from deepvista_cli.auth.tokens import (
    delete_tokens,
    load_all_accounts,
    load_tokens,
    remove_account,
    switch_active_account,
)
from deepvista_cli.config import credentials_path
from deepvista_cli.output.formatter import format_output, output_error


@click.group("auth")
def auth_group() -> None:
    """Authenticate with DeepVista."""


@auth_group.command("login")
@click.option("--code", default=None, help="One-time auth code from the browser.")
@click.pass_context
def auth_login(ctx: click.Context, code: str | None) -> None:
    """Login to DeepVista (adds account alongside existing ones).

    \b
    Interactive (opens browser, automatic):
      deepvista auth login

    \b
    Non-interactive (paste code from browser):
      deepvista auth login --code XXXX-XXXX

    \b
    You can login with multiple accounts. The most recent login
    becomes active. Switch with: deepvista auth switch <email>
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
    active_key, accounts = load_all_accounts(credentials_path(ctx.obj.profile))
    result = {
        "authenticated": True,
        "active_account": active_key,
        "email": tokens.email,
        "user_id": tokens.user_id,
        "token_expires_in_seconds": int(remaining),
        "token_expired": tokens.is_expired,
        "total_accounts": len(accounts),
    }
    format_output(result, ctx.obj.output_format)


@auth_group.command("list")
@click.pass_context
def auth_list(ctx: click.Context) -> None:
    """List all authenticated accounts on this profile."""
    creds_path = credentials_path(ctx.obj.profile)
    active, accounts = load_all_accounts(creds_path)

    if not accounts:
        click.echo("No accounts. Run: deepvista auth login", err=True)
        return

    rows = []
    for key, tokens in accounts.items():
        remaining = max(0, tokens.expires_at - time.time())
        rows.append(
            {
                "account": key,
                "active": key == active,
                "email": tokens.email,
                "user_id": tokens.user_id,
                "token_expires_in_seconds": int(remaining),
                "token_expired": tokens.is_expired,
            }
        )

    format_output(rows, ctx.obj.output_format, title="Accounts")


@auth_group.command("switch")
@click.argument("account")
@click.pass_context
def auth_switch(ctx: click.Context, account: str) -> None:
    """Switch the active account.

    \b
    ACCOUNT is the email (or user ID) shown by `deepvista auth list`.

    \b
    Example:
      deepvista auth switch alice@example.com
    """
    creds_path = credentials_path(ctx.obj.profile)
    try:
        tokens = switch_active_account(account, creds_path)
    except KeyError:
        # Show available accounts to help the user
        _active, accounts = load_all_accounts(creds_path)
        available = ", ".join(accounts.keys()) if accounts else "(none)"
        raise click.ClickException(f"Account '{account}' not found. Available: {available}")

    result = {"active_account": account, "email": tokens.email, "user_id": tokens.user_id}
    format_output(result, ctx.obj.output_format)
    click.echo(f"  Switched to {tokens.email or tokens.user_id}", err=True)


@auth_group.command("remove")
@click.argument("account")
@click.pass_context
def auth_remove(ctx: click.Context, account: str) -> None:
    """Remove a specific account from this profile.

    \b
    ACCOUNT is the email (or user ID) shown by `deepvista auth list`.

    \b
    Example:
      deepvista auth remove old@example.com
    """
    creds_path = credentials_path(ctx.obj.profile)
    if not remove_account(account, creds_path):
        _active, accounts = load_all_accounts(creds_path)
        available = ", ".join(accounts.keys()) if accounts else "(none)"
        raise click.ClickException(f"Account '{account}' not found. Available: {available}")

    result = {"removed": account}
    format_output(result, ctx.obj.output_format)
    click.echo(f"  Removed {account}", err=True)


@auth_group.command("logout")
@click.pass_context
def auth_logout(ctx: click.Context) -> None:
    """Clear all stored credentials for this profile."""
    delete_tokens(credentials_path(ctx.obj.profile))
    result = {"status": "logged_out"}
    format_output(result, ctx.obj.output_format)
    click.echo("  Logged out (all accounts removed).", err=True)
