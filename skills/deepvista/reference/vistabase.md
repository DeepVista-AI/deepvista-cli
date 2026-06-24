# Vistabase — implicit memory

The vistabase is the knowledge base seen through the **implicit memory** lens:
things the AI agent has inferred about the user across chat sessions, not entries the
user typed by hand.

- **Read-only from the CLI.** Entries only change via `chat +send` (i.e. through
  conversation). There is no `vistabase create` / `update` / `delete`.
- Editing the knowledge base directly? Use [vistabase-card.md](vistabase-card.md).

## Commands

### `show` — read-only

```bash
deepvista vistabase show [--limit N]
```

Shows a summary of accumulated memory, newest first. Default limit is 20.

### `search` — read-only

```bash
deepvista vistabase search "query text" [--limit N]
```

Semantic search through the implicit memory store.

## Examples

```bash
deepvista vistabase show
deepvista vistabase show --limit 50
deepvista vistabase search "project decisions"
deepvista vistabase search "team meeting Q1"
```

## How entries appear

The agent writes to vistabase automatically during `deepvista chat +send`. It may also
proactively surface a relevant entry mid-conversation ("I remember you mentioned…").
Users can correct or clarify by asking the agent — never by editing the CLI side.

## See also

- [chat.md](chat.md) — the only write path into vistabase
- [vistabase-card.md](vistabase-card.md) — direct card management (explicit knowledge)
