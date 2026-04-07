---
name: deepvista-recipe
description: "DeepVista Recipe: Manage structured executable workflows (Recipes) and run them via the AI agent."
metadata:
  deepvista:
    category: "service"
    requires:
      bins:
        - uv
      skills:
        - deepvista-shared
    cliHelp: "deepvista recipe --help"
---

# Recipe (Executable Workflows)

> **PREREQUISITE:** Read [deepvista-shared](../deepvista-shared/SKILL.md) for auth, profiles, and global flags.

Recipes are structured checklist workflows. Each Recipe is a template with phases and steps. Running a Recipe creates a "run" — an execution instance where the AI agent works through the checklist.

**Command:** `deepvista recipe <subcommand>`

## App URLs

After any write operation (run, create), always show the recipe URL to the user:

```
https://app.deepvista.ai/memory?contextId=<id>
```

Extract the `id` from the JSON response and present it as a clickable link.

## Commands

### list

```bash
deepvista recipe list [--limit N] [--page N]
```

Read-only — lists all Recipe templates.

### get

```bash
deepvista recipe get <recipe_id>
```

Read-only — returns full Recipe content including checklist phases.

### run

```bash
deepvista recipe run <recipe_id> [--input "context text"]
```

Start a Recipe run — the AI agent executes the workflow checklist step by step.

| Flag | Required | Default | Description |
|------|----------|---------|-------------|
| `<recipe_id>` | Yes | — | ID of the Recipe template to run |
| `--input` | No | — | Context or instructions for the run |

> [!CAUTION]
> Write command — creates a new Recipe run (a chat session) and the agent may create/update context cards, search the web, and take other actions. Confirm with the user before executing.

Output is NDJSON (one JSON object per line) as the agent streams its response.

### status

```bash
deepvista recipe status <run_chat_id>
```

Read-only — shows run state (running, awaiting_input, completed, failed, paused).

### export

```bash
deepvista recipe export <recipe_id> --format skill
```

Export a Recipe as a SKILL.md file for use in AI agents.

| Flag | Required | Default | Description |
|------|----------|---------|-------------|
| `<recipe_id>` | Yes | — | ID of the Recipe to export |
| `--format` | No | `skill` | Export format (currently only `skill`) |

Read-only — generates output but does not modify the Recipe.

## Examples

```bash
# List all recipes
deepvista recipe list

# Run a recipe
deepvista recipe run vb_abc123 --input "Focus on Q4 objectives"

# Check if a run is complete
deepvista recipe status chat_xyz789

# Export as a skill for other agents
deepvista recipe export vb_abc123 --format skill
```

## See Also

- [deepvista-shared](../deepvista-shared/SKILL.md) — Auth and global flags
- [deepvista-chat](../deepvista-chat/SKILL.md) — Continue a Recipe run conversation
