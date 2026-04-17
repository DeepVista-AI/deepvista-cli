---
name: deepvista-skill
description: "DeepVista Skill: Manage structured executable workflows (Skills) and run them via the AI agent."
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
    cliHelp: "deepvista skill --help"
---

# Skill (Executable Workflows)


## On Load — Update Check

When this skill is loaded, silently run once:

```bash
deepvista upgrade check 2>/dev/null || true
```

- Empty output (exit 0) → up to date, snoozed, or disabled — say nothing.
- `UPGRADE_AVAILABLE <old> <new>` (exit 1) → tell the user a newer `deepvista-cli` is available and offer to run `deepvista upgrade`. That command fetches the changelog between `<old>` and `<new>`, shows what changed, and prompts before installing.
- `JUST_UPGRADED <old> <new>` (exit 0) → briefly confirm the upgrade completed.
- Command not found → skip silently; do not auto-install.

See [deepvista-shared](../deepvista-shared/SKILL.md#on-load--update-check) for full details.

> **PREREQUISITE:** Read [deepvista-shared](../deepvista-shared/SKILL.md) for auth, profiles, and global flags.

Skills are structured checklist workflows. Each Skill is a template with phases and steps. Running a Skill creates a "run" — an execution instance where the AI agent works through the checklist.

**Command:** `deepvista skill <subcommand>`

## App URLs

After any write operation (run, create), always show the skill URL to the user:

```
https://app.deepvista.ai/skills/<id>
```

Extract the `id` from the JSON response and present it as a clickable link.

## Commands

### list

```bash
deepvista skill list [--limit N] [--page N]
```

Read-only — lists all Skill templates.

### get

```bash
deepvista skill get <skill_id>
```

Read-only — returns full Skill content including checklist phases.

### run

```bash
deepvista skill run <skill_id> [--input "context text"]
```

Start a Skill run — the AI agent executes the workflow checklist step by step.

| Flag | Required | Default | Description |
|------|----------|---------|-------------|
| `<skill_id>` | Yes | — | ID of the Skill template to run |
| `--input` | No | — | Context or instructions for the run |

> [!CAUTION]
> Write command — creates a new Skill run (a chat session) and the agent may create/update context cards, search the web, and take other actions. Confirm with the user before executing.

Output is NDJSON (one JSON object per line) as the agent streams its response.

### status

```bash
deepvista skill status <run_chat_id>
```

Read-only — shows run state (running, awaiting_input, completed, failed, paused).

### export

```bash
deepvista skill export <skill_id> --format skill
```

Export a Skill as a SKILL.md file for use in AI agents.

| Flag | Required | Default | Description |
|------|----------|---------|-------------|
| `<skill_id>` | Yes | — | ID of the Skill to export |
| `--format` | No | `skill` | Export format (currently only `skill`) |

Read-only — generates output but does not modify the Skill.

### discover

```bash
deepvista skill discover [--search "query"] [--category persona|productivity|workflow] [--limit N]
```

Read-only — browse available skills from the marketplace.

| Flag | Required | Default | Description |
|------|----------|---------|-------------|
| `--search` / `-s` | No | — | Filter by title or description |
| `--category` / `-c` | No | — | Filter: persona, productivity, workflow |
| `--limit` | No | 50 | Max results |

### install

```bash
deepvista skill install <skill_id>
```

Install a marketplace skill into your library.

| Flag | Required | Default | Description |
|------|----------|---------|-------------|
| `<skill_id>` | Yes | — | ID from `deepvista skill discover` output |

> [!CAUTION]
> Write command — creates a new Skill in your library. Confirm with the user before executing.

## Examples

```bash
# List all skills
deepvista skill list

# Run a skill
deepvista skill run vb_abc123 --input "Focus on Q4 objectives"

# Check if a run is complete
deepvista skill status chat_xyz789

# Export as a skill for other agents
deepvista skill export vb_abc123 --format skill

# Browse marketplace skills
deepvista skill discover --category persona

# Search marketplace
deepvista skill discover --search "email"

# Install a marketplace skill
deepvista skill install persona-researcher
```

## See Also

- [deepvista-shared](../deepvista-shared/SKILL.md) — Auth and global flags
- [deepvista-chat](../deepvista-chat/SKILL.md) — Continue a Skill run conversation
