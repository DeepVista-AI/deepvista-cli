---
name: deepvista-vistabase
description: "DeepVista Vistabase: View and search implicit memory context automatically accumulated from Chat."
metadata:
  openclaw:
    category: service
    requires:
      bins:
        - deepvista
      skills:
        - deepvista-shared
    install:
      - kind: uv
        package: deepvista-cli
        bins: [deepvista]
    homepage: https://cli.deepvista.ai
    cliHelp: "deepvista vistabase --help"
---

# Vistabase (Implicit Context)

> **PREREQUISITE:** Read [deepvista-shared](../deepvista-shared/SKILL.md) for auth, profiles, and global flags.

Vistabase is the implicit context layer — automatically accumulated from Chat conversations. It is **never directly editable**. The AI surfaces relevant context in Chat when appropriate ("I remember you mentioned…"). Users can view and search it, but all updates happen through Chat.

**Command:** `deepvista vistabase <subcommand>`

> **Backward compatibility:** `deepvista memory` is a deprecated alias that works identically.

## Commands

### show

```bash
deepvista vistabase show [--limit N]
```

Show a summary of your accumulated memory context.

| Flag | Required | Default | Description |
|------|----------|---------|-------------|
| `--limit` | No | 20 | Max entries to show |

Read-only. Context is automatically built from Chat — this command never modifies it.

### search

```bash
deepvista vistabase search "query text" [--limit N]
```

Search through your memory context using semantic search.

| Flag | Required | Default | Description |
|------|----------|---------|-------------|
| `<query>` | Yes | — | Search query |
| `--limit` | No | 10 | Max results |

Read-only.

## Design Principles

- **Always implicit:** Vistabase context is only written by Chat — there is no manual write entry point.
- **Occasionally surfaces:** The AI proactively hints at relevant context during Chat.
- **Correctable:** Tell the AI in Chat to correct a memory — it will update accordingly.
- **Not directly editable:** Users can view (CLI) but cannot directly modify entries.

## Examples

```bash
# View context summary
deepvista vistabase show

# Show more entries
deepvista vistabase show --limit 50

# Search for specific context
deepvista vistabase search "project decisions"
deepvista vistabase search "team meeting Q1"
```

## See Also

- [deepvista-shared](../deepvista-shared/SKILL.md) — Auth and global flags
- [deepvista-chat](../deepvista-chat/SKILL.md) — Chat (where vistabase context is accumulated)
