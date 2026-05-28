# Contributing to deepvista-cli

This repo ships both a Python CLI (`deepvista_cli/`, published to PyPI as `deepvista-cli`) and a Claude Code plugin (`plugins/claude-code/`, distributed via the marketplace at `.claude-plugin/marketplace.json`). Both are versioned together.

For code-level conventions (Ruff, pre-commit, skill files, Python style) see [`CLAUDE.md`](./CLAUDE.md) — this guide focuses on the PR workflow.

## Pull-request workflow

1. Branch from `main`. Make your change.
2. Run the project's lint / format steps (see `CLAUDE.md` → "After editing Python files"). The pre-commit hooks (`gitleaks`, `ruff-check`, `ruff-format`, `pyright`) gate the commit; the same checks run in CI.
3. Open a PR with a **Conventional Commits**–formatted title (see below).
4. We use **squash merge only**. The PR **title** becomes the single commit subject on `main`; the PR **body** becomes the commit body. Branches are auto-deleted on merge.

## Conventional Commits

The PR title prefix decides whether (and how) `release-please` cuts the next release:

| Prefix | Effect on the next release |
|--------|----------------------------|
| `fix:` / `fix(scope):` | patch (`0.y.Z`) |
| `feat:` / `feat(scope):` | minor (`0.Y.0` while pre-1.0; `x.Y.0` post-1.0) |
| `feat!:` / `<type>!:` or any `BREAKING CHANGE:` footer in the PR body | major (`X.0.0`) |
| `chore:`, `docs:`, `refactor:`, `test:`, `ci:`, `style:`, `perf:`, `build:` | no release |

Scopes are conventional too — `feat(notes):`, `fix(skills):`, `feat(DV-832):` etc. Use whatever subsystem name or ticket id is meaningful.

The release-please config lives at [`release-please-config.json`](./release-please-config.json). It bumps `pyproject.toml` and `plugins/claude-code/.claude-plugin/plugin.json` in lockstep, then `sync-uv-lock` refreshes `uv.lock` on the release-please PR so CI's `uv sync --frozen` stays green.

### ⚠️ Don't write conventional-commit markers in PR prose

`release-please` scans the **entire** squashed commit body, not just the subject line. If you write something like:

> Future contributors should use the bang-suffixed type for breaking work…

inside a PR body using the **literal** marker at line-start, `release-please` will treat it as a breaking-change marker and bump the major version unexpectedly. (Documented in the sibling repo's PR #6 — same trap.)

**Rules of thumb when writing PR/commit prose:**

- Don't start a line with `<type>!:` (e.g. `feat!:`, `fix!:`) followed by descriptive text.
- Don't put the literal string `BREAKING CHANGE:` at the start of a line.
- If you need to refer to those markers, wrap them in backticks and don't put them at line-start, or paraphrase ("the bang-suffixed type", "a breaking-change footer").

## Releasing

You don't release by hand. See `CLAUDE.md` → "Releasing a new version" for the full flow. Short version:

1. Merge a `fix:` / `feat:` PR onto `main`.
2. `release-please` opens or updates `chore(main): release X.Y.Z` (versions + CHANGELOG).
3. The `sync-uv-lock` job refreshes `uv.lock` on that branch.
4. Merging the release PR cuts the `vX.Y.Z` tag + GitHub Release; CI then publishes to PyPI.

To force a specific version on the next release, add a `Release-As: 1.2.3` footer to a PR body.

## Plugin vs CLI

A change can affect only the Python CLI, only the Claude Code plugin, or both. The version bumps together either way — there's a single source of truth in `release-please-config.json` mirrored into both `pyproject.toml` and the plugin's `plugin.json`. Scope the PR title to make the surface area obvious (`feat(plugin):`, `feat(cli):`, `feat(skills):`, etc.).

## Skill development

Skills are published as GitHub Releases by `gh skill publish` and discovered by [skills.sh](https://skills.sh). The version comes from the git tag — **don't add a `version` field to `SKILL.md`**. Validate with `gh skill publish --dry-run` before committing; same check runs in CI. See `CLAUDE.md` → "After editing skill files" for the consolidated `skills/deepvista/` structure.
