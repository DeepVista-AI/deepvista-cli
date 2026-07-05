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
from deepvista_cli.client.origin import detect_agent_tool
from deepvista_cli.commands import emit, maybe_dry_run
from deepvista_cli.config import credentials_path
from deepvista_cli.output.formatter import output_error


@click.group("auth")
def auth_group() -> None:
    """Authenticate with DeepVista."""


def _print_next_steps() -> None:
    """Print actionable next-step options after a successful login (DV-942).

    Written to stderr so the JSON result on stdout stays machine-parseable.
    Suggestions adapt to whoever is driving the CLI (agent vs. terminal).
    """
    tool, _version = detect_agent_tool()
    if tool == "claude-code":
        steps = [
            "/refresh-skills — sync the DeepVista skill catalog",
            'say "Help me get started with DeepVista."',
            'deepvista notes +quick "<fact>" — capture your first note',
        ]
    elif tool == "deepvista-cli":  # direct terminal usage
        steps = [
            'deepvista notes +quick "My first note" — capture a note',
            "deepvista skill list — browse your workflow skills",
            "deepvista chat — talk to your DeepVista agent",
        ]
    else:  # some other AI agent is driving us
        steps = [
            'deepvista notes +quick "<fact>" — capture a note for the user',
            "deepvista skill list — discover available workflow skills",
            'deepvista vistabase +search "<topic>" — recall the user\'s stored context',
        ]
    click.echo("\n  What's next? Pick one:", err=True)
    for step in steps:
        click.echo(f"    - {step}", err=True)


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
        maybe_dry_run(ctx, dry_run, f"perform {method}", credentials_path=str(creds_path))
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
    emit(
        ctx,
        result,
    )
    click.echo(f"  Logged in as {tokens.email or tokens.user_id}", err=True)
    _print_next_steps()


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
    emit(
        ctx,
        result,
    )


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

    emit(
        ctx,
        rows,
        title="Accounts",
    )


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
        maybe_dry_run(ctx, dry_run, "switch active account", to=account)
        return

    try:
        tokens = switch_active_account(account, creds_path)
    except KeyError:
        _active, accounts = load_all_accounts(creds_path)
        available = ", ".join(accounts.keys()) if accounts else "(none)"
        raise click.ClickException(f"Account '{account}' not found. Available: {available}")

    result = {"active_account": account, "email": tokens.email, "user_id": tokens.user_id}
    emit(
        ctx,
        result,
    )
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
        maybe_dry_run(ctx, dry_run, "remove account", account=account)
        return

    if not remove_account(account, creds_path):
        _active, accounts = load_all_accounts(creds_path)
        available = ", ".join(accounts.keys()) if accounts else "(none)"
        raise click.ClickException(f"Account '{account}' not found. Available: {available}")

    result = {"removed": account}
    emit(
        ctx,
        result,
    )
    click.echo(f"  Removed {account}", err=True)


@auth_group.command("logout")
@click.option("--dry-run", is_flag=True, default=False, help="Preview what would happen without making any changes.")
@click.pass_context
def auth_logout(ctx: click.Context, dry_run: bool) -> None:
    """Clear all stored credentials for this profile."""
    creds_path = credentials_path(ctx.obj.profile)

    if maybe_dry_run(ctx, dry_run, "delete all stored credentials", credentials_path=str(creds_path)):
        return

    delete_tokens(creds_path)
    result = {"status": "logged_out"}
    emit(
        ctx,
        result,
    )
    click.echo("  Logged out (all accounts removed).", err=True)
