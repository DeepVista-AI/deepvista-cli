"""Skill/file bundle manifests and local materialization (DV-1816).

A card can carry a **bundle** — a skill's ``scripts/``, ``references/``, and
assets — declared as a ``files:`` block in its SKILL.md frontmatter::

    ---
    name: pdf-report
    files:
      - path: scripts/render.py
        sha256: 3a7f9c...
        mode: "755"
    ---

Two namespaces that never touch, and keeping them straight is the whole model:

* ``path`` is a **destination** — where bytes land on disk, relative to the
  bundle root.
* ``sha256`` is the **only locator** — the server derives the storage path from
  it plus the card's project. A manifest names no bucket and no project.

Materializing a bundle writes files an agent will then execute, so this module
is a security boundary. Every path is realpath-confined to the bundle root
before a byte is written; the server validates the same rules at save, but a
client must never trust that a manifest arrived unmodified.

The frontmatter parser here is hand-rolled: the CLI deliberately carries no
PyYAML dependency (see ``skill_catalog.build_stub_markdown``), and the manifest
grammar is a deliberately small, fixed subset — a block list of flat mappings.

Both directions live here (DV-1869). Upload is the exact inverse of install —
hash the tree, skip the shas storage already holds, PUT the rest, have the
server verify them — and splitting the two halves across modules would let the
manifest they share drift.
"""

from __future__ import annotations

import hashlib
import json
import logging
import mimetypes
import os
import re
import stat
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

logger = logging.getLogger(__name__)

# Mirrors vista_common.bundle_manifest — keep the two in sync.
MAX_BUNDLE_FILES = 100
MAX_PATH_LENGTH = 256
ALLOWED_MODES = ("644", "755")
DEFAULT_MODE = "644"
# Lowercased and compared case-insensitively (DV-1869): the body of a skill dir
# on APFS/NTFS may be spelled `skill.md`, and letting it also appear in `files:`
# would put two copies of the description on disk racing each other.
RESERVED_PATHS = frozenset({"skill.md"})

# Written into the bundle root so a repeat `skill load` is a no-op and a
# later sync can tell server-owned files apart from ones the user edited.
MARKER_FILENAME = ".deepvista-bundle.json"

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
# Backslash and colon are path separators / drive markers on Windows; neither
# is needed in a bundle path, and a POSIX-only check would let `C:/evil.py`
# through as "relative".
_UNSAFE_PATH_CHARS = re.compile(r"[\x00-\x1f\x7f\\:]")

_DOWNLOAD_CHUNK = 1024 * 1024


class BundleError(Exception):
    """A manifest is malformed, or materialization would leave the bundle root."""


class _BundleClient(Protocol):
    """Just enough of DeepVistaClient to resolve refs (so tests inject a fake)."""

    def get(self, path: str, params: dict | None = None) -> Any: ...


@dataclass(frozen=True, slots=True)
class BundleFile:
    path: str
    sha256: str
    size: int | None = None
    mode: str = DEFAULT_MODE
    content_type: str | None = None


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def validate_bundle_path(path: Any) -> str | None:
    """Return a problem string for an unsafe bundle path, or ``None`` if valid.

    The parse-time half of path safety. :func:`materialize_bundle` still
    realpath-confines on write — this catches a bad manifest before any file is
    created, so a rejected bundle never half-installs.
    """
    if not isinstance(path, str) or not path:
        return "each files[] entry needs a non-empty `path`"
    if len(path) > MAX_PATH_LENGTH:
        return f"path exceeds {MAX_PATH_LENGTH} characters"
    if _UNSAFE_PATH_CHARS.search(path):
        return f"path contains a control character, backslash, or colon: {path!r}"
    if path.startswith("/"):
        return f"path must be relative, got absolute: {path}"
    if path.endswith("/"):
        return f"path must name a file, not a directory: {path}"
    if any(seg in ("", ".", "..") for seg in path.split("/")):
        return f"path must not contain empty, '.', or '..' segments: {path}"
    if path.lower() in RESERVED_PATHS:
        return f"'{path}' is the skill body itself and cannot be a bundle entry"
    return None


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def _split_frontmatter(body: str | None) -> str | None:
    """Return the raw frontmatter block, or ``None`` when there isn't one."""
    if not body or not body.startswith("---"):
        return None
    parts = body.split("---", 2)
    return parts[1] if len(parts) >= 3 else None


def parse_frontmatter_scalars(body: str | None) -> dict[str, str]:
    """Top-level ``key: value`` scalars from a SKILL.md's frontmatter.

    Deliberately flat: block lists (``files:``, ``inputs:``) are skipped rather
    than half-parsed, because every consumer wants a single value — the skill's
    own ``description``, which is the text an agent reads to decide whether to
    load it. Same no-PyYAML reasoning as :func:`parse_bundle_files`.
    """
    frontmatter = _split_frontmatter(body)
    if frontmatter is None:
        return {}

    scalars: dict[str, str] = {}
    for raw in frontmatter.splitlines():
        line = raw.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        # Indented lines and list items belong to the block above, not here.
        if line[:1].isspace() or line.lstrip().startswith("- "):
            continue
        key, sep, value = line.partition(":")
        value = _unquote(value)
        if sep and value:
            scalars[key.strip()] = value
    return scalars


def strip_manifest(body: str) -> str:
    """Remove the ``files:`` block from a body's frontmatter (DV-1869).

    The manifest is machine state the installer has already consumed by the time
    a body is shown to an agent. Leaving it in spends context on sha256 digests
    and invites the model to read storage bookkeeping as skill content — a
    7-file bundle is ~1.5 KB of noise on every invocation. The card keeps the
    manifest; only the rendered view drops it.
    """
    lines = body.splitlines()
    if not lines or lines[0].strip() != "---":
        return body
    close = next((i for i, line in enumerate(lines[1:], start=1) if line.strip() == "---"), None)
    if close is None:
        return body

    start = next((i for i in range(1, close) if lines[i].startswith("files:")), None)
    if start is None:
        return body

    end = start + 1
    while end < close and (not lines[end].strip() or lines[end][:1].isspace()):
        end += 1

    kept = lines[:start] + lines[end:]
    return "\n".join(kept) + ("\n" if body.endswith("\n") else "")


def parse_bundle_files(body: str | None) -> list[BundleFile]:
    """Extract the ``files:`` manifest from a SKILL.md body.

    Returns ``[]`` when the skill has no bundle — the common case. Raises
    :class:`BundleError` when a bundle is declared but malformed, because
    installing half of a broken manifest is worse than installing none of it.
    """
    frontmatter = _split_frontmatter(body)
    if frontmatter is None:
        return []

    entries: list[dict[str, str]] = []
    in_files = False
    current: dict[str, str] | None = None

    for raw in frontmatter.splitlines():
        line = raw.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        stripped = line.strip()

        if indent == 0:
            # A new top-level key ends the files block.
            if in_files:
                break
            key, sep, value = stripped.partition(":")
            if sep and key.strip() == "files" and not value.strip():
                in_files = True
            continue

        if not in_files:
            continue

        if stripped.startswith("- "):
            current = {}
            entries.append(current)
            stripped = stripped[2:].strip()
        elif stripped == "-":
            current = {}
            entries.append(current)
            continue

        if current is None:
            raise BundleError("`files:` entries must start with `- path: ...`")
        key, sep, value = stripped.partition(":")
        if not sep:
            raise BundleError(f"unparseable manifest line: {raw.strip()!r}")
        current[key.strip()] = _unquote(value)

    if not entries:
        return []
    if len(entries) > MAX_BUNDLE_FILES:
        raise BundleError(f"bundle exceeds {MAX_BUNDLE_FILES} files ({len(entries)})")

    files: list[BundleFile] = []
    seen: set[str] = set()
    for index, entry in enumerate(entries):
        where = f"files[{index}]"
        path = entry.get("path")
        problem = validate_bundle_path(path)
        if problem:
            raise BundleError(f"{where}: {problem}")
        assert isinstance(path, str)
        if path in seen:
            raise BundleError(f"{where}: duplicate path '{path}'")
        seen.add(path)

        sha = (entry.get("sha256") or "").lower()
        if not _SHA256_RE.match(sha):
            raise BundleError(f"{where}: `sha256` must be a lowercase hex digest")

        mode = entry.get("mode") or DEFAULT_MODE
        if mode not in ALLOWED_MODES:
            raise BundleError(f"{where}: mode must be one of {', '.join(ALLOWED_MODES)}, got {mode!r}")

        size_raw = entry.get("size")
        size: int | None = None
        if size_raw is not None:
            try:
                size = int(size_raw)
            except ValueError as exc:
                raise BundleError(f"{where}: `size` must be an integer") from exc

        files.append(
            BundleFile(
                path=path,
                sha256=sha,
                size=size,
                mode=mode,
                content_type=entry.get("content_type"),
            )
        )
    return files


def compute_bundle_sha(files: list[BundleFile]) -> str:
    """Hash the manifest so sync is one scalar comparison.

    Must stay byte-identical to ``vista_common.bundle_manifest.compute_bundle_sha``
    — the server stores this value in ``attributes.bundle_sha`` and the CLI
    compares against it. Covers path/sha/mode; ``size`` is descriptive, so
    correcting it doesn't look like a content change to every machine.
    """
    canonical = sorted([f.path, f.sha256, f.mode] for f in files)
    payload = json.dumps(canonical, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Materialization
# ---------------------------------------------------------------------------


def safe_destination(root: Path, path: str) -> Path:
    """Resolve ``root/path``, refusing anything that escapes ``root``.

    The single check that kills ``..``, absolute paths, and symlink escapes at
    once — including a symlinked *parent directory* planted by an earlier
    bundle, which the string-level rules in :func:`validate_bundle_path` can't
    see. Both layers are load-bearing.
    """
    root_resolved = root.resolve()
    candidate = (root_resolved / path).resolve()
    if candidate != root_resolved and root_resolved not in candidate.parents:
        raise BundleError(f"refusing to write outside the bundle root: {path}")
    return candidate


def sha256_file(path: Path) -> str | None:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            while chunk := handle.read(_DOWNLOAD_CHUNK):
                digest.update(chunk)
    except OSError:
        return None
    return digest.hexdigest()


def read_marker(root: Path) -> dict[str, Any]:
    try:
        return json.loads((root / MARKER_FILENAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def write_marker(root: Path, files: list[BundleFile]) -> None:
    payload = {
        "bundle_sha": compute_bundle_sha(files),
        "files": {f.path: f.sha256 for f in files},
    }
    try:
        (root / MARKER_FILENAME).write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except OSError:
        logger.debug("could not write bundle marker in %s", root)


def materialize_bundle(
    files: list[BundleFile],
    root: Path,
    fetch: Callable[[BundleFile], bytes],
    *,
    force: bool = False,
) -> dict[str, list[str]]:
    """Write a bundle into ``root``. Returns per-outcome path lists.

    Outcomes: ``written``, ``skipped`` (content already correct), ``preserved``
    (locally edited — see below), ``removed`` (dropped from the manifest).

    Bundle files are server-owned, so a content change overwrites. The
    exception is a file whose on-disk hash matches *neither* the previous
    manifest nor the new one: that's a local edit, and clobbering someone's
    debugging is worse than being one version stale. ``force`` overrides.
    """
    root.mkdir(parents=True, exist_ok=True)
    previous = read_marker(root)
    previous_files: dict[str, str] = previous.get("files") or {}

    result: dict[str, list[str]] = {"written": [], "skipped": [], "preserved": [], "removed": []}

    for entry in files:
        destination = safe_destination(root, entry.path)
        on_disk = sha256_file(destination) if destination.exists() else None

        if on_disk == entry.sha256:
            result["skipped"].append(entry.path)
            continue

        if not force and on_disk is not None and on_disk != previous_files.get(entry.path):
            logger.warning("local edit preserved: %s", entry.path)
            result["preserved"].append(entry.path)
            continue

        payload = fetch(entry)
        actual = hashlib.sha256(payload).hexdigest()
        if actual != entry.sha256:
            raise BundleError(
                f"{entry.path}: downloaded bytes hash to {actual[:12]}…, manifest claims {entry.sha256[:12]}…"
            )

        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(payload)
        destination.chmod(_mode_bits(entry.mode))
        result["written"].append(entry.path)

    result["removed"] = _prune_removed(root, files, previous_files)
    write_marker(root, files)
    return result


def make_fetcher(client: _BundleClient, card_id: str) -> Callable[[BundleFile], bytes]:
    """Build the download callable :func:`materialize_bundle` needs.

    Two hops by design: the API resolves ``dv://`` to a short-lived signed URL
    (deriving the storage path from the card's project, which is the access
    check), then the bytes come straight from storage without our auth header
    riding along to a third party.
    """
    import httpx

    def fetch(entry: BundleFile) -> bytes:
        uri = f"dv://card/{card_id}/{entry.path}"
        resolved = client.get("/attachments/resolve", {"uri": uri})
        url = (resolved or {}).get("url")
        if not url:
            raise BundleError(f"{entry.path}: server returned no download URL")
        response = httpx.get(url, timeout=60.0, follow_redirects=True)
        if response.status_code >= 400:
            raise BundleError(f"{entry.path}: download failed with HTTP {response.status_code}")
        return response.content

    return fetch


def _mode_bits(mode: str) -> int:
    if mode == "755":
        return stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH
    return stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH


# ---------------------------------------------------------------------------
# Upload — the inverse of materialize (DV-1869)
# ---------------------------------------------------------------------------

# Build artefacts and VCS metadata are never part of a skill. Excluded by name
# rather than by pattern so the rule is legible in a `--dry-run` listing.
EXCLUDED_DIRS = frozenset(
    {"__pycache__", ".git", ".venv", "venv", "node_modules", ".ruff_cache", ".pytest_cache", ".mypy_cache"}
)
EXCLUDED_FILES = frozenset({".DS_Store", MARKER_FILENAME})

_UPLOAD_TIMEOUT = 300.0


class _UploadClient(Protocol):
    def post(self, path: str, body: dict | None = None) -> Any: ...


def find_skill_body(root: Path) -> Path | None:
    """The file in ``root`` that becomes the card description.

    Resolved by *listing* the directory, not by probing
    ``(root / "SKILL.md").exists()``. On a case-insensitive filesystem that
    probe hits a lowercase ``skill.md`` while handing back the uppercase
    spelling, so a later ``path == "SKILL.md"`` exclusion misses and the body is
    uploaded as a bundle entry as well — two copies of the description with no
    rule for which wins (DV-1869).
    """
    try:
        entries = sorted(root.iterdir())
    except OSError:
        return None
    return next((p for p in entries if p.is_file() and p.name.lower() == "skill.md"), None)


def collect_bundle_files(root: Path, *, exclude: Path | None = None) -> list[BundleFile]:
    """Hash a directory tree into manifest entries.

    ``mode`` comes from the file's own executable bit, which is the whole reason
    it is in the manifest: a pulled ``narrate_recording.py`` has to stay runnable
    on the machine that installs it.
    """
    files: list[BundleFile] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        relative = path.relative_to(root)
        if any(part in EXCLUDED_DIRS for part in relative.parts[:-1]):
            continue
        if path.name in EXCLUDED_FILES or (exclude is not None and path == exclude):
            continue

        posix = relative.as_posix()
        problem = validate_bundle_path(posix)
        if problem:
            raise BundleError(f"{posix}: {problem}")

        digest = sha256_file(path)
        if digest is None:
            raise BundleError(f"{posix}: could not be read")

        files.append(
            BundleFile(
                path=posix,
                sha256=digest,
                size=path.stat().st_size,
                mode="755" if os.access(path, os.X_OK) else DEFAULT_MODE,
                content_type=mimetypes.guess_type(path.name)[0],
            )
        )

    if len(files) > MAX_BUNDLE_FILES:
        raise BundleError(f"bundle exceeds {MAX_BUNDLE_FILES} files ({len(files)}) — import from git instead")
    return files


def render_manifest(files: list[BundleFile]) -> str:
    """Render manifest entries as the ``files:`` frontmatter block."""
    lines = ["files:"]
    for entry in files:
        lines.append(f"  - path: {entry.path}")
        lines.append(f"    sha256: {entry.sha256}")
        if entry.size is not None:
            lines.append(f"    size: {entry.size}")
        lines.append(f'    mode: "{entry.mode}"')
        if entry.content_type:
            lines.append(f"    content_type: {entry.content_type}")
    return "\n".join(lines)


def splice_manifest(body: str, files: list[BundleFile]) -> str:
    """Return ``body`` with its ``files:`` block replaced by ``files``.

    Goes last in the frontmatter block, per the DV-1816 format note, so the keys
    a human reads stay at the top. Re-push is idempotent because the old block is
    stripped first rather than appended to.
    """
    stripped = strip_manifest(body)
    if not files:
        return stripped

    lines = stripped.splitlines()
    if not lines or lines[0].strip() != "---":
        raise BundleError("skill body needs a `---` frontmatter block to carry a manifest")
    close = next((i for i, line in enumerate(lines[1:], start=1) if line.strip() == "---"), None)
    if close is None:
        raise BundleError("skill body's frontmatter block is never closed")

    spliced = lines[:close] + render_manifest(files).splitlines() + lines[close:]
    return "\n".join(spliced) + "\n"


def upload_bundle(client: _UploadClient, root: Path, files: list[BundleFile]) -> dict[str, list[str]]:
    """Upload every blob a manifest references. Returns per-outcome path lists.

    Outcomes: ``uploaded`` and ``deduped`` — the server answers ``alreadyExists``
    when that sha is already stored, and identical bytes are already there by
    definition, so the PUT is skipped. That is what makes a re-push of an
    unchanged tree nearly free, and what stores a helper script shared by ten
    skills exactly once.

    Every upload is followed by a server-side verify. The write-once
    precondition stops an existing blob being *overwritten*, but nothing stops a
    first upload claiming a hash it didn't compute, and an unverified blob would
    poison every manifest referencing that sha.
    """
    import httpx

    result: dict[str, list[str]] = {"uploaded": [], "deduped": []}
    for entry in files:
        signed = (
            client.post(
                "/attachments/signed-upload-url",
                {
                    "file_name": Path(entry.path).name,
                    "file_size": entry.size or 0,
                    "content_type": entry.content_type or "application/octet-stream",
                    "scope": "bundle",
                    "sha256": entry.sha256,
                },
            )
            or {}
        )
        if signed.get("alreadyExists"):
            result["deduped"].append(entry.path)
            continue

        url = signed.get("signedUrl")
        if not url:
            raise BundleError(f"{entry.path}: server returned no upload URL")

        # The signed headers are part of the signature — GCS rejects the PUT if
        # they aren't sent verbatim.
        response = httpx.put(
            url,
            content=safe_destination(root, entry.path).read_bytes(),
            headers=signed.get("headers") or {},
            timeout=_UPLOAD_TIMEOUT,
        )
        if response.status_code >= 400:
            raise BundleError(f"{entry.path}: upload failed with HTTP {response.status_code}")

        verified = client.post("/attachments/blobs/verify", {"sha256": entry.sha256}) or {}
        if not verified.get("verified"):
            raise BundleError(f"{entry.path}: server did not verify the uploaded bytes")
        result["uploaded"].append(entry.path)

    return result


def _prune_removed(root: Path, files: list[BundleFile], previous_files: dict[str, str]) -> list[str]:
    """Delete files we installed that the manifest no longer lists.

    Only ever touches paths recorded in our own marker, and only when the
    on-disk content still matches what we put there — an edited leftover is
    left alone rather than silently deleted.
    """
    current = {f.path for f in files}
    removed: list[str] = []
    for path, recorded_sha in previous_files.items():
        if path in current:
            continue
        try:
            destination = safe_destination(root, path)
        except BundleError:
            continue
        if not destination.exists() or sha256_file(destination) != recorded_sha:
            continue
        try:
            destination.unlink()
            removed.append(path)
        except OSError:
            continue
    return removed
