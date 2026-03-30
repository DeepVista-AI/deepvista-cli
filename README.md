# deepvista-cli

CLI for DeepVista — manage your knowledge base, VistaBooks, notes, and chat from the terminal. Designed for both humans and AI agents.

## Install

### From PyPI (once published)

```bash
pip install deepvista-cli
```

```bash
uv tool install deepvista-cli
```

```bash
pipx install deepvista-cli
```

### Directly from GitHub (available now)

```bash
pip install git+https://github.com/DeepVista-AI/deepvista-cli.git
```

Pin to a specific tag or branch:

```bash
pip install git+https://github.com/DeepVista-AI/deepvista-cli.git@v0.1.0
pip install git+https://github.com/DeepVista-AI/deepvista-cli.git@main
```

Or with uv / pipx:

```bash
uv tool install git+https://github.com/DeepVista-AI/deepvista-cli.git
pipx install git+https://github.com/DeepVista-AI/deepvista-cli.git
```

### For development (from this repo)

```bash
uv sync
uv run deepvista --help
```

## Authentication

### Browser login (default)

```bash
deepvista auth login
```

Opens your browser to DeepVista's login page. After authenticating with Google, copy the auth code shown on screen and paste it back into the terminal.

### Paste code directly (skip browser)

```bash
deepvista auth login --code <base64_auth_code>
```

### Self-hosted / staging

```bash
export DEEPVISTA_SITE_URL=https://staging.deepvista.ai
deepvista auth login
```

### Check / clear auth

```bash
deepvista auth status
deepvista auth logout
```

## Profiles

Profiles store `base_url` so you don't need env vars for each environment.

### Create a profile

```bash
# Local development
deepvista config set local \
  --base-url http://localhost:8080

# Staging (Cloud Run)
deepvista config set staging \
  --base-url https://deepvista-ai-service-160619978676.us-west1.run.app
```

### Use a profile

```bash
deepvista --profile local vistabase list
deepvista --profile staging chat +send "hello" --new
```

### Manage profiles

```bash
deepvista config list       # list all profiles
deepvista config show local # show one profile
deepvista config delete old # delete a profile
```

### Resolution order

Settings are resolved in this order (first wins):

1. CLI flags (`--base-url`, `--format`, etc.)
2. Environment variables (`DEEPVISTA_BASE_URL`, etc.)
3. Named profile (`--profile local`)
4. Built-in defaults (staging Cloud Run)

## Commands

### vistabase — Knowledge base cards

```bash
# List cards
deepvista vistabase list [--type person|note|topic|...] [--limit N]

# Get a card
deepvista vistabase get <card_id>

# Create a card
deepvista vistabase create --type note --title "Title" --content "..."

# Update a card
deepvista vistabase update <card_id> --title "New title"

# Delete a card
deepvista vistabase delete <card_id>

# Search (hybrid vector + keyword)
deepvista vistabase +search "query text" [--type person] [--limit 10]

# Find similar cards
deepvista vistabase +similar <card_id>

# Pin / archive
deepvista vistabase +pin <card_id>
deepvista vistabase +archive <card_id>
```

Card types: `person`, `organization`, `message`, `todo`, `topic`, `keypoint`, `file`, `note`, `vistabook`, `vistabook_run`

### vistabook — Workflow templates & runs

```bash
deepvista vistabook list
deepvista vistabook get <vistabook_id>
deepvista vistabook +run <vistabook_id> [--input "context"]
deepvista vistabook +status <run_chat_id>
deepvista vistabook +export <vistabook_id> --format skill
```

### notes — Quick note management

```bash
deepvista notes list
deepvista notes get <note_id>
deepvista notes create --title "Title" --content "..."
deepvista notes update <note_id> --title "..." --content "..."
deepvista notes delete <note_id>
deepvista notes +quick "Quick note from a single line"
```

### chat — Talk to the DeepVista agent

```bash
deepvista chat sessions [--limit N] [--search "query"]
deepvista chat get <chat_id>
deepvista chat delete <chat_id>
deepvista chat +send "your message" [--chat-id ID] [--new]
```

Chat output is NDJSON (one JSON object per line) streamed from the agent.

## Global Flags

| Flag | Default | Description |
|------|---------|-------------|
| `--format json\|table` | `json` | Output format |
| `--verbose` | off | Show HTTP request/response details |
| `--dry-run` | off | Show what would be sent, don't execute |
| `--base-url URL` | staging | Override backend URL |
| `--profile NAME` | `default` | Use a named config profile |

**Global flags must come before the service name:**

```bash
# Correct:
deepvista --profile local vistabase list

# Wrong:
deepvista vistabase list --profile local
```

## Output

- **JSON** (default): Structured JSON to stdout. Agents parse this.
- **Table**: `--format table` for human-readable output.
- **Errors**: `{"error": {"code": N, "message": "...", "detail": "..."}}` on stderr.
- **Streaming**: NDJSON for `chat +send` and `vistabook +run`.

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | API error |
| 2 | Auth error |
| 3 | Validation error |
| 4 | Network error |
| 5 | Internal error |

## Environment Variables

| Variable | Description |
|----------|-------------|
| `DEEPVISTA_BASE_URL` | Backend API URL |
| `DEEPVISTA_SITE_URL` | Web app URL for login (default: `https://app.deepvista.ai`) |
| `DEEPVISTA_SUPABASE_URL` | Supabase project URL |
| `DEEPVISTA_CONFIG_DIR` | Config directory (default: `~/.config/deepvista`) |

## For AI Agents

Install the skills so agents (Claude Code, OpenCode, etc.) can discover and use the CLI:

```bash
npx skills add deepvista/deepvista-cli
```

Skills are in `skills/` — SKILL.md files covering shared auth, all services, helpers, recipes, and a persona.

## Files

```
deepvista-cli/
├── deepvista_cli/          # Python package
│   ├── main.py             # Click entry point
│   ├── config.py           # Config + profiles
│   ├── auth/               # Login, token storage
│   ├── client/             # HTTP client, SSE streaming
│   ├── commands/           # auth, vistabase, vistabook, notes, chat, config
│   └── output/             # JSON + table formatters
└── skills/                 # SKILL.md files for agent integration
    ├── deepvista-shared/       # Auth, global flags, security rules
    ├── deepvista-vistabase/    # Knowledge base cards
    ├── deepvista-vistabook/    # Workflow templates & runs
    ├── deepvista-notes/        # Notes management
    ├── deepvista-chat/         # Chat with AI agent
    ├── deepvista-persona-knowledge-worker/
    ├── deepvista-recipe-export-knowledge-as-skills/
    └── deepvista-recipe-research-to-vistabook/
```
