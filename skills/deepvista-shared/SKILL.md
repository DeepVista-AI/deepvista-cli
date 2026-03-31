---
name: deepvista-shared
description: "DeepVista CLI: Authentication, global flags, and security conventions."
metadata:
  deepvista:
    category: "shared"
    requires:
      bins:
        - deepvista
    cliHelp: "deepvista --help"
---

# DeepVista CLI — Shared Reference

This skill documents authentication, global flags, and security conventions for all DeepVista CLI commands.

## Installation

If `deepvista` is not already installed, install it with any of:

```bash
# From PyPI
pip install deepvista-cli

# From GitHub (latest)
pip install git+https://github.com/DeepVista-AI/deepvista-cli.git
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
deepvista [GLOBAL FLAGS] <service> <command> [options]
```

If running from the cloned repo without installing, prefix commands with `uv run`.

**IMPORTANT:** Global flags like `--profile` must come BEFORE the service name:

```bash
# Correct:
deepvista --profile local notes list

# WRONG — will fail:
deepvista notes list --profile local
```

## Profiles

The CLI uses profiles to connect to different backends. Use `--profile local` for local development:

```bash
deepvista --profile local <service> <command>
```

List available profiles:

```bash
deepvista config list
```

## Authentication

```bash
# Step 1: Open browser login page
deepvista auth login

# Step 2: Copy the command shown in the browser and paste it:
deepvista auth login --code <base64_code>

# Check auth state
deepvista auth status

# Logout
deepvista auth logout
```

## CLI Syntax

```
deepvista [--profile NAME] <service> <command> [options]
deepvista [--profile NAME] <service> +<helper> [args] [options]
```

**Services:** `auth`, `config`, `vistabase`, `vistabook`, `notes`, `chat`

## Global Flags

Global flags go BEFORE the service name.

| Flag | Default | Description |
|------|---------|-------------|
| `--profile NAME` | `default` | Config profile to use (e.g. `local`, `staging`). |
| `--format json\|table` | `json` | Output format. JSON is default (agent-friendly). |
| `--verbose` | off | Show HTTP request/response details on stderr. |
| `--dry-run` | off | Show what would be sent without executing. |
| `--base-url URL` | — | Override backend URL. |
| `--version` | — | Show version and exit. |
| `--help` | — | Show help for any command. |

## Output Format

- **JSON** (default): Structured JSON to stdout. Agents should parse this.
- **Table**: Human-readable table on stderr + JSON on stdout.
- **Errors**: `{"error": {"code": N, "message": "...", "detail": "..."}}` on stderr.
- **Streaming** (chat, vistabook +run): NDJSON — one JSON object per line.

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
deepvista vistabase --help
deepvista vistabase +search --help
```

## Security Rules

1. **Write commands** are marked with `> [!CAUTION]` — always confirm with the user before executing write/delete operations.
2. **Read-only commands** are safe to run without confirmation.
3. **Never output tokens or secrets** — use `deepvista --profile local auth status` to check auth state.
4. **Use `--dry-run`** to preview destructive operations before executing.
5. **Tokens are sensitive** — stored in `~/.config/deepvista/credentials.json` (mode 0600).

## See Also

- [deepvista-vistabase](../deepvista-vistabase/SKILL.md) — Knowledge base cards
- [deepvista-vistabook](../deepvista-vistabook/SKILL.md) — VistaBook workflows
- [deepvista-notes](../deepvista-notes/SKILL.md) — Notes management
- [deepvista-chat](../deepvista-chat/SKILL.md) — Chat with AI agent
