# deepvista-cli — Claude Code Instructions

## ALWAYS work in a git worktree

The main `deepvista-cli/` checkout tracks the shared mainline branch. **Never create a
feature branch, edit files, or commit task work directly in it.** Before starting any task
that changes code, create a sibling worktree and do all work there:

```bash
# from inside deepvista-cli/ (the main checkout)
git worktree add ../deepvista-cli-<branch-id> -b <type>/<branch-id>-<title>
cd ../deepvista-cli-<branch-id>
```

If you are in `deepvista-cli/` about to branch or commit, STOP and create a worktree
instead. The only operations allowed directly in the main checkout are quick `git pull` /
inspection — never feature work.

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

## After editing skill files

Skills are published as a GitHub Release (via `gh skill publish`) and auto-discovered by [skills.sh](https://skills.sh). The version is the git tag (PEP 440 → semver mirror, see the release workflow) — do not add a `version` field to SKILL.md files.

Validate with `gh skill publish --dry-run` before committing — this is also the CI check. The repo ships a single consolidated `deepvista` skill at `skills/deepvista/` with per-subcommand detail under `skills/deepvista/reference/*.md` (DV-385). Do not re-introduce the 12 legacy `skills/deepvista-*/` directories.

## Releasing a new version

See [`docs/releasing.md`](docs/releasing.md) — release-please flow, version bumps by
commit type, and the manual pre-release path.
