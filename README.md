# deepvista-cli

[![PyPI - Status](https://img.shields.io/pypi/status/deepvista-cli)](https://pypi.org/project/deepvista-cli/)
[![PyPI](https://img.shields.io/pypi/v/deepvista-cli)](https://pypi.org/project/deepvista-cli/)
[![ClawHub](https://img.shields.io/badge/ClawHub-deepvista-blue)](https://clawhub.ai/skills?q=deepvista)
[![skills.sh](https://img.shields.io/badge/skills.sh-DeepVista--AI-purple)](https://skills.sh/deepvista-ai/deepvista-cli)

CLI for DeepVista — chat, notes, skills, and vistabase from your terminal. Designed for both humans and AI agents.

## Table of Contents

- [For AI Agents](#for-ai-agents)
- [Install](#install)
- [Uninstall](#uninstall)
- [Terminal UI (TUI)](#terminal-ui-tui)
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
2. Copies skills into your agent's skills directory (auto-detects Claude Code, OpenCode, Cursor, and others)

| Skill | What it teaches your agent |
|-------|---------------------------|
| `deepvista-shared` | Auth, profiles, global flags, security rules |
| `deepvista-vistabase` | Knowledge cards — search, read, create, update |
| `deepvista-notes` | Note capture and management |
| `deepvista-vistabook` | Run structured AI skills/workflows |
| `deepvista-vistabase` | View and search implicit vistabase context |
| `deepvista-chat` | Conversational AI agent |
| `deepvista-persona-knowledge-worker` | Daily knowledge workflow patterns |
| `deepvista-skill-research-to-skill` | Search → synthesize → run workflow |
| `deepvista-skill-export-knowledge` | Turn your knowledge into installable skills |
| `deepvista-skill-analyze-notes` | Analyze, summarize, and find patterns across notes |

### Get Started

Open your agent and paste:

```
Load skills: deepvista-shared deepvista-notes deepvista-vistabase

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

### Auto-Capture Notes

The install script automatically enables auto-capture in every detected agent — no manual setup required.

| Agent | Config file written |
|-------|-------------------|
| Claude Code | `~/.claude/CLAUDE.md` |
| Cursor | `~/.cursor/rules` |
| OpenCode | `~/.opencode/AGENTS.md` |

Once installed, your agent will silently save facts, decisions, insights, and action items to your DeepVista knowledge base as you work — no manual invocation needed. The install is idempotent: re-running it won't duplicate the block.

To remove auto-capture, delete the `<!-- deepvista-auto-capture -->` block from the relevant config file, or run the uninstall script (see [Uninstall](#uninstall)).

---

## Use Cases

### Capture Insights from Podcasts

Build a searchable knowledge base from founder interviews.

After listening to an episode, ask your agent:

```
Load skills: deepvista-shared deepvista-notes

I just listened to the Lenny's Podcast episode with Brian Chesky about founder mode.
Here are my notes: ...

Save this to my knowledge base as a note titled "Brian Chesky — Founder Mode".
```

Search and retrieve across everything you've captured:

```
Load skills: deepvista-shared deepvista-vistabase

Search my knowledge base for everything I've captured about founder mindset and obsession.
Show me the top 5 results.
```

### Research and Synthesize with a Skill

Once you've captured 10–20 interviews, ask your agent to synthesize patterns:

```
Load skills: deepvista-shared deepvista-vistabase deepvista-vistabook deepvista-skill-research-to-skill

Search for cards about growth and early-stage execution, then find my Research Synthesis
skill and run it focused on: what separates high-growth founders, common 0→1 mistakes.
Show me what you find before running.
```

The agent searches, reads your notes, finds the Skill, confirms with you, then streams the run live.

### Build a Founder Playbook

```
Load skills: deepvista-shared deepvista-vistabase deepvista-vistabook

I have a new startup idea to evaluate. Idea: [your idea].
1. Search my knowledge base for any idea validation frameworks
2. Find my idea evaluation Skill
3. Run it with the above context — show me the Skill first
```

Export your playbook as a reusable skill:

```
Load skills: deepvista-shared deepvista-vistabook deepvista-skill-export-knowledge

Export my founder playbook Skill as a SKILL.md file so I can share it with my team.
```

---

## Skill Patterns

Build these workflows in the DeepVista web app, then invoke them through your agent:

| Skill | Prompt to invoke |
|--------|-----------------|
| **Research synthesis** | "Search my KB for [topic] and run my Research Synthesis Skill" |
| **Idea evaluation** | "Evaluate this idea against my founder frameworks: [idea]" |
| **Weekly review** | "Run my weekly review — surface pinned cards and capture this week's key learnings" |
| **Interview debrief** | "I just finished a user interview. Run my Interview Debrief Skill with these notes: [notes]" |
| **Decision memo** | "Help me think through this decision using my knowledge base: [decision]" |
| **Competitive analysis** | "Run a competitive analysis on [company/space] using everything I've captured" |

---

## Install

### From PyPI

```bash
pip install deepvista-cli
pipx install deepvista-cli
uv tool install deepvista-cli
```

### With Terminal UI support

```bash
pip install 'deepvista-cli[ui]'
uv tool install 'deepvista-cli[ui]'
```

### Directly from GitHub

```bash
pip install git+https://github.com/DeepVista-AI/deepvista-cli.git
uv tool install git+https://github.com/DeepVista-AI/deepvista-cli.git
```

### For development (from this repo)

```bash
uv sync
uv pip install -e '.[ui]'   # include TUI
uv run deepvista --help
```

## Uninstall

```bash
curl -sSL https://raw.githubusercontent.com/DeepVista-AI/deepvista-cli/main/uninstall.sh | bash
```

The script:
1. Uninstalls the `deepvista` CLI
2. Removes all DeepVista skills from detected agent skill directories
3. Removes the auto-capture block from agent config files

---

## Terminal UI (TUI)

DeepVista includes a full terminal UI with four panels matching the product's core modules.

### Launch

```bash
deepvista ui
```

Requires the `[ui]` optional dependency:

```bash
pip install 'deepvista-cli[ui]'
```

### Panels

| Panel | Key | Description |
|-------|-----|-------------|
| **Chat** | `1` | Converse with the DeepVista AI agent. Select past sessions from the sidebar or start a new one. Responses stream in real time. |
| **Notes** | `2` | Browse and search your explicit knowledge (notes). Click any note to read its full content. |
| **Skills** | `3` | List all Skills (structured workflows). Select one to view its details and run it with the **▶ Run Skill** button — output streams live. |
| **Memory** | `4` | Read-only view of implicit context accumulated from your Chat sessions. Searchable. |

### Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `1` – `4` | Switch between Chat / Notes / Skills / Memory |
| `r` | Refresh the active panel |
| `q` | Quit |
| `Enter` | Send message (in Chat input) |

---

## Authentication

### Browser login (default)

```bash
deepvista auth login
```

Opens your browser to DeepVista's login page. If you're already logged in, the CLI authenticates automatically via a localhost callback.

### Non-interactive / headless

Visit the web app at `/cli`, sign in, and paste the code shown:

```bash
deepvista auth login --code XXXX-XXXX
```

### Check / clear auth

```bash
deepvista auth status
deepvista auth logout
```

---

## Profiles

Profiles store `api_url` so you don't need env vars for each environment.

```bash
# Create profiles
deepvista config set local   --api-url http://localhost:8080
deepvista config set staging --api-url https://api-staging.deepvista.ai

# Use a profile
deepvista --profile local card list
deepvista --profile staging chat +send "hello" --new

# Manage
deepvista config list
deepvista config show local
deepvista config delete old
```

**Resolution order** (first wins): CLI flags → named profile → built-in default

---

## Commands

The CLI uses four resources:

```
card       Knowledge cards (all types)
skill      Executable workflows
vistabase  Implicit context from Chat (read-only)
chat       Conversational AI agent
```

> **Backward compatibility:** `deepvista memory` is a deprecated alias for `deepvista vistabase`.

### card — Knowledge cards

```bash
# List cards
deepvista card list [--type TYPE] [--status pinned|archived|normal] [--limit N] [--page N]

# Get / create / update / delete
deepvista card get    <card_id>
deepvista card create --type TYPE --title "Title" [--content "..."] [--tags '["t1"]']
deepvista card update <card_id> [--title "..."] [--content "..."] [--status pinned|archived]
deepvista card delete <card_id>

# Search (hybrid vector + keyword)
deepvista card +search "query text" [--type TYPE] [--limit 10]

# Find similar cards
deepvista card +similar <card_id>

# Pin / archive
deepvista card +pin     <card_id>
deepvista card +archive <card_id>
```

Card types: `person`, `organization`, `message`, `todo`, `topic`, `keypoint`, `file`, `note`, `skill`, `skill_run`

### skill — Executable workflows

```bash
deepvista skill list [--limit N] [--page N]
deepvista skill get    <skill_id>
deepvista skill run    <skill_id> [--input "context"]
deepvista skill status <run_chat_id>
deepvista skill export <skill_id> --format skill
```

`skill run` streams NDJSON as the agent works through the checklist.

### vistabase — Implicit context

Vistabase is automatically accumulated from Chat. It is read-only — updates happen through conversation.

```bash
deepvista vistabase show   [--limit N]
deepvista vistabase search "query text" [--limit N]
```

> `deepvista memory` is a deprecated alias that works identically.

### chat — AI agent

```bash
deepvista chat sessions [--limit N] [--offset N] [--search "query"]
deepvista chat get    <chat_id>
deepvista chat delete <chat_id>
deepvista chat +send  "your message" [--chat-id ID] [--new]
```

`chat +send` streams NDJSON as the agent responds.

### notes — Quick note management (shorthand)

`notes` is a convenience alias for `card` commands filtered to `type=note`.

```bash
deepvista notes list [--limit N]
deepvista notes get    <note_id>
deepvista notes create --title "Title" [--content "..."]
deepvista notes update <note_id> [--title "..."] [--content "..."]
deepvista notes delete <note_id>
deepvista notes +quick "Quick note from a single line of text"
```

---

## Global Flags

Global flags must come **before** the resource name:

```bash
# Correct
deepvista --profile local card list

# Wrong
deepvista card list --profile local
```

| Flag | Default | Description |
|------|---------|-------------|
| `--format json\|table` | `json` | Output format |
| `--verbose` | off | Show HTTP request/response details |
| `--dry-run` | off | Show what would be sent, don't execute |
| `--api-url URL` | `https://api.deepvista.ai` | Override backend URL |
| `--profile NAME` | `default` | Use a named config profile |
| `--version` | | Show version and exit |

---

## Output

- **JSON** (default): structured JSON to stdout — agents parse this.
- **Table**: `--format table` for human-readable output.
- **Errors**: `{"error": {"code": N, "message": "...", "detail": "..."}}` on stderr.
- **Streaming**: NDJSON for `chat +send` and `skill run` (one JSON object per line).

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | API error |
| 2 | Auth error (not logged in / token expired) |
| 3 | Validation error (bad arguments) |
| 4 | Network error |
| 5 | Internal error |

## Environment Variables

| Variable | Description |
|----------|-------------|
| `DEEPVISTA_CONFIG_DIR` | Config directory (default: `~/.config/deepvista`) |

---

## Files

```
deepvista-cli/
├── deepvista_cli/
│   ├── main.py              # CLI entry point (five resources)
│   ├── config.py            # Config + profiles
│   ├── auth/                # Login, token storage, callback server
│   ├── client/              # HTTP client, SSE streaming
│   ├── commands/
│   │   ├── card.py          # Knowledge cards
│   │   ├── skill.py         # Executable workflows
│   │   ├── memory.py        # Implicit memory context
│   │   ├── chat.py          # Conversational agent
│   │   ├── notes.py         # Notes (alias for card --type note)
│   │   ├── auth.py
│   │   └── config.py
│   ├── tui/
│   │   └── app.py           # Terminal UI (requires [ui] extra)
│   └── output/              # JSON + table formatters
└── skills/                  # SKILL.md files for agent integration
    ├── deepvista-shared/
    ├── deepvista-vistabase/     # card commands
    ├── deepvista-vistabook/     # skill commands
    ├── deepvista-vistabase/     # vistabase commands
    ├── deepvista-notes/
    ├── deepvista-chat/
    ├── deepvista-persona-knowledge-worker/
    ├── deepvista-skill-analyze-notes/
    ├── deepvista-skill-export-knowledge/
    └── deepvista-skill-research-to-skill/
```

## See Also

- [skills/](./skills/) — SKILL.md files for agent integration
- [deepvista.ai](https://deepvista.ai) — Web app to build and manage Skills
- [PyPI](https://pypi.org/project/deepvista-cli/) — Package releases
- [GitHub Issues](https://github.com/DeepVista-AI/deepvista-cli/issues) — Bug reports and feature requests
