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

The pre-commit hook validates every `skills/*/SKILL.md`. If you create or modify a skill, validate it manually first:

```bash
uv run agentskills validate skills/<skill-name>/
```

Fix any validation errors before committing.

## Pre-commit hooks summary

| Hook | Command | Auto-fix? |
|------|---------|-----------|
| gitleaks | secret scanning | no — remove secrets manually |
| ruff-check | lint | yes — `ruff check --fix` |
| ruff-format | formatting | yes — `ruff format` |
| pyright | type checking | no — fix type errors manually |
| skills-ref-validate | skill YAML/schema | no — fix schema errors manually |
