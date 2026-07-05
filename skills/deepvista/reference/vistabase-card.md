# Cards — the knowledge base

`deepvista card` manages every knowledge base entry. Types: `person`, `organization`,
`message`, `todo`, `topic`, `keypoint`, `file`, `note`, `skill`, `skill_run`.

`deepvista vistabase` is a backward-compatible alias — every `card` subcommand
works under `vistabase` too (hidden from `--help`).

Run `deepvista card --help` or `deepvista card <cmd> --help` for full flag reference.

`deepvista notes` is a thin convenience wrapper over `card --type note`.
Use [notes.md](notes.md) for note-only ergonomics.

## Commands

`list` · `get` · `create` · `update` · `edit` · `delete`
`index` · `history` · `diff` · `restore`
`+search` · `+similar` · `+grep` · `+pin` · `+archive`

## Agent conventions

> [!CAUTION] `create`, `update`, `edit`, `delete`, `index`, `restore`, `+pin`, `+archive` are writes.
> Confirm first. Use `--dry-run` to preview.

- **Always use `--content-file <absolute-path>`** for large content — never inline.
- Show the app URL after any write: `https://app.deepvista.ai/vistabase/<id>`
- Read-only commands (`list`, `get`, `history`, `diff`, `+search`, `+similar`, `+grep`) are safe to run
  without confirmation.

## Non-obvious gotchas

**`edit` requires an exact string match.** `--old-string` must appear exactly once in
the current body — it is replaced with `--new-string`. Fails if not found. Use
`card get` to read the current body before calling `edit`. Prefer `update
--content-file` when replacing large sections.

**`+search` vs `+grep`:** `+search` is hybrid vector+keyword (fuzzy, semantic).
`+grep` is literal/regex. Use `+search` for concepts, `+grep` for exact strings like
`TODO`, URLs, or identifiers.

**`index`** — queues entity extraction + embedding refresh on unprocessed cards
(`--type note` by default). Run after bulk imports or a long offline period.

**`history` / `diff` / `restore`** — version history for any card. `restore`
captures the current state as a new version first, so it's reversible.

## Examples

```bash
# Search
deepvista card +search "quarterly metrics"
deepvista card +search "ML team" --type person
deepvista card +grep "TODO|FIXME" --type note -i

# Create
deepvista card create --type topic \
  --title "ML Strategy" --content-file /tmp/ml-strategy.md

# Targeted patch
deepvista card edit <id> --old-string "old API URL" --new-string "new API URL"

# Pin
deepvista card +pin <id>
```

## See also

- [notes.md](notes.md) — `--type note` convenience wrapper
- [skill-import-files.md](skill-import-files.md) — bulk-import files as `type=file` cards
