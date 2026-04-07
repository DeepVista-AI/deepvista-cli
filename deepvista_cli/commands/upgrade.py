"""deepvista upgrade — check for and install CLI and skill updates."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import urllib.request
from http.client import HTTPResponse
from pathlib import Path
from urllib.parse import urlparse

import click

from deepvista_cli import __version__


def _safe_urlopen(url: str, timeout: int = 10) -> HTTPResponse:
    """Open a URL, but only allow https:// scheme to prevent file:// attacks."""
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise ValueError(f"Only https:// URLs are allowed, got: {parsed.scheme}://")
    return urllib.request.urlopen(url, timeout=timeout)  # nosec B310 - scheme validated above


REPO = "DeepVista-AI/deepvista-cli"
SKILL_RAW_BASE = f"https://raw.githubusercontent.com/{REPO}/main/skills"

SKILL_DIRS = [
    Path.home() / ".claude" / "skills",
    Path.home() / ".agents" / "skills",
    Path.home() / ".cursor" / "skills",
    Path.home() / ".opencode" / "skills",
]


# ---------------------------------------------------------------------------
# Skill helpers
# ---------------------------------------------------------------------------


def _parse_skill_version(skill_md: str) -> str | None:
    in_frontmatter = False
    for line in skill_md.splitlines():
        if line.strip() == "---":
            if not in_frontmatter:
                in_frontmatter = True
                continue
            else:
                break
        if in_frontmatter and line.startswith("version:"):
            val = line.split(":", 1)[1].strip().strip('"').strip("'")
            return val or None
    return None


def _fetch_remote_skill_version(skill_name: str) -> str | None:
    url = f"{SKILL_RAW_BASE}/{skill_name}/SKILL.md"
    try:
        with _safe_urlopen(url, timeout=5) as resp:
            return _parse_skill_version(resp.read().decode("utf-8", errors="replace"))
    except Exception:
        return None


def _find_installed_skills() -> dict[str, tuple[Path, str | None]]:
    """Return {skill_name: (skill_dir, local_version)} for all installed deepvista skills."""
    found: dict[str, tuple[Path, str | None]] = {}
    for base in SKILL_DIRS:
        if not base.exists():
            continue
        for skill_dir in sorted(base.iterdir()):
            if not skill_dir.is_dir() or not skill_dir.name.startswith("deepvista-"):
                continue
            skill_md = skill_dir / "SKILL.md"
            version = _parse_skill_version(skill_md.read_text(encoding="utf-8")) if skill_md.exists() else None
            if skill_dir.name not in found:
                found[skill_dir.name] = (skill_dir, version)
    return found


def _check_skill_updates() -> list[tuple[str, str | None, str | None]]:
    """Return list of (name, local_version, remote_version) for outdated skills."""
    installed = _find_installed_skills()
    if not installed:
        return []
    updates = []
    for name, (_, local_version) in sorted(installed.items()):
        remote_version = _fetch_remote_skill_version(name)
        if local_version and remote_version and local_version != remote_version:
            updates.append((name, local_version, remote_version))
    return updates


# ---------------------------------------------------------------------------
# CLI command
# ---------------------------------------------------------------------------


@click.command("upgrade")
@click.option("--check", is_flag=True, help="Only check for updates, do not install.")
def upgrade_command(check: bool) -> None:
    """Check for updates to the CLI and installed skills, then upgrade.

    \b
    Examples:
      deepvista upgrade           # check and upgrade everything
      deepvista upgrade --check   # check only, exit 1 if any update available
    """
    has_updates = False

    # --- CLI package ---
    click.echo("Checking CLI...")
    pypi_url = "https://pypi.org/pypi/deepvista-cli/json"
    try:
        with _safe_urlopen(pypi_url, timeout=10) as resp:
            latest_cli = json.loads(resp.read().decode("utf-8"))["info"]["version"]
    except Exception as exc:
        raise click.ClickException(f"Could not reach PyPI: {exc}")

    current = __version__
    if current == latest_cli:
        click.echo(f"  CLI: {current} (up to date)")
    else:
        click.echo(f"  CLI: {current} → {latest_cli}")
        has_updates = True

    # --- Skills ---
    click.echo("Checking skills...")
    skill_updates = _check_skill_updates()
    if not skill_updates:
        click.echo("  Skills: all up to date")
    else:
        for name, local, remote in skill_updates:
            click.echo(f"  {name}: {local} → {remote}")
        has_updates = True

    if not has_updates:
        return

    if check:
        sys.exit(1)

    # --- Upgrade CLI ---
    if current != latest_cli:
        exe = sys.executable
        if shutil.which("pipx") and ".local/pipx" in exe:
            cmd = ["pipx", "upgrade", "deepvista-cli"]
        else:
            cmd = [exe, "-m", "pip", "install", "--upgrade", "deepvista-cli"]
        click.echo(f"\nUpgrading CLI: {' '.join(cmd)}")
        result = subprocess.run(cmd)
        if result.returncode != 0:
            sys.exit(result.returncode)

    # --- Upgrade skills ---
    if skill_updates:
        install_sh = f"https://raw.githubusercontent.com/{REPO}/main/install.sh"
        click.echo("\nUpgrading skills...")
        result = subprocess.run(["bash", "-c", f"curl -sSL {install_sh} | bash"])
        if result.returncode != 0:
            sys.exit(result.returncode)
