---
name: deepvista-vistabase
version: "0.1.0"
description: "DeepVista Card: Manage your knowledge cards — create, search, and organize context cards."
metadata:
  deepvista:
    category: "service"
    requires:
      bins:
        - uv
      skills:
        - deepvista-shared
    cliHelp: "deepvista card --help"
---

# Card (Knowledge Base)

> **PREREQUISITE:** Read [deepvista-shared](../deepvista-shared/SKILL.md) for auth, profiles, and global flags.

Cards are DeepVista's knowledge base — context cards representing people, organizations, topics, notes, files, and more. Cards have vector embeddings for semantic search and keyword indexing for precise lookups.

**Command:** `deepvista card <subcommand>`

## App URLs

After any write operation (create, update), always show the card URL to the user:

```
https://app.deepvista.ai/vistabase?contextId=<id>
```

Extract the `id` from the JSON response and present it as a clickable link.

## CRUD Commands

### list

```bash
deepvista card list [--type TYPE] [--status STATUS] [--limit N] [--page N] [--order-by FIELD] [--order DIR]
```

| Flag | Required | Default | Description |
|------|----------|---------|-------------|
| `--type` | No | all | Card type filter |
| `--status` | No | all | `pinned`, `archived`, or `normal` |
| `--limit` | No | 20 | Max results |
| `--page` | No | 1 | Page number |
| `--order-by` | No | — | `created_at` or `updated_at` |
| `--order` | No | — | `asc` or `desc` |

### get

```bash
deepvista card get <card_id>
```

### create

```bash
deepvista card create --type TYPE --title "Title" [--content "Description"] [--tags '["t1","t2"]'] [--no-enrich]
```

> [!CAUTION] Write command — confirm with user before executing.

### update

```bash
deepvista card update <card_id> [--title "..."] [--content "..."] [--type TYPE] [--tags '["t1"]'] [--status pinned|archived]
```

> [!CAUTION] Write command — confirm with user before executing.

### delete

```bash
deepvista card delete <card_id> [--type TYPE]
```

> [!CAUTION] Destructive command — confirm with user before executing.

## Helper Commands

### +search

```bash
deepvista card +search "query text" [--type TYPE] [--limit N]
```

Search across all context cards using hybrid vector + keyword search.

| Flag | Required | Default | Description |
|------|----------|---------|-------------|
| `<query>` | Yes | — | Search query (natural language) |
| `--type` | No | all | Filter by card type |
| `--limit` | No | 10 | Max results |

Read-only. Use `card get <id>` to read the full content of a result.

### +similar

```bash
deepvista card +similar <card_id> [--limit N]
```

Find context cards semantically similar to a given card.

Read-only. The source card is excluded from results.

### +pin

```bash
deepvista card +pin <card_id>
```

> [!CAUTION] Write command.

### +archive

```bash
deepvista card +archive <card_id>
```

> [!CAUTION] Write command.

## Card Types

`person`, `organization`, `message`, `todo`, `topic`, `keypoint`, `file`, `note`, `recipe`, `recipe_run`

## Examples

```bash
# Search for anything about quarterly metrics
deepvista card +search "quarterly metrics"

# Find people related to a topic
deepvista card +search "machine learning team" --type person

# List all notes
deepvista card list --type note

# Create a topic card
deepvista card create --type topic --title "Machine Learning Strategy" --content "Our approach to ML..."

# Pin an important card
deepvista card +pin abc123

# Get full details of a card
deepvista card get abc123
```

## See Also

- [deepvista-shared](../deepvista-shared/SKILL.md) — Auth and global flags
- [deepvista-notes](../deepvista-notes/SKILL.md) — Notes (shorthand for cards with type=note)
