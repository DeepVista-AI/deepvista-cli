"""``deepvista pull`` — materialize a card's bundle onto this machine (DV-1816).

Generic by design: a bundle is just "a set of paths a card carries", so the
same verb installs a skill repo, syncs a document's attachments, or fetches a
single blob. Nothing here is skill-specific.

    deepvista pull <skill-id>                 # → ~/.claude/skills/dv-<slug>/
    deepvista pull <skill-id> --to ./work     # → ./work/
    deepvista pull dv://card/<id>/scripts/x.py --to ./work

Works anywhere the CLI runs — a cloud machine or a laptop. The machine
registry is only the dispatch path for remotely-triggered installs, not a gate
on pulling.
"""

from __future__ import annotations

import click

from deepvista_cli import bundle, skill_catalog
from deepvista_cli.client.http import DeepVistaClient
from deepvista_cli.commands import apply_project_override, project_option
from deepvista_cli.config import CLIConfig
from deepvista_cli.output.formatter import output_error


def _client(ctx: click.Context) -> DeepVistaClient:
    return DeepVistaClient(ctx.obj["config"] if isinstance(ctx.obj, dict) else CLIConfig())


def _default_target(card: dict) -> str:
    """Where a bundle lands when the user doesn't say: the bundle store.

    Not the stub dir (DV-1869). Stubs live wherever the syncing agent directory
    wants them — under the Claude Code plugin that's a version-pinned path the
    marketplace updater wipes on upgrade — so bundles kept beside them were
    deleted by an upgrade with no old location left to migrate from. The store is
    keyed by card id and survives both.

    `skill load` prints the root and tells the agent to resolve the body's
    relative paths against it, which is what the agent needed anyway: its cwd is
    the project, never the skill directory.
    """
    card_id = str(card.get("id") or "")
    return str(skill_catalog.bundle_root_for(card_id, card))


@click.command("pull")
@click.argument("target")
@click.option("--to", "destination", default=None, help="Directory to write into. Defaults to the skill's stub dir.")
@click.option("--force", is_flag=True, default=False, help="Overwrite locally edited files instead of preserving them.")
@click.option("--dry-run", is_flag=True, default=False, help="Show what would be written without touching disk.")
@project_option
@click.pass_context
def pull_command(
    ctx: click.Context,
    target: str,
    destination: str | None,
    force: bool,
    dry_run: bool,
    project_override: str | None,
) -> None:
    """Download a card's bundled files to a local directory.

    TARGET is a card id or a ``dv://card/<id>[/<path>]`` reference.

    > [!CAUTION] This writes files to your machine that an agent may later
    > execute. Only pull bundles from cards you or your team authored.
    """
    apply_project_override(ctx, project_override)
    client = _client(ctx)

    card_id, single_path = _parse_target(target)

    try:
        data = client.post("/get_context_card", {"card_id": card_id})
    except SystemExit:
        raise
    card = (data or {}).get("card") or data or {}
    body = str(card.get("content") or card.get("description") or "")

    try:
        files = bundle.parse_bundle_files(body)
    except bundle.BundleError as exc:
        output_error(4, "Invalid bundle manifest", str(exc))

    if single_path is not None:
        files = [f for f in files if f.path == single_path]
        if not files:
            output_error(4, "Not found", f"'{single_path}' is not in this card's manifest")

    if not files:
        click.echo(f"No bundled files on card {card_id}.")
        return

    root = _resolve_root(destination, card)

    if dry_run:
        click.echo(f"Would write {len(files)} file(s) to {root}:")
        for entry in files:
            click.echo(f"  {entry.mode}  {entry.path}")
        return

    try:
        result = bundle.materialize_bundle(files, root, bundle.make_fetcher(client, card_id), force=force)
    except bundle.BundleError as exc:
        output_error(4, "Bundle install failed", str(exc))

    _report(root, result)


def _parse_target(target: str) -> tuple[str, str | None]:
    """Accept a bare card id or a ``dv://card/<id>[/<path>]`` reference."""
    if not target.startswith("dv://"):
        return target, None
    remainder = target[len("dv://") :]
    kind, _, rest = remainder.partition("/")
    if kind != "card" or not rest:
        output_error(3, "Unsupported reference", "pull takes a card id or dv://card/<id>[/<path>]")
    card_id, _, path = rest.partition("/")
    return card_id, path or None


def _resolve_root(destination: str | None, card: dict):
    from pathlib import Path

    return Path(destination).expanduser() if destination else Path(_default_target(card)).expanduser()


def _report(root, result: dict[str, list[str]]) -> None:
    written, skipped = result["written"], result["skipped"]
    preserved, removed = result["preserved"], result["removed"]

    click.echo(f"Bundle installed to {root}")
    click.echo(f"  {len(written)} written, {len(skipped)} unchanged")
    for path in written:
        click.echo(f"  + {path}")
    for path in removed:
        click.echo(f"  - {path} (no longer in manifest)")
    if preserved:
        click.echo(f"\n  {len(preserved)} file(s) kept — they differ from both the old and new manifest,")
        click.echo("  which means you edited them locally. Re-run with --force to overwrite:")
        for path in preserved:
            click.echo(f"    ! {path}")
