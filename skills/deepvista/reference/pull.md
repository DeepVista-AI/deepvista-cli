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

By default, the skill's **stub directory** — the same
`~/.claude/skills/dv-<slug>/` that `deepvista skill sync` writes `SKILL.md` into:

```
~/.claude/skills/dv-pdf-report/
├── SKILL.md              ← the skill body (written by sync)
├── scripts/render.py     ← bundle
├── references/layout.md
└── .deepvista-bundle.json   ← install marker, do not edit
```

Landing in the stub dir is deliberate: `scripts/render.py` then resolves
relative to the `SKILL.md` the agent is reading, with no absolute paths.

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

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Installed (or nothing to do) |
| 3 | Bad target — not a card id or a `dv://card/...` reference |
| 4 | Invalid manifest, download failure, or a path that escapes the bundle root |
