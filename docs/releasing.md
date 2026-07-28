# Releasing a new version

Releases are automated by [release-please](https://github.com/googleapis/release-please).
You don't bump versions, edit `uv.lock`, write tags, or open release PRs by hand.

**Day-to-day flow:**

1. Land feature PRs on `main` using Conventional Commit titles
   (`feat(DV-xxx): …`, `fix(notes): …`, `feat!: …` for breaking). Squash-merge as usual.
2. release-please watches `main` and keeps a single open PR titled
   `chore(main): release X.Y.Z`. It bumps `pyproject.toml`, `uv.lock`, and
   `plugins/claude-code/.claude-plugin/plugin.json`, and updates `CHANGELOG.md`.
   Each new commit on `main` rewrites the same PR (highest bump wins:
   `feat` upgrades a pending `fix` PR from patch to minor).
3. **To ship: merge the release PR.** release-please then creates the
   `vX.Y.Z` tag and the GitHub Release. The tag push triggers
   `.github/workflows/publish.yml`, which builds and uploads to PyPI.

**Version bumps follow commit types:**

| Commit type | Bump | Example |
|---|---|---|
| `fix:` | patch | 0.1.16 → 0.1.17 |
| `feat:` | minor | 0.1.16 → 0.2.0 |
| `feat!:` or `BREAKING CHANGE:` footer | major | 0.1.16 → 1.0.0 |
| `chore:` / `docs:` / `refactor:` / `test:` / `ci:` | none | — |

Override the proposed version with a `Release-As: 1.0.0` footer on any commit.

**Pre-releases (alpha / beta / rc) still use the manual flow** — release-please
is configured for stable PEP 440 versions only. To cut `0.1.0a27` etc., bump
`pyproject.toml` + `plugins/claude-code/.claude-plugin/plugin.json` on a release
branch, push, tag `v0.1.0a27`, and the publish workflow's pre-release path
(`gh skill publish --tag`) handles the PEP 440 → semver conversion.

**Version scheme:** `0.1.0aN` (alpha) → `0.1.0bN` (beta) → `0.1.0rcN` (rc) → `0.1.0` (stable)
