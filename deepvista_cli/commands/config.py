"""deepvista config — manage CLI profiles for different environments."""

from __future__ import annotations

import click

from deepvista_cli.commands import emit, maybe_dry_run
from deepvista_cli.config import delete_profile, get_profile, list_profiles, set_profile


@click.group("config")
def config_group() -> None:
    """Manage CLI profiles (local, staging, production, etc.)."""


@config_group.command("set")
@click.argument("profile_name")
@click.option("--api-url", required=True, help="Backend API URL for this profile.")
@click.option("--auth-url", default=None, help="Frontend URL for login (default: https://app.deepvista.ai).")
@click.option("--dry-run", is_flag=True, default=False, help="Preview what would happen without making any changes.")
@click.pass_context
def config_set(ctx: click.Context, profile_name: str, api_url: str, auth_url: str | None, dry_run: bool) -> None:
    """Create or update a profile.

    \b
    Example:
      deepvista config set local --api-url http://localhost:8080 --auth-url http://localhost:3000
    """
    payload: dict = {"api_url": api_url}
    if auth_url:
        payload["auth_url"] = auth_url

    if maybe_dry_run(ctx, dry_run, "create or update profile", profile=profile_name, settings=payload):
        return

    set_profile(profile_name, payload)
    output: dict = {"profile": profile_name, **payload}
    emit(
        ctx,
        output,
    )
    click.echo(f"Profile '{profile_name}' saved.", err=True)


@config_group.command("list")
@click.pass_context
def config_list(ctx: click.Context) -> None:
    """List all profiles."""
    profiles = list_profiles()
    if not profiles:
        click.echo(
            "No profiles configured. Create one with: deepvista config set <name> --api-url ...",
            err=True,
        )
        return
    emit(
        ctx,
        profiles,
        title="Profiles",
    )


@config_group.command("show")
@click.argument("profile_name")
@click.pass_context
def config_show(ctx: click.Context, profile_name: str) -> None:
    """Show a profile's settings."""
    profile = get_profile(profile_name)
    if not profile:
        click.echo(f"Profile '{profile_name}' not found.", err=True)
        return
    emit(
        ctx,
        profile,
        title=f"Profile: {profile_name}",
    )


@config_group.command("delete")
@click.argument("profile_name")
@click.option("--dry-run", is_flag=True, default=False, help="Preview what would happen without making any changes.")
@click.pass_context
def config_delete(ctx: click.Context, profile_name: str, dry_run: bool) -> None:
    """Delete a profile."""
    if dry_run:
        exists = get_profile(profile_name) is not None
        if not exists:
            click.echo(f"Profile '{profile_name}' not found.", err=True)
            return
        maybe_dry_run(ctx, dry_run, "delete profile", profile=profile_name)
        return

    if delete_profile(profile_name):
        emit(
            ctx,
            {"deleted": profile_name},
        )
    else:
        click.echo(f"Profile '{profile_name}' not found.", err=True)
