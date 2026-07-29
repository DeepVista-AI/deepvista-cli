# Push — upload a skill directory to Vistabase

`deepvista push` uploads a local skill **directory** — its `SKILL.md` plus every
supporting file — as one card with a bundle. The inverse of
[`pull`](pull.md), and the way a multi-file skill gets into Vistabase at all so
it can be stored, versioned, shared, and installed on another machine.

Use when the user says: "upload this skill", "push this skill to Vistabase",
"store this skill with its scripts", "share this skill with my team".

## Usage

```bash
deepvista push ./skills/pdf-report                  # create a new skill card
deepvista push ./skills/pdf-report --card <id>      # update an existing card
deepvista push ./skills/pdf-report --dry-run        # list what would upload
deepvista push ./skills/pdf-report --title "PDF Report"
```

> [!CAUTION] Write command — it uploads file contents to your project and
> creates or updates a card. Run `--dry-run` first and show the user the file
> list before pushing.

## What goes where

```
skills/pdf-report/
├── SKILL.md               → the card description (never a bundle entry)
├── scripts/render.py      → bundle entry, mode 755 (it's executable)
├── references/layout.md   → bundle entry, mode 644
└── __pycache__/           → skipped
```

`SKILL.md` is matched **case-insensitively**, so `skill.md` works too. Skipped
automatically: `__pycache__`, `.git`, `.venv`, `venv`, `node_modules`,
`.ruff_cache`, `.pytest_cache`, `.mypy_cache`, `.DS_Store`, and the
`.deepvista-bundle.json` install marker. Symlinks are not followed.

A `files:` manifest is written into the SKILL.md frontmatter (last, so the keys a
human reads stay on top). Each entry carries `path`, `sha256`, `size`, `mode`,
and `content_type` — **no bucket, no project, no URL**: the sha is the only
locator, and the server derives storage from it plus the card's project.

## Re-pushing is cheap and idempotent

Uploads are content-addressed, so the server answers `alreadyExists` for any sha
it already holds and the PUT is skipped. Push the same tree twice and the second
run uploads nothing. The manifest is *replaced*, not appended to, so the
frontmatter never accumulates duplicate `files:` blocks.

## Requirements on the skill body

- It must have a `---` frontmatter block (that's where the manifest goes).
- The frontmatter `description` is what an agent reads to decide whether to load
  the skill — write it as a trigger sentence, not a summary.
- The frontmatter `name` becomes the card title unless `--title` says otherwise.
- Max 100 files per bundle. Past that, the right answer is a git import.

## After pushing

The card is created `confirmed`, so it shows up immediately in
`deepvista skill list` and syncs a stub on the next `deepvista skill sync`.
(Cards the CLI creates otherwise default to `unconfirmed` and stay filtered out
of search and the catalog — `card create --status confirmed` is the manual
equivalent.)

Show the user the link:

```
https://app.deepvista.ai/skills/<card_id>
```

## Installing it elsewhere

On any machine with the CLI authenticated to the same project:

```bash
deepvista skill sync           # writes the stub
# …invoking the skill runs `deepvista skill load <id>`, which installs the bundle
```

Or explicitly: `deepvista pull <card-id>`. See [pull.md](pull.md).

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Pushed (or nothing to upload) |
| 3 | Not a skill directory — no `SKILL.md` found |
| 4 | Invalid bundle, or an upload the server would not verify |
| 1 | API error — the card save was rejected (the message says why) |

## Gotcha: `type: workflow` in frontmatter

Vistabase validates any body whose frontmatter says `type: workflow` as a
DeepVista *workflow document* — `name: workflow-<slug>`, `execution: stateful`,
and a `## Workflow` → `## Node Description` body with a mermaid chart. A Claude
Code skill that uses `type: workflow` in the looser "sequence of steps" sense
will be rejected on save with errors about a name slug and a mermaid chart.

If you hit that on an older backend, either use `type: tool` or drop the key —
but say so, because it edits the author's frontmatter.

## See also

- [pull.md](pull.md) — install a bundle on a machine
- [skill.md](skill.md) — `sync` / `load` and the catalog stub mechanism
- [vistabase-card.md](vistabase-card.md) — `card upload` for a single binary file (no bundle)
