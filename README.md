# deepvista-cli

CLI for DeepVista — manage your knowledge base, VistaBooks, notes, and chat from the terminal. Designed for both humans and AI agents.

## Table of Contents

- [For AI Agents](#for-ai-agents)
- [Install](#install)
- [Authentication](#authentication)
- [Profiles](#profiles)
- [Commands](#commands)
- [Global Flags](#global-flags)
- [Output](#output)
- [Exit Codes](#exit-codes)
- [Environment Variables](#environment-variables)
- [Files](#files)
- [See Also](#see-also)

---

## For AI Agents

<p>
  <img src="https://cdn.simpleicons.org/anthropic/000000" width="18" alt="Claude Code" />&nbsp; <strong>Claude Code</strong> &nbsp;&nbsp;
  <img src="https://cdn.simpleicons.org/cursor/000000" width="18" alt="Cursor" />&nbsp; <strong>Cursor</strong> &nbsp;&nbsp;
  <strong>OpenCode</strong> &nbsp;&nbsp;
  and any agent that supports skills
</p>

The key idea: **install once, then talk to your agent**. The agent handles authentication and all commands on your behalf.

### Install

Run this in your terminal — no Node, no extra tools required beyond a Python package manager and either `git` or `curl`:

```bash
curl -sSL https://raw.githubusercontent.com/DeepVista-AI/deepvista-cli/main/install.sh | bash
```

The script:
1. Installs the `deepvista` CLI (auto-detects `uv`, `pipx`, or `pip`)
2. Copies 9 skills into your agent's skills directory (auto-detects Claude Code, OpenCode, Cursor, and others)

| Skill | What it teaches your agent |
|-------|---------------------------|
| `deepvista-shared` | Auth, profiles, global flags, security rules |
| `deepvista-vistabase` | Knowledge base — search, read, create, update cards |
| `deepvista-notes` | Note capture and management |
| `deepvista-vistabook` | Run structured AI workflows |
| `deepvista-chat` | Conversational AI agent |
| `deepvista-persona-knowledge-worker` | Daily knowledge workflow patterns |
| `deepvista-recipe-research-to-vistabook` | Search → synthesize → run workflow |
| `deepvista-recipe-export-knowledge-as-skills` | Turn your knowledge into installable skills |
| `deepvista-recipe-analyze-notes` | Analyze, summarize, and find patterns across notes |

### Get Started

Open your agent and paste:

```
Load skills: deepvista-shared deepvista-notes deepvista-vistabase deepvista-vistabook

Help me get started with DeepVista. Walk me through logging in.
```

Your agent will:
1. Open the browser login page
2. Guide you through pasting the auth code
3. Confirm you're logged in with `deepvista auth status`

> **Claude Code tip:** If you're prompted to confirm skill file reads, run once:
> ```bash
> claude config set allowedPaths "~/.claude/skills" --global
> ```

---

## Use Cases

### Capture Insights from Podcasts

Build a searchable knowledge base from founder interviews.

After listening to an episode, ask your agent:

```
Load skills: deepvista-shared deepvista-notes

I just listened to the Lenny's Podcast episode with Brian Chesky about founder mode.
Here are my notes:

- CEOs in "manager mode" lose touch with what's actually happening in the product
- Founder mode means staying in the details — not micromanaging, but knowing
- Skip-level meetings: he talks directly to ICs, bypasses middle layers
- Airbnb COVID turnaround: cut to essentials, rediscovered product obsession
- "Great founders don't just set vision and delegate. They stay in the arena."

Save this to my knowledge base as a note titled "Brian Chesky — Founder Mode".
```

Search and retrieve across everything you've captured:

```
Load skills: deepvista-shared deepvista-vistabase

Search my knowledge base for everything I've captured about founder mindset and obsession.
Show me the top 5 results.
```

Quick capture mid-session:

```
Quick note: "Tobi Lütke on Lenny's — the company is a tool to amplify your ability to do what you love. Not the destination, the instrument."
```

### Research and Synthesize with a VistaBook

Once you've captured 10–20 interviews, ask your agent to synthesize patterns:

```
Load skills: deepvista-shared deepvista-vistabase deepvista-vistabook deepvista-recipe-research-to-vistabook

I want to synthesize patterns from the founder interviews I've captured in my knowledge base.

1. Search for cards about growth, momentum, and early-stage execution
2. Search for cards about hiring and team building
3. Find my "Research Synthesis" VistaBook (or the most relevant one)
4. Run it with context focused on: what separates high-growth founders, common 0→1 mistakes,
   and how great founders think about product

Show me what you find before running the VistaBook so I can confirm.
```

The agent searches, reads your notes, finds the VistaBook, confirms with you, then streams the run live.

### Build a Founder Playbook

Capture frameworks, then run an idea evaluation workflow:

```
Load skills: deepvista-shared deepvista-vistabase deepvista-vistabook

I have a new startup idea I want to evaluate against my founder playbook.

Idea: a CLI tool that lets developers query their observability stack in natural language.
Context: I work in DevOps, I've felt this pain daily for 3 years. Market: all companies
running microservices (~50k+ teams globally).

1. Search my knowledge base for any idea validation frameworks I've captured
2. Find my idea evaluation VistaBook
3. Run it with the above context — but show me the VistaBook first so I can review it
```

Export your playbook as a reusable skill:

```
Load skills: deepvista-shared deepvista-vistabook deepvista-recipe-export-knowledge-as-skills

Export my founder playbook VistaBook as a SKILL.md file so I can share it with my team.
```

---

## VistaBook Patterns

Build these workflows in the DeepVista web app, then invoke them through your agent:

| VistaBook | Prompt to invoke |
|-----------|-----------------|
| **Research synthesis** | "Search my KB for [topic] and run my Research Synthesis VistaBook" |
| **Idea evaluation** | "Evaluate this idea against my founder frameworks: [idea]" |
| **Weekly review** | "Run my weekly review — surface pinned cards and capture this week's key learnings" |
| **Interview debrief** | "I just finished a user interview. Run my Interview Debrief VistaBook with these notes: [notes]" |
| **Decision memo** | "Help me think through this decision using my knowledge base: [decision]" |
| **Competitive analysis** | "Run a competitive analysis on [company/space] using everything I've captured" |

---

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
export DEEPVISTA_AUTH_URL=https://staging.deepvista.ai
deepvista auth login
```

### Check / clear auth

```bash
deepvista auth status
deepvista auth logout
```

## Profiles

Profiles store `api_url` so you don't need env vars for each environment.

### Create a profile

```bash
# Local development
deepvista config set local --api-url http://localhost:8080

# Staging
deepvista config set staging --api-url https://api-staging.deepvista.ai
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

1. CLI flags (`--api-url`, `--format`, etc.)
2. Environment variables (`DEEPVISTA_API_URL`, etc.)
3. Named profile (`--profile local`)
4. Built-in default (`https://api.deepvista.ai`)

## Commands

### vistabase — Knowledge base cards

```bash
# List cards
deepvista vistabase list [--type person|note|topic|...] [--limit N] [--page N]

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
deepvista vistabook list [--limit N] [--page N]
deepvista vistabook get <vistabook_id>
deepvista vistabook +run <vistabook_id> [--input "context"]
deepvista vistabook +status <run_chat_id>
deepvista vistabook +export <vistabook_id> --format skill
```

### notes — Quick note management

```bash
deepvista notes list [--limit N] [--page N]
deepvista notes get <note_id>
deepvista notes create --title "Title" --content "..."
deepvista notes update <note_id> --title "..." --content "..."
deepvista notes delete <note_id>
deepvista notes +quick "Quick note from a single line"
```

### chat — Talk to the DeepVista agent

```bash
deepvista chat sessions [--limit N] [--offset N] [--search "query"]
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
| `--api-url URL` | staging | Override backend URL |
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
| `DEEPVISTA_API_URL` | Backend API URL (default: `https://api.deepvista.ai`) |
| `DEEPVISTA_AUTH_URL` | Auth app URL for login (default: `https://app.deepvista.ai`) |
| `DEEPVISTA_SUPABASE_URL` | Supabase project URL |
| `DEEPVISTA_CONFIG_DIR` | Config directory (default: `~/.config/deepvista`) |

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
    ├── deepvista-recipe-analyze-notes/
    ├── deepvista-recipe-export-knowledge-as-skills/
    └── deepvista-recipe-research-to-vistabook/
```

## See Also

- [skills/](./skills/) — SKILL.md files, installable via `npx skills add`
- [deepvista.ai](https://deepvista.ai) — Web app to build and manage VistaBooks
- [PyPI](https://pypi.org/project/deepvista-cli/) — Package releases
- [GitHub Issues](https://github.com/DeepVista-AI/deepvista-cli/issues) — Bug reports and feature requests
