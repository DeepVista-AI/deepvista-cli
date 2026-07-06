"""deepvista upgrade — check for and install CLI and skill updates.

Two parts:

1. A fast, cached `upgrade check` subcommand — called from skill on-load
   preambles by AI agents. Prints a single marker line on stdout and exits 1
   if an update is available so the agent can react.

2. An `upgrade install` flow that fetches the changelog between the current
   and latest version, shows it to the user, and performs the install via
   the appropriate package manager.

State lives in ``~/.config/deepvista/`` (via ``deepvista_cli.config.CONFIG_DIR``,
honors ``DEEPVISTA_CONFIG_DIR``):

- ``update-check-cache.json`` — last-check timestamp + fetched latest version.
  Asymmetric TTL: 60 min if up-to-date (so new releases surface quickly),
  720 min if an update is already pending (so users don't get nagged).
- ``just-upgraded`` — marker written by `install` so the next `check` can
  report `JUST_UPGRADED`.

Set ``DEEPVISTA_UPDATE_CHECK=0`` to disable checks entirely.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import urllib.request
from datetime import UTC, datetime, timedelta
from http.client import HTTPResponse
from pathlib import Path
from urllib.parse import urlparse

import click

from deepvista_cli import __version__
from deepvista_cli.config import CONFIG_DIR

REPO = "DeepVista-AI/deepvista-cli"
RAW_BASE = f"https://raw.githubusercontent.com/{REPO}/main"
PYPI_URL = "https://pypi.org/pypi/deepvista-cli/json"

STATE_DIR = CONFIG_DIR
CACHE_FILE = STATE_DIR / "update-check-cache.json"
JUST_UPGRADED_FILE = STATE_DIR / "just-upgraded"

FRESH_TTL_MIN = 60
STALE_TTL_MIN = 720


def _safe_urlopen(url: str, timeout: int = 10) -> HTTPResponse:
    """Open a URL, but only allow https:// scheme to prevent file:// attacks."""
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise ValueError(f"Only https:// URLs are allowed, got: {parsed.scheme}://")
    return urllib.request.urlopen(url, timeout=timeout)  # nosec B310 - scheme validated above


def _now() -> datetime:
    return datetime.now(UTC)


def _ensure_state_dir() -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)


def _read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write_json(path: Path, data: dict) -> None:
    _ensure_state_dir()
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _update_check_enabled() -> bool:
    return os.environ.get("DEEPVISTA_UPDATE_CHECK", "").lower() not in {"0", "false", "no", "off"}


def _parse_iso(s: str) -> datetime | None:
    try:
        return datetime.fromisoformat(s)
    except (TypeError, ValueError):
        return None


def _fetch_latest_pypi_version(timeout: int = 5) -> str | None:
    try:
        with _safe_urlopen(PYPI_URL, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))["info"]["version"]
    except Exception:
        return None


def _cache_is_fresh(cache: dict, has_update: bool) -> bool:
    ts = _parse_iso(cache.get("checked_at", ""))
    if ts is None:
        return False
    ttl = timedelta(minutes=STALE_TTL_MIN if has_update else FRESH_TTL_MIN)
    return _now() - ts < ttl


def _load_cache() -> dict | None:
    return _read_json(CACHE_FILE)


def _save_cache(current: str, latest: str) -> None:
    _write_json(
        CACHE_FILE,
        {"checked_at": _now().isoformat(), "current": current, "latest": latest},
    )


def _fetch_changelog_between(old: str, new: str) -> str | None:
    """Fetch CHANGELOG.md and return entries newer than ``old`` up to ``new``.

    Assumes CHANGELOG.md uses ``## vX.Y.Z`` (or ``## X.Y.Z``) section headers in
    reverse chronological order — the standard Keep a Changelog layout. Returns
    None on network errors, empty string when no matching sections exist.
    """
    try:
        with _safe_urlopen(f"{RAW_BASE}/CHANGELOG.md", timeout=5) as resp:
            text = resp.read().decode("utf-8", errors="replace")
    except Exception:
        return None

    out: list[str] = []
    capturing = False
    for line in text.splitlines():
        if line.startswith("## "):
            version = line[3:].strip().split()[0].lstrip("v")
            if version == old:
                break
            capturing = True
        if capturing:
            out.append(line)
    return "\n".join(out).strip()


# ---------------------------------------------------------------------------
# upgrade command group
# ---------------------------------------------------------------------------


@click.group("upgrade", invoke_without_command=True)
@click.option("--check", "check_flag", is_flag=True, help="Only check for updates, do not install.")
@click.pass_context
def upgrade_command(ctx: click.Context, check_flag: bool) -> None:
    """Check for and install CLI + skill updates.

    \b
    Examples:
      deepvista upgrade                 # interactive upgrade with changelog
      deepvista upgrade check           # fast cached check (for skill preambles)
      deepvista upgrade install --yes   # upgrade without prompting

    Set DEEPVISTA_UPDATE_CHECK=0 to disable update checks.
    """
    if ctx.invoked_subcommand is not None:
        return
    if check_flag:
        ctx.invoke(check_subcommand)
        return
    ctx.invoke(install_subcommand)


@upgrade_command.command("check")
@click.option("--quiet", "quiet", is_flag=True, help="Suppress all output; communicate via exit code only.")
@click.option("--no-cache", is_flag=True, help="Ignore cached result and re-check against PyPI.")
def check_subcommand(quiet: bool, no_cache: bool) -> None:
    """Fast cached check for a newer CLI version.

    \b
    Exit codes:
      0 — up to date, disabled, or network failure (silent)
      1 — update available

    \b
    Output markers on stdout:
      UPGRADE_AVAILABLE <old> <new>
      JUST_UPGRADED     <old> <new>   (once, cleared on read)
    """
    if JUST_UPGRADED_FILE.exists():
        try:
            data = json.loads(JUST_UPGRADED_FILE.read_text(encoding="utf-8"))
            old = data.get("from", "?")
            new = data.get("to", __version__)
            JUST_UPGRADED_FILE.unlink()
            if not quiet:
                click.echo(f"JUST_UPGRADED {old} {new}")
        except (OSError, ValueError):
            try:
                JUST_UPGRADED_FILE.unlink()
            except OSError:
                pass

    if not _update_check_enabled():
        sys.exit(0)

    cache = _load_cache() if not no_cache else None
    latest: str | None = None
    if cache and cache.get("current") == __version__:
        has_update = cache.get("latest") != __version__
        if _cache_is_fresh(cache, has_update):
            latest = cache.get("latest")

    if latest is None:
        latest = _fetch_latest_pypi_version()
        if latest is None:
            sys.exit(0)
        _save_cache(__version__, latest)

    if latest == __version__:
        sys.exit(0)

    if not quiet:
        click.echo(f"UPGRADE_AVAILABLE {__version__} {latest}")
    sys.exit(1)


@upgrade_command.command("install")
@click.option("--yes", "-y", is_flag=True, help="Do not prompt — install immediately.")
@click.option("--skip-skills", is_flag=True, help="Only upgrade the CLI; leave skills alone.")
@click.option("--dry-run", is_flag=True, help="Preview what would be installed without making any changes.")
def install_subcommand(yes: bool, skip_skills: bool, dry_run: bool) -> None:
    """Interactive upgrade of the CLI and installed skills.

    Fetches the changelog between your current version and the latest,
    shows the highlights, and asks for confirmation before installing.
    """
    click.echo("Checking for updates...")
    latest = _fetch_latest_pypi_version(timeout=10)
    if latest is None:
        raise click.ClickException("Could not reach PyPI — check your network connection.")

    if latest == __version__:
        click.echo(f"deepvista-cli {__version__} is up to date.")
        _save_cache(__version__, latest)
        return

    click.echo(f"\nUpdate available: {__version__} → {latest}\n")

    changelog = _fetch_changelog_between(__version__, latest)
    if changelog:
        click.echo("What's new:\n")
        click.echo(changelog)
        click.echo("")
    elif changelog is not None:
        click.echo(f"Release notes: https://github.com/{REPO}/releases\n")

    if dry_run:
        cmd = _pick_install_command()
        click.echo(
            json.dumps(
                {
                    "dry_run": True,
                    "would": "upgrade CLI",
                    "from": __version__,
                    "to": latest,
                    "install_command": " ".join(cmd),
                    "would_refresh_skills": not skip_skills,
                },
                indent=2,
            )
        )
        return

    if not yes and not click.confirm("Install now?", default=True):
        click.echo("Skipped. Re-run `deepvista upgrade` when you're ready.")
        return

    _run_install(latest, skip_skills=skip_skills)


# ---------------------------------------------------------------------------
# Install helpers
# ---------------------------------------------------------------------------


def _run_install(latest: str, *, skip_skills: bool) -> None:
    old = __version__
    click.echo(f"Upgrading CLI to {latest}...")
    cmd = _pick_install_command()
    click.echo(f"  $ {' '.join(cmd)}")
    result = subprocess.run(cmd)
    if result.returncode != 0:
        raise click.ClickException(f"Install failed (exit {result.returncode}).")

    if not skip_skills:
        click.echo("\nRefreshing skills...")
        install_sh = f"{RAW_BASE}/install.sh"
        skill_result = subprocess.run(["bash", "-c", f"curl -sSL {install_sh} | bash"])
        if skill_result.returncode != 0:
            click.echo(
                f"Skill refresh exited with code {skill_result.returncode}. "
                "You can rerun it later with `deepvista upgrade install`.",
                err=True,
            )

    _ensure_state_dir()
    _write_json(JUST_UPGRADED_FILE, {"from": old, "to": latest})
    # Clear cache so the next check sees the new current version.
    try:
        CACHE_FILE.unlink()
    except FileNotFoundError:
        pass
    click.echo(f"\nUpgrade complete: {old} → {latest}")


def _pick_install_command() -> list[str]:
    """Choose the best upgrade command for the current install layout."""
    exe = sys.executable
    if shutil.which("uv") and ".local/share/uv" in exe:
        return ["uv", "tool", "upgrade", "deepvista-cli"]
    if shutil.which("pipx") and ".local/pipx" in exe:
        return ["pipx", "upgrade", "deepvista-cli"]
    if shutil.which("uv"):
        return ["uv", "tool", "upgrade", "deepvista-cli"]
    return [exe, "-m", "pip", "install", "--upgrade", "deepvista-cli"]
