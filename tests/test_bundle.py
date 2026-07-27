"""Bundle manifest parsing and local materialization (DV-1816)."""

from __future__ import annotations

import hashlib
import json

import pytest

from deepvista_cli import bundle

SHA_A = "a" * 64
SHA_B = "b" * 64


def _doc(files_yaml: str, *, trailing: str = "") -> str:
    return f"---\nname: demo\ndescription: demo\nfiles:\n{files_yaml}{trailing}---\n\n# Demo\n"


def _blob(content: bytes) -> tuple[str, bytes]:
    return hashlib.sha256(content).hexdigest(), content


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def test_no_frontmatter_yields_no_bundle():
    assert bundle.parse_bundle_files("# plain\n") == []


def test_frontmatter_without_files_yields_no_bundle():
    assert bundle.parse_bundle_files("---\nname: x\n---\n\nbody\n") == []


def test_parses_entries_with_defaults():
    files = bundle.parse_bundle_files(
        _doc(
            f"  - path: scripts/render.py\n"
            f"    sha256: {SHA_A}\n"
            f"    size: 4210\n"
            f'    mode: "755"\n'
            f"  - path: references/layout.md\n"
            f"    sha256: {SHA_B}\n"
        )
    )
    assert [f.path for f in files] == ["scripts/render.py", "references/layout.md"]
    assert files[0].mode == "755"
    assert files[0].size == 4210
    assert files[1].mode == bundle.DEFAULT_MODE


def test_a_following_top_level_key_ends_the_block():
    files = bundle.parse_bundle_files(_doc(f"  - path: a.py\n    sha256: {SHA_A}\n", trailing="license: Apache-2.0\n"))
    assert [f.path for f in files] == ["a.py"]


def test_unquoted_and_quoted_values_both_work():
    files = bundle.parse_bundle_files(_doc(f'  - path: "a b.py"\n    sha256: {SHA_A}\n    mode: 755\n'))
    assert files[0].path == "a b.py"
    assert files[0].mode == "755"


@pytest.mark.parametrize(
    "path",
    ["../escape.py", "/etc/passwd", "a//b.py", "./rel.py", "C:/evil.py", "back\\slash.py", "SKILL.md", "scripts/"],
)
def test_unsafe_paths_rejected(path):
    assert bundle.validate_bundle_path(path) is not None
    with pytest.raises(bundle.BundleError):
        bundle.parse_bundle_files(_doc(f'  - path: "{path}"\n    sha256: {SHA_A}\n'))


def test_duplicate_paths_rejected():
    with pytest.raises(bundle.BundleError, match="duplicate"):
        bundle.parse_bundle_files(_doc(f"  - path: a.py\n    sha256: {SHA_A}\n  - path: a.py\n    sha256: {SHA_B}\n"))


def test_bad_sha_rejected():
    with pytest.raises(bundle.BundleError, match="sha256"):
        bundle.parse_bundle_files(_doc('  - path: a.py\n    sha256: "nope"\n'))


def test_bad_mode_rejected():
    with pytest.raises(bundle.BundleError, match="mode"):
        bundle.parse_bundle_files(_doc(f'  - path: a.py\n    sha256: {SHA_A}\n    mode: "4755"\n'))


def test_file_count_cap():
    entries = "".join(f"  - path: f{i}.txt\n    sha256: {SHA_A}\n" for i in range(bundle.MAX_BUNDLE_FILES + 1))
    with pytest.raises(bundle.BundleError, match="exceeds"):
        bundle.parse_bundle_files(_doc(entries))


def test_bundle_sha_matches_backend_canonicalization():
    """Pins the wire format shared with vista_common.bundle_manifest.

    The server stores this in `attributes.bundle_sha`; if the two ever disagree
    every machine re-downloads every bundle on every invocation.
    """
    files = [
        bundle.BundleFile(path="b.py", sha256=SHA_B, mode="644"),
        bundle.BundleFile(path="a.py", sha256=SHA_A, mode="755"),
    ]
    canonical = json.dumps([["a.py", SHA_A, "755"], ["b.py", SHA_B, "644"]], separators=(",", ":"), ensure_ascii=True)
    assert bundle.compute_bundle_sha(files) == hashlib.sha256(canonical.encode()).hexdigest()


def test_bundle_sha_ignores_size():
    with_size = [bundle.BundleFile(path="a.py", sha256=SHA_A, size=10)]
    without = [bundle.BundleFile(path="a.py", sha256=SHA_A)]
    assert bundle.compute_bundle_sha(with_size) == bundle.compute_bundle_sha(without)


# ---------------------------------------------------------------------------
# Path confinement
# ---------------------------------------------------------------------------


def test_safe_destination_allows_nested(tmp_path):
    assert bundle.safe_destination(tmp_path, "a/b/c.py") == (tmp_path / "a/b/c.py").resolve()


def test_safe_destination_blocks_symlinked_parent(tmp_path):
    """The check `validate_bundle_path` structurally cannot make.

    A symlinked directory planted by an earlier bundle looks like an ordinary
    relative path in the manifest — only resolving it catches the escape.
    """
    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "root"
    root.mkdir()
    (root / "link").symlink_to(outside, target_is_directory=True)

    with pytest.raises(bundle.BundleError, match="outside the bundle root"):
        bundle.safe_destination(root, "link/pwned.py")


# ---------------------------------------------------------------------------
# Materialization
# ---------------------------------------------------------------------------


def _materialize(tmp_path, blobs: dict[str, bytes], files, **kwargs):
    def fetch(entry):
        return blobs[entry.sha256]

    return bundle.materialize_bundle(files, tmp_path, fetch, **kwargs)


def test_writes_files_and_marker(tmp_path):
    sha, content = _blob(b"print('hi')\n")
    files = [bundle.BundleFile(path="scripts/run.py", sha256=sha, mode="755")]

    result = _materialize(tmp_path, {sha: content}, files)

    written = tmp_path / "scripts/run.py"
    assert written.read_bytes() == content
    assert result["written"] == ["scripts/run.py"]
    assert written.stat().st_mode & 0o777 == 0o755
    assert bundle.read_marker(tmp_path)["bundle_sha"] == bundle.compute_bundle_sha(files)


def test_non_executable_mode_is_644(tmp_path):
    sha, content = _blob(b"# notes\n")
    _materialize(tmp_path, {sha: content}, [bundle.BundleFile(path="a.md", sha256=sha)])
    assert (tmp_path / "a.md").stat().st_mode & 0o777 == 0o644


def test_second_run_is_a_no_op(tmp_path):
    sha, content = _blob(b"x\n")
    files = [bundle.BundleFile(path="a.py", sha256=sha)]
    _materialize(tmp_path, {sha: content}, files)

    result = _materialize(tmp_path, {sha: content}, files)
    assert result["written"] == []
    assert result["skipped"] == ["a.py"]


def test_server_side_change_overwrites(tmp_path):
    old_sha, old = _blob(b"v1\n")
    new_sha, new = _blob(b"v2\n")
    _materialize(tmp_path, {old_sha: old}, [bundle.BundleFile(path="a.py", sha256=old_sha)])

    result = _materialize(tmp_path, {new_sha: new}, [bundle.BundleFile(path="a.py", sha256=new_sha)])
    assert result["written"] == ["a.py"]
    assert (tmp_path / "a.py").read_bytes() == new


def test_local_edit_is_preserved_not_clobbered(tmp_path):
    old_sha, old = _blob(b"v1\n")
    new_sha, new = _blob(b"v2\n")
    files_v1 = [bundle.BundleFile(path="a.py", sha256=old_sha)]
    _materialize(tmp_path, {old_sha: old}, files_v1)

    (tmp_path / "a.py").write_bytes(b"my debugging\n")

    result = _materialize(tmp_path, {new_sha: new}, [bundle.BundleFile(path="a.py", sha256=new_sha)])
    assert result["preserved"] == ["a.py"]
    assert (tmp_path / "a.py").read_bytes() == b"my debugging\n"


def test_force_overwrites_a_local_edit(tmp_path):
    old_sha, old = _blob(b"v1\n")
    new_sha, new = _blob(b"v2\n")
    _materialize(tmp_path, {old_sha: old}, [bundle.BundleFile(path="a.py", sha256=old_sha)])
    (tmp_path / "a.py").write_bytes(b"mine\n")

    result = _materialize(tmp_path, {new_sha: new}, [bundle.BundleFile(path="a.py", sha256=new_sha)], force=True)
    assert result["written"] == ["a.py"]
    assert (tmp_path / "a.py").read_bytes() == new


def test_hash_mismatch_on_download_aborts(tmp_path):
    files = [bundle.BundleFile(path="a.py", sha256=SHA_A)]

    def fetch(entry):
        return b"not what was promised"

    with pytest.raises(bundle.BundleError, match="hash"):
        bundle.materialize_bundle(files, tmp_path, fetch)
    assert not (tmp_path / "a.py").exists()


def test_dropped_entry_is_removed(tmp_path):
    sha_a, a = _blob(b"a\n")
    sha_b, b = _blob(b"b\n")
    blobs = {sha_a: a, sha_b: b}
    _materialize(
        tmp_path,
        blobs,
        [bundle.BundleFile(path="a.py", sha256=sha_a), bundle.BundleFile(path="b.py", sha256=sha_b)],
    )

    result = _materialize(tmp_path, blobs, [bundle.BundleFile(path="a.py", sha256=sha_a)])
    assert result["removed"] == ["b.py"]
    assert not (tmp_path / "b.py").exists()


def test_edited_leftover_is_not_deleted(tmp_path):
    """Pruning only removes what we installed *and* still own."""
    sha_a, a = _blob(b"a\n")
    sha_b, b = _blob(b"b\n")
    _materialize(
        tmp_path,
        {sha_a: a, sha_b: b},
        [bundle.BundleFile(path="a.py", sha256=sha_a), bundle.BundleFile(path="b.py", sha256=sha_b)],
    )
    (tmp_path / "b.py").write_bytes(b"i edited this\n")

    result = _materialize(tmp_path, {sha_a: a}, [bundle.BundleFile(path="a.py", sha256=sha_a)])
    assert result["removed"] == []
    assert (tmp_path / "b.py").read_bytes() == b"i edited this\n"


def test_fetcher_resolves_dv_uri_then_downloads(monkeypatch):
    """The two-hop fetch: resolve via API, download from the signed URL."""
    calls = {}

    class FakeClient:
        def get(self, path, params=None):
            calls["resolve"] = (path, params)
            return {"url": "https://signed.example/blob"}

    class FakeResponse:
        status_code = 200
        content = b"payload"

    monkeypatch.setattr("httpx.get", lambda url, **kw: calls.setdefault("download", url) and None or FakeResponse())

    fetch = bundle.make_fetcher(FakeClient(), "card-1")
    assert fetch(bundle.BundleFile(path="scripts/x.py", sha256=SHA_A)) == b"payload"
    assert calls["resolve"] == ("/attachments/resolve", {"uri": "dv://card/card-1/scripts/x.py"})
    assert calls["download"] == "https://signed.example/blob"
