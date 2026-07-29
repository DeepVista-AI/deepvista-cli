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


# ---------------------------------------------------------------------------
# Frontmatter reads shared with the catalog (DV-1869)
# ---------------------------------------------------------------------------


def test_frontmatter_scalars_skip_block_lists():
    body = _doc("  - path: a.py\n    sha256: " + SHA_A + "\n")
    scalars = bundle.parse_frontmatter_scalars(body)

    assert scalars == {"name": "demo", "description": "demo"}
    # The manifest's own keys must not leak in as top-level scalars.
    assert "path" not in scalars
    assert "sha256" not in scalars


def test_frontmatter_scalars_on_a_bodyless_document():
    assert bundle.parse_frontmatter_scalars("# no frontmatter\n") == {}
    assert bundle.parse_frontmatter_scalars(None) == {}


def test_strip_manifest_removes_only_the_files_block():
    body = f'---\nname: demo\nfiles:\n  - path: a.py\n    sha256: {SHA_A}\n    mode: "755"\ntype: tool\n---\n\n# Demo\n'

    stripped = bundle.strip_manifest(body)

    assert "files:" not in stripped
    assert SHA_A not in stripped
    # Keys on both sides of the block survive, and so does the body.
    assert "name: demo" in stripped
    assert "type: tool" in stripped
    assert stripped.endswith("# Demo\n")
    # Still a well-formed single frontmatter block.
    assert stripped.splitlines().count("---") == 2


def test_strip_manifest_is_a_no_op_without_one():
    body = "---\nname: demo\n---\n\n# Demo\n"
    assert bundle.strip_manifest(body) == body
    assert bundle.strip_manifest("# plain\n") == "# plain\n"


# ---------------------------------------------------------------------------
# Upload — collect / render / splice / put (DV-1869)
# ---------------------------------------------------------------------------


def _skill_dir(tmp_path, *, body_name: str = "SKILL.md"):
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / body_name).write_text("---\nname: demo\ndescription: A demo skill.\n---\n\n# Demo\n")
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "run.py").write_text("print('hi')\n")
    (tmp_path / "scripts" / "run.py").chmod(0o755)
    (tmp_path / "notes.md").write_text("# notes\n")
    return tmp_path


def test_find_skill_body_is_case_insensitive(tmp_path):
    _skill_dir(tmp_path, body_name="skill.md")
    found = bundle.find_skill_body(tmp_path)
    assert found is not None
    # The *actual* spelling on disk, not the one we probed for — that's the bug
    # this guards: keeping "SKILL.md" makes the caller's exclusion miss.
    assert found.name == "skill.md"


def test_find_skill_body_missing(tmp_path):
    (tmp_path / "notes.md").write_text("x")
    assert bundle.find_skill_body(tmp_path) is None


def test_collect_excludes_the_body_and_build_artefacts(tmp_path):
    _skill_dir(tmp_path)
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "run.cpython-314.pyc").write_bytes(b"\x00")
    (tmp_path / ".DS_Store").write_bytes(b"\x00")
    (tmp_path / bundle.MARKER_FILENAME).write_text("{}")

    files = bundle.collect_bundle_files(tmp_path, exclude=bundle.find_skill_body(tmp_path))

    assert [f.path for f in files] == ["notes.md", "scripts/run.py"]


def test_collect_records_the_executable_bit_and_hashes(tmp_path):
    _skill_dir(tmp_path)

    files = {f.path: f for f in bundle.collect_bundle_files(tmp_path, exclude=bundle.find_skill_body(tmp_path))}

    assert files["scripts/run.py"].mode == "755"
    assert files["notes.md"].mode == "644"
    assert files["scripts/run.py"].sha256 == hashlib.sha256(b"print('hi')\n").hexdigest()
    assert files["scripts/run.py"].size == len(b"print('hi')\n")


def test_collect_rejects_a_lowercase_body_left_in_the_tree(tmp_path):
    """Without `exclude`, a `skill.md` must still be refused as an entry."""
    _skill_dir(tmp_path, body_name="skill.md")
    with pytest.raises(bundle.BundleError, match="skill body"):
        bundle.collect_bundle_files(tmp_path)


def test_splice_manifest_round_trips(tmp_path):
    _skill_dir(tmp_path)
    body = (tmp_path / "SKILL.md").read_text()
    files = bundle.collect_bundle_files(tmp_path, exclude=tmp_path / "SKILL.md")

    spliced = bundle.splice_manifest(body, files)

    assert bundle.parse_bundle_files(spliced) == files
    assert bundle.parse_frontmatter_scalars(spliced)["description"] == "A demo skill."


def test_splice_manifest_replaces_rather_than_appends(tmp_path):
    """A re-push must not stack a second `files:` block on the first."""
    _skill_dir(tmp_path)
    body = (tmp_path / "SKILL.md").read_text()
    files = bundle.collect_bundle_files(tmp_path, exclude=tmp_path / "SKILL.md")

    once = bundle.splice_manifest(body, files)
    twice = bundle.splice_manifest(once, files)

    assert once == twice
    assert twice.count("files:") == 1


def test_splice_manifest_needs_frontmatter():
    with pytest.raises(bundle.BundleError, match="frontmatter"):
        bundle.splice_manifest("# no frontmatter\n", [bundle.BundleFile(path="a.py", sha256=SHA_A)])


class _FakeUploadClient:
    """Records posts; reports `already` shas as stored."""

    def __init__(self, already: set[str] | None = None):
        self.posts: list[tuple[str, dict]] = []
        self.already = already or set()

    def post(self, path, body=None):
        self.posts.append((path, body or {}))
        if path == "/attachments/signed-upload-url":
            if (body or {}).get("sha256") in self.already:
                return {"alreadyExists": True}
            return {"signedUrl": "https://signed.example/put", "headers": {"x-goog-if-generation-match": "0"}}
        if path == "/attachments/blobs/verify":
            return {"verified": True}
        return {}


def test_upload_puts_then_verifies_each_blob(tmp_path, monkeypatch):
    _skill_dir(tmp_path)
    files = bundle.collect_bundle_files(tmp_path, exclude=tmp_path / "SKILL.md")
    client = _FakeUploadClient()
    puts: list[tuple[str, bytes, dict]] = []

    class FakeResponse:
        status_code = 200

    def fake_put(url, content=None, headers=None, **kw):
        puts.append((url, content, headers or {}))
        return FakeResponse()

    monkeypatch.setattr("httpx.put", fake_put)

    result = bundle.upload_bundle(client, tmp_path, files)

    assert result["uploaded"] == ["notes.md", "scripts/run.py"]
    assert result["deduped"] == []
    # Signed headers go up verbatim — they are part of the signature.
    assert puts[0][2] == {"x-goog-if-generation-match": "0"}
    assert puts[0][1] == b"# notes\n"
    # Every upload is followed by a verify, so an unverified blob never lands.
    assert [p for p, _ in client.posts].count("/attachments/blobs/verify") == 2


def test_upload_skips_shas_the_server_already_holds(tmp_path, monkeypatch):
    _skill_dir(tmp_path)
    files = bundle.collect_bundle_files(tmp_path, exclude=tmp_path / "SKILL.md")
    client = _FakeUploadClient(already={f.sha256 for f in files})
    monkeypatch.setattr("httpx.put", lambda *a, **kw: pytest.fail("should not PUT a deduped blob"))

    result = bundle.upload_bundle(client, tmp_path, files)

    assert result["deduped"] == ["notes.md", "scripts/run.py"]
    assert result["uploaded"] == []
    assert "/attachments/blobs/verify" not in [p for p, _ in client.posts]


def test_upload_fails_loudly_when_the_server_will_not_verify(tmp_path, monkeypatch):
    _skill_dir(tmp_path)
    files = bundle.collect_bundle_files(tmp_path, exclude=tmp_path / "SKILL.md")

    class RefusingClient(_FakeUploadClient):
        def post(self, path, body=None):
            if path == "/attachments/blobs/verify":
                return {"verified": False}
            return super().post(path, body)

    class FakeResponse:
        status_code = 200

    monkeypatch.setattr("httpx.put", lambda *a, **kw: FakeResponse())

    with pytest.raises(bundle.BundleError, match="did not verify"):
        bundle.upload_bundle(RefusingClient(), tmp_path, files)


def test_push_then_pull_is_byte_identical(tmp_path, monkeypatch):
    """The round trip the whole feature exists for: upload a tree, install it back.

    Ties the two halves together through one manifest — contents *and* the
    executable bit, which is what makes a pulled script runnable.
    """
    source = _skill_dir(tmp_path / "src")
    files = bundle.collect_bundle_files(source, exclude=source / "SKILL.md")

    blobs: dict[str, bytes] = {}

    class FakeResponse:
        status_code = 200

    def fake_put(url, content=None, headers=None, **kw):
        blobs[hashlib.sha256(content).hexdigest()] = content
        return FakeResponse()

    monkeypatch.setattr("httpx.put", fake_put)
    bundle.upload_bundle(_FakeUploadClient(), source, files)

    installed = tmp_path / "dest"
    manifest = bundle.parse_bundle_files(bundle.splice_manifest((source / "SKILL.md").read_text(), files))
    bundle.materialize_bundle(manifest, installed, lambda entry: blobs[entry.sha256])

    for entry in files:
        assert (installed / entry.path).read_bytes() == (source / entry.path).read_bytes()
    assert (installed / "scripts/run.py").stat().st_mode & 0o777 == 0o755
