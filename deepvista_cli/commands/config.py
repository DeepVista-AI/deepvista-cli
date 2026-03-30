"""deepvista config — manage CLI profiles for different environments."""

from __future__ import annotations

import click

from deepvista_cli.config import delete_profile, get_profile, list_profiles, set_profile
from deepvista_cli.output.formatter import format_output


@click.group("config")
def config_group() -> None:
    """Manage CLI profiles (local, staging, production, etc.)."""


@config_group.command("set")
@click.argument("profile_name")
@click.option("--base-url", required=True, help="Backend API URL for this profile.")
@click.option("--api-key", required=True, help="API key for this profile.")
@click.option("--site-url", default=None, help="Frontend URL for login (default: https://app.deepvista.ai).")
@click.pass_context
def config_set(ctx: click.Context, profile_name: str, base_url: str, api_key: str, site_url: str | None) -> None:
    """Create or update a profile.

    \b
    Example:
      deepvista config set local --base-url http://localhost:8080 --api-key dvsa_xxx --site-url http://localhost:3000
    """
    settings: dict = {"base_url": base_url, "api_key": api_key}
    if site_url:
        settings["site_url"] = site_url
    set_profile(profile_name, settings)
    output = {"profile": profile_name, "base_url": base_url, "api_key": f"{api_key[:8]}..."}
    if site_url:
        output["site_url"] = site_url
    format_output(output, ctx.obj.output_format)
    click.echo(f"Profile '{profile_name}' saved.", err=True)


@config_group.command("list")
@click.pass_context
def config_list(ctx: click.Context) -> None:
    """List all profiles."""
    profiles = list_profiles()
    if not profiles:
        click.echo(
            "No profiles configured. Create one with: deepvista config set <name> --base-url ... --api-key ...",
            err=True,
        )
        return
    # Mask API keys in output
    masked = {}
    for name, settings in profiles.items():
        masked[name] = {**settings}
        if "api_key" in masked[name]:
            masked[name]["api_key"] = masked[name]["api_key"][:8] + "..."
    format_output(masked, ctx.obj.output_format, title="Profiles")


@config_group.command("show")
@click.argument("profile_name")
@click.pass_context
def config_show(ctx: click.Context, profile_name: str) -> None:
    """Show a profile's settings."""
    profile = get_profile(profile_name)
    if not profile:
        click.echo(f"Profile '{profile_name}' not found.", err=True)
        return
    masked = {**profile}
    if "api_key" in masked:
        masked["api_key"] = masked["api_key"][:8] + "..."
    format_output(masked, ctx.obj.output_format, title=f"Profile: {profile_name}")


@config_group.command("delete")
@click.argument("profile_name")
@click.pass_context
def config_delete(ctx: click.Context, profile_name: str) -> None:
    """Delete a profile."""
    if delete_profile(profile_name):
        format_output({"deleted": profile_name}, ctx.obj.output_format)
    else:
        click.echo(f"Profile '{profile_name}' not found.", err=True)
