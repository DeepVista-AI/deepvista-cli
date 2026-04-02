---
name: dv
description: |
  DeepVista: Full skill set for managing your knowledge base, notes, VistaBook workflows, and AI chat.
  TRIGGER when: user mentions DeepVista, asks about notes, knowledge base, cards, VistaBooks, or any `deepvista` / `dv` command; user wants to capture, search, analyze, or synthesize knowledge; user asks about "dv" CLI commands.
  DO NOT TRIGGER when: user is asking about an unrelated knowledge base or note-taking tool.
metadata:
  deepvista:
    category: "umbrella"
    requires:
      bins:
        - deepvista
    cliHelp: "deepvista --help"
---

# DeepVista

Full reference for the DeepVista CLI. This skill covers all services: notes, knowledge base, VistaBook workflows, chat, and recipes.

## Install & Auth

```bash
# Install CLI
curl -sSL https://raw.githubusercontent.com/DeepVista-AI/deepvista-cli/main/install.sh | bash

# Login
deepvista auth login
deepvista auth login --code <base64_code>   # paste code from browser

# Check / logout
deepvista auth status
deepvista auth logout
```

## CLI Syntax

```
deepvista [GLOBAL FLAGS] <service> <command> [options]
```

**Global flags must come BEFORE the service name.**

| Flag | Default | Description |
|------|---------|-------------|
| `--profile NAME` | `default` | Named config profile |
| `--format json\|table` | `json` | Output format |
| `--verbose` | off | Show HTTP details |
| `--dry-run` | off | Preview without executing |
| `--api-url URL` | — | Override backend URL |

**Exit codes:** 0 success · 1 API error · 2 auth error · 3 validation · 4 network · 5 internal

## Security Rules

- Commands marked `[!CAUTION]` are **write/destructive** — always confirm with the user before executing.
- Read-only commands are safe to run without confirmation.
- Never output auth tokens or secrets.
- Use `--dry-run` to preview destructive operations.

---

## notes — Quick note capture

```bash
deepvista notes list [--limit N] [--page N]
deepvista notes get <note_id>
deepvista notes create --title "Title" [--content "..."] [--tags '["t1"]']   # [!CAUTION]
deepvista notes update <note_id> [--title "..."] [--content "..."]           # [!CAUTION]
deepvista notes delete <note_id>                                              # [!CAUTION]
deepvista notes +quick "text"   # auto-derives title from first line          # [!CAUTION]
```

---

## vistabase — Knowledge base cards

Card types: `person` · `organization` · `message` · `todo` · `topic` · `keypoint` · `file` · `note` · `vistabook` · `vistabook_run`

```bash
# List & read
deepvista vistabase list [--type TYPE] [--status pinned|archived] [--limit N] [--order-by created_at|updated_at] [--order asc|desc]
deepvista vistabase get <card_id>

# Search (hybrid vector + keyword)
deepvista vistabase +search "query" [--type TYPE] [--limit N]

# Find similar cards
deepvista vistabase +similar <card_id> [--limit N]

# Write                                                                        [!CAUTION]
deepvista vistabase create --type TYPE --title "Title" [--content "..."] [--tags '["t1"]']
deepvista vistabase update <card_id> [--title "..."] [--content "..."] [--status pinned|archived]
deepvista vistabase delete <card_id>
deepvista vistabase +pin <card_id>
deepvista vistabase +archive <card_id>
```

---

## vistabook — Structured workflow templates

```bash
# Read
deepvista vistabook list [--limit N]
deepvista vistabook get <vistabook_id>
deepvista vistabook +status <run_chat_id>

# Run workflow (streams NDJSON)                                                [!CAUTION]
deepvista vistabook +run <vistabook_id> [--input "context"]

# Export as SKILL.md
deepvista vistabook +export <vistabook_id> --format skill
```

---

## chat — AI agent conversation

```bash
# Read
deepvista chat sessions [--limit N] [--offset N] [--search "query"]
deepvista chat get <chat_id>

# Write (streams NDJSON)                                                       [!CAUTION]
deepvista chat +send "message" [--chat-id ID] [--new]
deepvista chat delete <chat_id>                                                # [!CAUTION]
```

---

## Recipes

### Analyze notes — surface themes and patterns

1. Search for relevant notes:
   ```bash
   deepvista vistabase +search "<topic>" --type note --limit 20
   ```
2. List recent notes if no specific topic:
   ```bash
   deepvista notes list --limit 20
   ```
3. Fetch full content of key notes:
   ```bash
   deepvista notes get <note_id>
   ```
4. Synthesize: identify recurring themes, decisions, open questions, timeline.
5. Optionally save analysis as a new note (confirm with user first): `[!CAUTION]`
   ```bash
   deepvista notes create --title "Analysis: <topic> — <date>" --content "<synthesis>"
   ```

### Research → VistaBook

1. Search KB: `deepvista vistabase +search "topic" --limit 10`
2. Read top results: `deepvista vistabase get <id>`
3. Summarize findings into context string
4. List VistaBooks: `deepvista vistabook list`
5. Run with context (confirm first): `deepvista vistabook +run <id> --input "<summary>"` `[!CAUTION]`
6. Check status: `deepvista vistabook +status <run_chat_id>`

### Export knowledge as skills

1. List VistaBooks: `deepvista vistabook list`
2. Export each: `deepvista vistabook +export <id> --format skill`
3. Save SKILL.md output to `~/.agents/skills/<skill-name>/`

---

## Daily workflow

```bash
# 1. Check priorities
deepvista vistabase list --status pinned --limit 10

# 2. Find context for today's work
deepvista vistabase +search "today's focus area"

# 3. Capture a quick note
deepvista notes +quick "Insight: ..."

# 4. Run a workflow
deepvista vistabook list
deepvista vistabook +run <vistabook_id> --input "context"

# 5. Ask the agent
deepvista chat +send "Summarize what I've learned about X this week" --new
```

## Tips

- Always use `vistabase +search` before creating new content — avoid duplicates.
- `--order-by updated_at --order desc` shows recently touched cards.
- VistaBook runs create linked chat sessions — continue with `chat +send --chat-id <id>`.
- `--dry-run` previews write operations safely.
