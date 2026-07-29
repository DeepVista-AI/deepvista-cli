# Pull — install a card's bundled files onto this machine

`deepvista pull` materializes a card's **bundle** — the set of files it carries —
into a local directory. A skill's `scripts/`, `references/`, and assets are the
main case, but nothing about the command is skill-specific: any card with a
`files:` manifest can be pulled.

Use when the user says: "install this skill", "download the skill files", "pull
the bundle", "get the scripts for this skill onto my machine".

Works anywhere the CLI runs — a cloud machine or a laptop. The Machine registry
is only the dispatch path for remotely-triggered installs, not a gate on pulling.

## Usage

```bash
deepvista pull <skill-id>                        # → ~/.claude/skills/dv-<slug>/
deepvista pull <skill-id> --to ./workdir         # → ./workdir/
deepvista pull dv://card/<id>/scripts/render.py --to ./workdir   # one file
deepvista pull <skill-id> --dry-run              # list without writing
```

> [!CAUTION] This writes files your agent may later execute. Confirm the source
> with the user before pulling a bundle they didn't author. Preview with
> `--dry-run` first.

## Where files land

By default the **bundle store** — a stable, version-independent directory keyed by
card id:

```
~/.local/share/deepvista/bundles/<card-id>/
├── scripts/render.py
├── references/layout.md
└── .deepvista-bundle.json   ← install marker, do not edit
```

Deliberately *not* the skill's stub directory. Stubs belong to whichever agent
directory syncs them, and under the Claude Code plugin that is
`${CLAUDE_PLUGIN_ROOT}/skills` — a **version-pinned** path the marketplace
updater deletes on upgrade. A bundle kept there was collateral damage: the
directory vanishes wholesale, so there is nothing left to migrate from, and every
upgrade silently forced a re-download.

Keyed by card id rather than a title slug, so renaming a skill doesn't orphan its
installed files.

Override with `--to`, or point the whole store somewhere else with
`DEEPVISTA_BUNDLE_DIR`.

`deepvista skill load` prints the root and tells the agent to resolve the body's
relative file paths against it — which it needed anyway, since an agent's working
directory is the project, never the skill directory.

A bundle installed under the older stub-dir layout is **moved** into the store the
next time the skill is loaded or pulled, not re-downloaded.

## You usually don't need to run this

`deepvista skill load <id>` — which the stub `SKILL.md` already invokes at
skill-invocation time — installs the bundle automatically before printing the
body. Reach for `pull` explicitly only to target a different directory, to
recover from a failed auto-install, or to inspect a bundle with `--dry-run`.

## Local edits are preserved

Bundle files are server-owned, so a content change overwrites. The exception:
if a file's contents match **neither** the previously installed version nor the
new one, you edited it locally, and `pull` keeps your copy and reports it:

```
  1 file(s) kept — they differ from both the old and new manifest,
  which means you edited them locally. Re-run with --force to overwrite:
    ! scripts/render.py
```

Pass `--force` to take the server's version anyway.

Files dropped from the manifest are deleted, but only when they still match what
we installed — an edited leftover is left alone.

## Sync won't delete what you installed

Bundles live outside the stub dirs `sync` manages, so retiring or relocating a
stub cannot touch them. Two older safeguards still apply to installs made under
the previous layout: `sync` removes only the stub plus the files its own marker
says it installed, skipping any whose hash changed (you edited them) and leaving
the directory standing if anything survives; and a target move carries such a
bundle across rather than deleting it.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Installed (or nothing to do) |
| 3 | Bad target — not a card id or a `dv://card/...` reference |
| 4 | Invalid manifest, download failure, or a path that escapes the bundle root |
