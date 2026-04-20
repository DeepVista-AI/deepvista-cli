# deepvista-cli — Claude Code Instructions

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

Skills are published to [ClawHub](https://clawhub.ai). The version is read from `pyproject.toml` at publish time — do not add a `version` field to SKILL.md files.

## Pre-commit hooks summary

| Hook | Command | Auto-fix? |
|------|---------|-----------|
| gitleaks | secret scanning | no — remove secrets manually |
| ruff-check | lint | yes — `ruff check --fix` |
| ruff-format | formatting | yes — `ruff format` |
| pyright | type checking | no — fix type errors manually |

## Releasing a new version

The `main` branch is protected. Follow this workflow:

1. **Create release branch and bump version**
   ```bash
   git checkout main && git pull
   git checkout -b release/vX.Y.Z
   # Edit pyproject.toml: version = "X.Y.Z"
   uv lock                              # regenerate uv.lock so it matches
   git add pyproject.toml uv.lock
   git commit -m "release: vX.Y.Z"
   git push -u origin release/vX.Y.Z
   ```

   Both `pyproject.toml` **and** `uv.lock` must be staged — `uv.lock` pins the
   project's own version, and CI's `uv sync --frozen` tolerates self-version
   drift but contributors will hit a lockfile mismatch if it's skipped.

2. **Create PR and merge**
   ```bash
   gh pr create --title "release: vX.Y.Z" --body "Bump version for release"
   ```

3. **After PR merged, tag and push**
   ```bash
   git checkout main && git pull
   git tag vX.Y.Z
   git push origin vX.Y.Z
   ```

CI publishes to PyPI **and** creates a GitHub Release automatically on `v*`
tags. Pre-releases (`vX.Y.ZaN` / `bN` / `rcN`) are converted to semver
(`vX.Y.Z-alpha.N`, etc.) and released under that tag by `gh skill publish`,
so `gh skill install DeepVista-AI/deepvista-cli@vX.Y.Z-alpha.N` works. Stable
releases reuse the PyPI tag directly.

**Version scheme:** `0.1.0aN` (alpha) → `0.1.0bN` (beta) → `0.1.0rcN` (rc) → `0.1.0` (stable)
