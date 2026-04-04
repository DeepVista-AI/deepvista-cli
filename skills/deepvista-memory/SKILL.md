---
name: deepvista-memory
version: "0.1.0"
description: "DeepVista Memory: View and search implicit memory context automatically accumulated from Chat."
metadata:
  deepvista:
    category: "service"
    requires:
      bins:
        - deepvista
      skills:
        - deepvista-shared
    cliHelp: "deepvista memory --help"
---

# Memory (Implicit Context)

> **PREREQUISITE:** Read [deepvista-shared](../deepvista-shared/SKILL.md) for auth, profiles, and global flags.

Memory is the implicit context layer — automatically accumulated from Chat conversations. It is **never directly editable**. The AI surfaces relevant memory in Chat when appropriate ("I remember you mentioned…"). Users can view and search it, but all updates happen through Chat.

**Command:** `deepvista memory <subcommand>`

## Commands

### show

```bash
deepvista memory show [--limit N]
```

Show a summary of your accumulated memory context.

| Flag | Required | Default | Description |
|------|----------|---------|-------------|
| `--limit` | No | 20 | Max entries to show |

Read-only. Memory is automatically built from Chat — this command never modifies it.

### search

```bash
deepvista memory search "query text" [--limit N]
```

Search through your memory context using semantic search.

| Flag | Required | Default | Description |
|------|----------|---------|-------------|
| `<query>` | Yes | — | Search query |
| `--limit` | No | 10 | Max results |

Read-only.

## Design Principles

- **Always implicit:** Memory is only written by Chat — there is no manual write entry point.
- **Occasionally surfaces:** The AI proactively hints at relevant memories during Chat.
- **Correctable:** Tell the AI in Chat to correct a memory — it will update accordingly.
- **Not directly editable:** Users can view (CLI) but cannot directly modify memory entries.

## Examples

```bash
# View memory summary
deepvista memory show

# Show more entries
deepvista memory show --limit 50

# Search for specific memories
deepvista memory search "project decisions"
deepvista memory search "team meeting Q1"
```

## See Also

- [deepvista-shared](../deepvista-shared/SKILL.md) — Auth and global flags
- [deepvista-chat](../deepvista-chat/SKILL.md) — Chat (where memory is accumulated)
