---
name: deepvista-vistabook
description: "DeepVista VistaBook: Manage structured workflow templates and run them via the AI agent."
metadata:
  deepvista:
    category: "service"
    requires:
      bins:
        - uv
      skills:
        - deepvista-shared
    cliHelp: "deepvista vistabook --help"
---

# VistaBook

> **PREREQUISITE:** Read [deepvista-shared](../deepvista-shared/SKILL.md) for auth, profiles, and global flags.

VistaBooks are structured checklist workflows stored as context cards. Each VistaBook is a template with phases and steps. Running a VistaBook creates a "run" -- an execution instance where the AI agent works through the checklist.

## Commands

### list

```bash
deepvista vistabook list [--limit N] [--page N]
```

Read-only -- lists all VistaBook templates.

### get

```bash
deepvista vistabook get <vistabook_id>
```

Read-only -- returns full VistaBook content including checklist phases.

### +run

```bash
deepvista vistabook +run <vistabook_id> [--input "context text"]
```

Start a VistaBook run -- the AI agent executes the workflow checklist step by step.

| Flag | Required | Default | Description |
|------|----------|---------|-------------|
| `<vistabook_id>` | Yes | — | ID of the VistaBook template to run |
| `--input` | No | — | Context or instructions for the run |

> [!CAUTION]
> Write command -- creates a new VistaBook run (a chat session) and the agent may create/update context cards, search the web, and take other actions. Confirm with the user before executing.

Output is NDJSON (one JSON object per line) as the agent streams its response.

- Use `vistabook list` first to find available VistaBook IDs.
- Check run status afterward: `vistabook +status <run_chat_id>`
- The run creates a linked chat session -- you can continue the conversation with `chat +send`.

### +status

```bash
deepvista vistabook +status <run_chat_id>
```

Read-only -- shows run state (running, awaiting_input, completed, failed, paused).

### +export

```bash
deepvista vistabook +export <vistabook_id> --format skill
```

Export a VistaBook as a SKILL.md file -- the VistaBook-as-Skill pipeline. Author workflows in DeepVista's GUI, then export them as installable agent skills.

| Flag | Required | Default | Description |
|------|----------|---------|-------------|
| `<vistabook_id>` | Yes | — | ID of the VistaBook to export |
| `--format` | No | `skill` | Export format (currently only `skill`) |

Read-only -- generates output but does not modify the VistaBook. The exported SKILL.md can be installed with `npx skills add` or placed in `~/.agents/skills/`.

## Examples

```bash
# List all vistabooks
deepvista vistabook list

# Run a vistabook
deepvista vistabook +run vb_abc123 --input "Focus on Q4 objectives"

# Check if a run is complete
deepvista vistabook +status chat_xyz789

# Export as a skill for other agents
deepvista vistabook +export vb_abc123 --format skill
```

## See Also

- [deepvista-shared](../deepvista-shared/SKILL.md) — Auth and global flags
- [deepvista-chat](../deepvista-chat/SKILL.md) — Continue a VistaBook run conversation
