"""``deepvista push`` — upload a skill directory to Vistabase (DV-1869).

The inverse of ``deepvista pull``. DV-1816 shipped the storage half — content
addressed blobs, ``dv://`` refs, ``files:`` manifests, and an installer — but
nothing that could put a multi-file skill *in*, so a skill with ``scripts/``
could be pulled onto a machine only if someone had hand-driven the raw upload
contract first.

    deepvista push ./skills/pdf-report              # create a new skill card
    deepvista push ./skills/pdf-report --card <id>  # update an existing one
    deepvista push ./skills/pdf-report --dry-run    # list what would upload

``SKILL.md`` becomes the card description; every other file becomes a bundle
entry. Re-pushing an unchanged tree uploads nothing: content addressing means
the server already holds every sha and answers ``alreadyExists``.
"""

from __future__ import annotations

from pathlib import Path

import click

from deepvista_cli import bundle
from deepvista_cli.client.http import DeepVistaClient
from deepvista_cli.commands import apply_project_override, project_option
from deepvista_cli.config import CLIConfig
from deepvista_cli.output.formatter import output_error

# A human running `push` is an explicit act, not an agent's inference, so the
# card is searchable immediately. Left to default, an `X-DeepVista-Origin`
# request lands `unconfirmed` (DV-793) and `/get_context_cards` filters it out —
# the skill would exist but never appear in `skill list`, never sync a stub, and
# never be findable by a dispatched task (DV-1869).
PUSH_STATUS = "confirmed"


def _client(ctx: click.Context) -> DeepVistaClient:
    return DeepVistaClient(ctx.obj["config"] if isinstance(ctx.obj, dict) else CLIConfig())


@click.command("push")
@click.argument("directory", type=click.Path(exists=True, file_okay=False))
@click.option("--card", "card_id", default=None, help="Update this existing card instead of creating a new one.")
@click.option("--title", default=None, help="Card title. Defaults to the frontmatter `name`, else the dir name.")
@click.option("--dry-run", is_flag=True, default=False, help="Show what would upload without writing anything.")
@project_option
@click.pass_context
def push_command(
    ctx: click.Context,
    directory: str,
    card_id: str | None,
    title: str | None,
    dry_run: bool,
    project_override: str | None,
) -> None:
    """Upload a skill directory — SKILL.md plus its bundled files — to Vistabase.

    > [!CAUTION] This is a write command. It uploads file contents to your
    > project and creates or updates a card. Preview with --dry-run first.
    """
    apply_project_override(ctx, project_override)

    root = Path(directory).expanduser().resolve()
    body_path = bundle.find_skill_body(root)
    if body_path is None:
        output_error(3, "Not a skill directory", f"no SKILL.md in {root}")
        return

    body = body_path.read_text(encoding="utf-8")
    try:
        files = bundle.collect_bundle_files(root, exclude=body_path)
        composed = bundle.splice_manifest(body, files)
    except bundle.BundleError as exc:
        output_error(4, "Invalid bundle", str(exc))
        return

    scalars = bundle.parse_frontmatter_scalars(body)
    resolved_title = title or scalars.get("name") or root.name

    if dry_run:
        click.echo(f"Would push '{resolved_title}' ({len(files)} bundled file(s)) from {root}:")
        for entry in files:
            click.echo(f"  {entry.mode}  {entry.size or 0:>9}  {entry.sha256[:12]}…  {entry.path}")
        target = f"card {card_id}" if card_id else "a new skill card"
        click.echo(f"\n  SKILL.md → {target} description ({len(composed)} bytes)")
        return

    client = _client(ctx)
    # Blobs first, card second — deliberately. A rejected save then leaves
    # orphan bytes, which DV-1816 accepted by design (no refcount, no sweep;
    # blobs are small and deduped). The reverse order trades that for a card
    # advertising a bundle whose bytes never arrived, which makes every
    # `dv://card/{id}/{path}` 404 and degrades `skill load` for real readers.
    try:
        uploaded = bundle.upload_bundle(client, root, files)
    except bundle.BundleError as exc:
        output_error(4, "Upload failed", str(exc))
        return

    if card_id:
        data = client.post(
            "/update_context_card", {"card_id": card_id, "description": composed, "title": resolved_title}
        )
    else:
        data = client.post(
            "/create_context_card",
            {
                "card_type": "skill",
                "title": resolved_title,
                "description": composed,
                "status": PUSH_STATUS,
            },
        )

    card = (data or {}).get("card") or data or {}
    new_id = str(card.get("id") or card_id or "")

    click.echo(f"Pushed '{resolved_title}' to card {new_id}")
    click.echo(f"  {len(uploaded['uploaded'])} uploaded, {len(uploaded['deduped'])} already stored")
    for path in uploaded["uploaded"]:
        click.echo(f"  ↑ {path}")
    for path in uploaded["deduped"]:
        click.echo(f"  = {path}")
    if new_id:
        click.echo(f"\n  https://app.deepvista.ai/skills/{new_id}")
