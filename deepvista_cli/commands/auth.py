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


def _print_next_steps(project_id: str | None = None) -> None:
    """Print the post-login welcome on stderr (DV-1493, DV-1646).

    Short command + description pairs keep the copy scannable; the
    machine-readable login JSON on stdout is untouched.
    """
    if project_id:
        steps = [("deepvista tasks run", "start the task daemon for your current project")]
    else:
        steps = [
            ("deepvista project use <id|slug>", "pick the project to work in"),
            ("deepvista tasks run", "start its task daemon"),
        ]

    click.echo("\n  What's next?", err=True)
    for command, description in steps:
        click.echo(f"    {click.style(command, fg='cyan', bold=True)}", err=True)
        click.echo(f"      {click.style(description, dim=True)}", err=True)

    click.echo(
        f"\n  New here? Open your AI agent and say: {click.style('Help me get started with DeepVista.', italic=True)}",
        err=True,
    )


@auth_group.command("login")
@click.option("--code", default=None, help="One-time auth code from the browser.")
@click.option("--dry-run", is_flag=True, default=False, help="Preview what would happen without making any changes.")
@click.pass_context
def auth_login(ctx: click.Context, code: str | None, dry_run: bool) -> None:
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

    if dry_run:
        method = "login with code" if code else "browser-based OAuth login"
        format_output(
            {"dry_run": True, "would": f"perform {method}", "credentials_path": str(creds_path)},
            ctx.obj.output_format,
        )
        return

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
    click.echo(
        f"\n  {click.style('✓', fg='green', bold=True)} Logged in as "
        f"{click.style(tokens.email or tokens.user_id, bold=True)}",
        err=True,
    )
    _print_next_steps(ctx.obj.project_id)


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
@click.option("--dry-run", is_flag=True, default=False, help="Preview what would happen without making any changes.")
@click.pass_context
def auth_switch(ctx: click.Context, account: str, dry_run: bool) -> None:
    """Switch the active account.

    \b
    ACCOUNT is the email (or user ID) shown by `deepvista auth list`.

    \b
    Example:
      deepvista auth switch alice@example.com
    """
    creds_path = credentials_path(ctx.obj.profile)

    if dry_run:
        _active, accounts = load_all_accounts(creds_path)
        if account not in accounts:
            available = ", ".join(accounts.keys()) if accounts else "(none)"
            raise click.ClickException(f"Account '{account}' not found. Available: {available}")
        format_output(
            {"dry_run": True, "would": "switch active account", "to": account},
            ctx.obj.output_format,
        )
        return

    try:
        tokens = switch_active_account(account, creds_path)
    except KeyError:
        _active, accounts = load_all_accounts(creds_path)
        available = ", ".join(accounts.keys()) if accounts else "(none)"
        raise click.ClickException(f"Account '{account}' not found. Available: {available}")

    result = {"active_account": account, "email": tokens.email, "user_id": tokens.user_id}
    format_output(result, ctx.obj.output_format)
    click.echo(f"  Switched to {tokens.email or tokens.user_id}", err=True)


@auth_group.command("remove")
@click.argument("account")
@click.option("--dry-run", is_flag=True, default=False, help="Preview what would happen without making any changes.")
@click.pass_context
def auth_remove(ctx: click.Context, account: str, dry_run: bool) -> None:
    """Remove a specific account from this profile.

    \b
    ACCOUNT is the email (or user ID) shown by `deepvista auth list`.

    \b
    Example:
      deepvista auth remove old@example.com
    """
    creds_path = credentials_path(ctx.obj.profile)

    if dry_run:
        _active, accounts = load_all_accounts(creds_path)
        if account not in accounts:
            available = ", ".join(accounts.keys()) if accounts else "(none)"
            raise click.ClickException(f"Account '{account}' not found. Available: {available}")
        format_output(
            {"dry_run": True, "would": "remove account", "account": account},
            ctx.obj.output_format,
        )
        return

    if not remove_account(account, creds_path):
        _active, accounts = load_all_accounts(creds_path)
        available = ", ".join(accounts.keys()) if accounts else "(none)"
        raise click.ClickException(f"Account '{account}' not found. Available: {available}")

    result = {"removed": account}
    format_output(result, ctx.obj.output_format)
    click.echo(f"  Removed {account}", err=True)


@auth_group.command("logout")
@click.option("--dry-run", is_flag=True, default=False, help="Preview what would happen without making any changes.")
@click.pass_context
def auth_logout(ctx: click.Context, dry_run: bool) -> None:
    """Clear all stored credentials for this profile."""
    creds_path = credentials_path(ctx.obj.profile)

    if dry_run:
        format_output(
            {"dry_run": True, "would": "delete all stored credentials", "credentials_path": str(creds_path)},
            ctx.obj.output_format,
        )
        return

    delete_tokens(creds_path)
    result = {"status": "logged_out"}
    format_output(result, ctx.obj.output_format)
    click.echo("  Logged out (all accounts removed).", err=True)
