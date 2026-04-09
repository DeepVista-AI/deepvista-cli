---
name: deepvista-shared
description: "DeepVista CLI: Authentication, global flags, and security conventions."
metadata:
  openclaw:
    category: shared
    requires:
      bins:
        - deepvista
    install:
      - kind: uv
        package: deepvista-cli
        bins: [deepvista]
    homepage: https://cli.deepvista.ai
    cliHelp: "deepvista --help"
---

# DeepVista CLI — Shared Reference

This skill documents authentication, global flags, and security conventions for all DeepVista CLI commands.

## On Load

When this skill is loaded, silently run the following command in the background to check for skill updates:

```bash
deepvista skill check-update
```

- If the command exits 0: skills are up to date — say nothing, continue normally.
- If the command exits 1 (updates available): inform the user that newer versions of the DeepVista skills are available and show the update command printed by the tool.
- If `deepvista` is not installed or the command fails: skip silently.

## Installation

If `deepvista` is not already installed, install it with any of:

```bash
# From PyPI
pip install deepvista-cli

# With TUI support
pip install 'deepvista-cli[ui]'
```

With uv or pipx:

```bash
uv tool install deepvista-cli
pipx install deepvista-cli
```

Verify:

```bash
deepvista --version
```

## Running Commands

```bash
deepvista [GLOBAL FLAGS] <resource> <command> [options]
```

If running from the cloned repo without installing, prefix commands with `uv run`.

**IMPORTANT:** Global flags like `--profile` must come BEFORE the resource name:

```bash
# Correct:
deepvista card list

# WRONG — will fail:
deepvista card list --profile local
```

## Resources

```
card      Knowledge cards (context cards — all types)
recipe    Executable workflows (run structured checklists)
memory    Implicit context automatically accumulated from Chat
chat      Conversational AI agent
```

Support commands: `auth`, `config`, `notes` (shorthand for card --type note)

## Profiles

Commands use the `default` profile unless you specify one. To target a specific backend, pass `--profile NAME` before the resource name:

```bash
deepvista --profile staging card list
```

List available profiles:

```bash
deepvista config list
```

## Authentication

```bash
# Interactive: opens browser, authenticates automatically
deepvista auth login

# Non-interactive: visit /cli in browser, paste the code shown
deepvista auth login --code XXXX-XXXX

# Check auth state
deepvista auth status

# Logout
deepvista auth logout
```

## CLI Syntax

```
deepvista [--profile NAME] <resource> <command> [options]
deepvista [--profile NAME] <resource> +<helper> [args] [options]
```

## Global Flags

Global flags go BEFORE the resource name.

| Flag | Default | Description |
|------|---------|-------------|
| `--profile NAME` | `default` | Config profile to use (e.g. `local`, `staging`). |
| `--format json\|table` | `json` | Output format. JSON is default (agent-friendly). |
| `--verbose` | off | Show HTTP request/response details on stderr. |
| `--dry-run` | off | Show what would be sent without executing. |
| `--api-url URL` | — | Override backend URL. |
| `--version` | — | Show version and exit. |
| `--help` | — | Show help for any command. |

## Launch the TUI

```bash
deepvista ui
```

Opens the terminal UI with Chat, Notes, Recipes, and Memory panels.
Requires: `pip install 'deepvista-cli[ui]'`

## Output Format

- **JSON** (default): Structured JSON to stdout. Agents should parse this.
- **Table**: Human-readable table on stderr + JSON on stdout.
- **Errors**: `{"error": {"code": N, "message": "...", "detail": "..."}}` on stderr.
- **Streaming** (chat +send, recipe run): NDJSON — one JSON object per line.

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | API error (backend returned error) |
| 2 | Auth error (not logged in / token expired) |
| 3 | Validation error (bad arguments) |
| 4 | Network error (cannot reach backend) |
| 5 | Internal error |

## Self-Discovery

Every command supports `--help`:

```bash
deepvista --help
deepvista card --help
deepvista card +search --help
deepvista recipe --help
deepvista memory --help
```

## Security Rules

1. **Write commands** are marked with `> [!CAUTION]` — always confirm with the user before executing write/delete operations.
2. **Read-only commands** are safe to run without confirmation.
3. **Never output tokens or secrets** — use `deepvista auth status` to check auth state.
4. **Use `--dry-run`** to preview destructive operations before executing.
5. **Tokens are sensitive** — stored in `~/.config/deepvista/credentials.json` (mode 0600).

## See Also

- [deepvista-vistabase](../deepvista-vistabase/SKILL.md) — Implicit context (vistabase)
- [deepvista-recipe](../deepvista-recipe/SKILL.md) — Recipes (executable workflows)
- [deepvista-notes](../deepvista-notes/SKILL.md) — Notes management
- [deepvista-chat](../deepvista-chat/SKILL.md) — Chat with AI agent
