---
name: deepvista-vistabase
description: "DeepVista VistaBase: Manage your knowledge base — create, search, and organize context cards."
metadata:
  deepvista:
    category: "service"
    requires:
      bins:
        - uv
      skills:
        - deepvista-shared
    cliHelp: "deepvista vistabase --help"
---

# VistaBase

> **PREREQUISITE:** Read [deepvista-shared](../deepvista-shared/SKILL.md) for auth, profiles, and global flags.

VistaBase is DeepVista's knowledge base — a collection of context cards that represent people, organizations, topics, notes, files, and more. Cards have vector embeddings for semantic search and keyword indexing for precise lookups.

## CRUD Commands

### list

```bash
deepvista vistabase list [--type TYPE] [--status STATUS] [--limit N] [--page N] [--order-by FIELD] [--order DIR]
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
deepvista vistabase get <card_id>
```

### create

```bash
deepvista vistabase create --type TYPE --title "Title" [--content "Description"] [--tags '["t1","t2"]'] [--no-enrich]
```

> [!CAUTION] Write command — confirm with user before executing.

### update

```bash
deepvista vistabase update <card_id> [--title "..."] [--content "..."] [--type TYPE] [--tags '["t1"]'] [--status pinned|archived]
```

> [!CAUTION] Write command — confirm with user before executing.

### delete

```bash
deepvista vistabase delete <card_id> [--type TYPE]
```

> [!CAUTION] Destructive command — confirm with user before executing.

## Helper Commands

### +search

```bash
deepvista vistabase +search "query text" [--type TYPE] [--limit N]
```

Search across all context cards using hybrid vector + keyword search.

| Flag | Required | Default | Description |
|------|----------|---------|-------------|
| `<query>` | Yes | — | Search query (natural language) |
| `--type` | No | all | Filter by card type |
| `--limit` | No | 10 | Max results |

Read-only. Results include relevance scores from hybrid search (vector similarity + keyword matching). Use `vistabase get <id>` to read the full content of a result.

### +similar

```bash
deepvista vistabase +similar <card_id> [--limit N]
```

Find context cards semantically similar to a given card. Uses the source card's content as a search query.

| Flag | Required | Default | Description |
|------|----------|---------|-------------|
| `<card_id>` | Yes | — | Source card to find similar cards for |
| `--limit` | No | 5 | Max results |

Read-only. The source card is excluded from results. Useful for discovering related knowledge you may not have thought to search for.

### +pin

```bash
deepvista vistabase +pin <card_id>
```

> [!CAUTION] Write command.

### +archive

```bash
deepvista vistabase +archive <card_id>
```

> [!CAUTION] Write command.

## Card Types

`person`, `organization`, `message`, `todo`, `topic`, `keypoint`, `file`, `note`, `vistabook`, `vistabook_run`

## Examples

```bash
# Search for anything about quarterly metrics
deepvista vistabase +search "quarterly metrics"

# Find people related to a topic
deepvista vistabase +search "machine learning team" --type person

# Find cards similar to a specific card
deepvista vistabase +similar card_abc123 --limit 10

# List all people cards
deepvista vistabase list --type person

# Create a topic card
deepvista vistabase create --type topic --title "Machine Learning Strategy" --content "Our approach to ML..."

# Pin an important card
deepvista vistabase +pin abc123

# Get full details of a card
deepvista vistabase get abc123
```

## See Also

- [deepvista-shared](../deepvista-shared/SKILL.md) — Auth and global flags
- [deepvista-notes](../deepvista-notes/SKILL.md) — Notes (subset of vistabase)
