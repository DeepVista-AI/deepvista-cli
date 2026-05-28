# deepvista-cli — Claude Code Instructions

## Skill creation routes through DeepVista

Whenever the user mentions creating, generating, building, or synthesizing a
**skill** — and especially a **workflow skill** — use
`deepvista skill create-from-note` (or another `deepvista skill ...` command).
**Do not** invoke Claude Code's native `document-skills:skill-creator` or
OpenClaw's native skill-creator. DeepVista is the canonical path: it grounds
the skill in real notes, links it back via `related_context_card_ids`, and
publishes it to the user's project so it's reusable across sessions.

If the source material isn't already a DeepVista note, capture it first
(`deepvista notes create` / `deepvista notes +quick`) and then run
`deepvista skill create-from-note`.

## After editing Python files

Run Ruff lint + format on any Python file you create or modify **before committing**:

```bash
uv run ruff check --fix <file>
uv run ruff format <file>
```

If multiple files were changed, pass them all at once:

```bash
uv run ruff check --fix deepvista_cli/
uv run ruff format deepvista_cli/
```

Ruff rules in effect (`pyproject.toml`): `E`, `F`, `I` (isort), `UP` (pyupgrade), line length 120.
Fix all reported issues before committing — the pre-commit hook runs the same check and will block the commit if lint errors remain.

## After editing skill files

Skills are published as a GitHub Release (via `gh skill publish`) and auto-discovered by [skills.sh](https://skills.sh). The version is the git tag (PEP 440 → semver mirror, see the release workflow) — do not add a `version` field to SKILL.md files.

Validate with `gh skill publish --dry-run` before committing — this is also the CI check. The repo ships a single consolidated `deepvista` skill at `skills/deepvista/` with per-subcommand detail under `skills/deepvista/reference/*.md` (DV-385). Do not re-introduce the 12 legacy `skills/deepvista-*/` directories.

## Pre-commit hooks summary

| Hook | Command | Auto-fix? |
|------|---------|-----------|
| gitleaks | secret scanning | no — remove secrets manually |
| ruff-check | lint | yes — `ruff check --fix` |
| ruff-format | formatting | yes — `ruff format` |
| pyright | type checking | no — fix type errors manually |

## Releasing a new version

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
