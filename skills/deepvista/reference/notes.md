# Notes — explicit user-authored knowledge

Notes are for content **the user explicitly asked to record** (long-form
text, "what I want to remember"). They are cards with `type=note`. For
agent-recorded incidental snippets use `deepvista card create --type …`
(see [vistabase-card.md](vistabase-card.md)); for session transcripts use
[`deepvista session`](session.md) (DV-742).

Run `deepvista notes --help` or `deepvista notes <cmd> --help` for full
flag reference.

## Commands

`list` · `get` · `create` · `update` · `delete` · `index` · `+quick`
`history` · `diff` · `restore`

> [!NOTE] `session-init` / `session-tick` / `session-finalize` are deprecated
> aliases that forward to `deepvista session …` (DV-742). They emit a
> deprecation hint on stderr and still work for one release.

## Agent conventions

> [!CAUTION] `create`, `update`, `delete`, `index`, `restore`, `session-*` are writes.
> Confirm with the user first (except `+quick` in auto-capture mode — see [openclaw.md](openclaw.md)).

- **Always use `--content-file <absolute-path>`** for anything more than ~200 chars or
  containing newlines. Never paste large content inline. Pass `-` to read from stdin.
- Show the app URL after any write: `https://app.deepvista.ai/notes/<id>`
- Use `--dry-run` to preview without writing.

## Non-obvious commands

**`+quick`** — single-line fast capture. First ~50 chars become the title:
```bash
deepvista notes +quick "Alice confirmed the API deadline is April 15"
```

**`index`** — queues entity extraction + embedding refresh on unprocessed notes.
Run after bulk imports or after a long offline period. Pair with
`deepvista lint --check missing-refs`.

**`session-*` (deprecated)** — see [session.md](session.md). New hook installs
should call `deepvista session init|tick|finalize` directly; the `notes
session-*` aliases delegate there and will be removed in a future release.

**`history` / `diff` / `restore`** — version history. `restore` captures the current
state as a new version first, so it's reversible.

### Hook installation (Claude Code plugin)

```
/plugin marketplace add DeepVista-AI/deepvista-cli
/plugin install deepvista@deepvista-ai
```

Manual install: copy `plugins/claude-code/hooks/` into `~/.claude/hooks/` and wire
`SessionStart`, `Stop`, and `SessionEnd` in `~/.claude/settings.json`.

## Examples

```bash
# Quick capture
deepvista notes +quick "Decided to drop legacy auth middleware — compliance req"

# Structured note from file
deepvista notes create --title "Standup 2026-04-20" \
  --content-file /tmp/standup.md --tags '["standup"]'

# Read then edit
deepvista notes get <note_id>
deepvista notes update <note_id> --title "Standup — April 20"

# From stdin
curl -sL https://example.com/page.md | \
  deepvista notes create --title "Reference page" --content-file -

# Index after bulk import
deepvista notes index --limit 100
```

## See also

- [vistabase-card.md](vistabase-card.md) — underlying `card --type note` commands
- [openclaw.md](openclaw.md) — auto-capture without confirmation
