<p align="center">
  <img src="https://raw.githubusercontent.com/DeepVista-AI/deepvista-cli/main/docs/assets/deepvista-banner.png" alt="DeepVista" width="600">
</p>

<h1 align="center">Turn Your Agents into a Self-Evolving Team</h1>

<p align="center">
  <strong>DeepVista CLI connects your coding agents to a shared knowledge base —<br>
    so they don’t just execute, but learn, remember, and build on past work.
  </strong>
</p>

<div align="center">

[![GitHub Stars](https://img.shields.io/github/stars/DeepVista-AI/deepvista-cli?style=social)](https://github.com/DeepVista-AI/deepvista-cli)
[![PyPI](https://img.shields.io/pypi/v/deepvista-cli?color=5B5BD6)](https://pypi.org/project/deepvista-cli/)
[![PyPI - Status](https://img.shields.io/pypi/status/deepvista-cli)](https://pypi.org/project/deepvista-cli/)
[![PyPI Downloads](https://static.pepy.tech/badge/deepvista-cli/month)](https://pepy.tech/projects/deepvista-cli)
[![License](https://img.shields.io/badge/license-Apache%202.0-5B5BD6)](https://www.apache.org/licenses/LICENSE-2.0)
[![skills.sh](https://img.shields.io/badge/skills.sh-DeepVista--AI-purple)](https://skills.sh/deepvista-ai/deepvista-cli)
[![GitHub Skills](https://img.shields.io/badge/gh%20skill-DeepVista--AI%2Fdeepvista--cli-181717)](https://github.com/DeepVista-AI/deepvista-cli)
[![Claude Code Plugin](https://img.shields.io/badge/Claude_Code-plugin-D97757?logo=anthropic)](https://docs.claude.com/en/docs/claude-code/plugins)

</div>

<br>

<p align="center">
⭐ If this direction resonates, consider <b>starring the repo</b> — it helps more people discover it.
</p>

<br>

---

## Who this is for

- Builders working with coding agents (Claude Code, Cursor, OpenCode)
- People experimenting with agent workflows and skills
- Anyone trying to turn scattered interactions into compounding knowledge

## What this enables

Modern coding agents are powerful — but each interaction is stateless and isolated.

DeepVista changes that.

- Agents **remember** past work
- Agents **share context** through a common knowledge base
- Agents **build on previous decisions and insights**

Over time, this turns isolated executions into a:

→ **a self-evolving team of agents that compound knowledge over time**


## Why DeepVista CLI?

Most knowledge tools trap your data in a GUI. DeepVista CLI gives you **full access to your knowledge base from the terminal** — and lets your AI agents use it too.

- 🧠 **Capture knowledge** — notes, insights, decisions — as you work
- 🔍 **Hybrid search** — vector + keyword across everything you've saved
- 🤖 **Agent-native** — Claude Code, Cursor, OpenCode use it as a skill
- 📋 **Run Skills** — execute structured AI workflows from the command line
- 💬 **Chat** — talk to the DeepVista AI agent in your terminal

## Related Ideas

This repo is part of a broader exploration of how agent skills are structured and executed.

If you're interested in:
- how different types of skills should be modeled
- how to handle stateless vs stateful execution
- how to make agent workflows more reliable

→ Read more: https://go.deepvista.ai/agent-skills-2d

---

## Quick Start

### One-line install

```bash
pip install deepvista-cli
```

Or with `uv` / `pipx`:

```bash
uv tool install deepvista-cli    # or: pipx install deepvista-cli
```

### Login and go

```bash
deepvista auth login              # opens browser
deepvista notes +quick "My first note from the terminal"
deepvista card +search "founder mindset"
deepvista chat +send "What did I learn last week?"
```

> **Tip:** `dv` is a short alias for `deepvista` — `dv <args>` and `deepvista <args>`
> are fully interchangeable (e.g. `dv notes +quick "..."`).

That's it. Your knowledge base is now accessible from any terminal.

---

## For AI Agents

<p>
  <img src="https://cdn.simpleicons.org/anthropic/000000" width="18" alt="Claude Code" />&nbsp; <strong>Claude Code</strong> &nbsp;&nbsp;
  <img src="https://cdn.simpleicons.org/cursor/000000" width="18" alt="Cursor" />&nbsp; <strong>Cursor</strong> &nbsp;&nbsp;
  <strong>OpenCode</strong> &nbsp;&nbsp;
  and any agent that supports skills
</p>

**Install once, then talk to your agent.** The agent handles authentication and all commands on your behalf.

### Claude Code (recommended)

Install the DeepVista plugin from inside Claude Code:

```
/plugin marketplace add DeepVista-AI/deepvista-cli
/plugin install deepvista@deepvista-ai
```

The plugin keeps your local skills directory in sync with the DeepVista
catalog on every `SessionStart`. It calls the `deepvista` CLI under the hood,
so make sure that's installed and logged in (`uv tool install deepvista-cli`
then `deepvista auth login`).

### For non-Claude-Code agents (Cursor, OpenCode, OpenClaw, …)

**macOS / Linux (bash):**

```bash
curl -sSL https://raw.githubusercontent.com/DeepVista-AI/deepvista-cli/main/install.sh | bash
```

**Windows (PowerShell):**

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://raw.githubusercontent.com/DeepVista-AI/deepvista-cli/main/install.ps1 | iex"
```

The script auto-detects your package manager (`uv`, `pipx`, or `pip`) and copies the consolidated `deepvista` skill into your agent's skill directory (Cursor, OpenCode, OpenClaw, and Claude Code as a fallback). If you upgraded from an earlier release, it also sweeps out the 12 legacy `deepvista-*` skills so you don't end up with both.

Prefer GitHub's CLI? `gh skill install DeepVista-AI/deepvista-cli` works too (GitHub CLI ≥ 2.90, preview).

#### Windows troubleshooting: `uv trampoline failed to canonicalize script path`

On Windows, running `deepvista` may fail with:

```
error: uv trampoline failed to canonicalize script path
```

This is a [known uv-on-Windows issue](https://github.com/astral-sh/uv/issues): the launcher (trampoline) that `uv tool install` creates can fail to resolve its own path. It is aggravated by working directories that contain **spaces** (e.g. `C:\Users\you\Claude Folder`) or are inside **OneDrive**-synced folders.

Fixes, in order of preference:

1. **Update uv and reinstall the launcher:**

   ```powershell
   uv self update
   uv tool install --reinstall "deepvista-cli"
   ```

2. **Run via `uv tool run` as a fallback** (bypasses the broken trampoline entirely):

   ```powershell
   uv tool run deepvista auth login
   uv tool run deepvista notes +quick "My first note"
   ```

3. **Avoid spaces / OneDrive in your working directory.** Run from a path without spaces, e.g. `C:\dev`, rather than `C:\Users\you\Claude Folder`.

The `install.ps1` script performs this check automatically: after installing it runs `deepvista --version`, and if it hits the trampoline error it falls back to `uv tool run deepvista` and prints the guidance above. It also adds `%USERPROFILE%\.local\bin` (uv's tool bin directory) to your user PATH if it isn't already there — restart your shell afterward so new terminals pick it up.

### Get Started

Open your agent and paste:

```
Help me get started with DeepVista. Walk me through logging in.
```

Your agent will open the browser login page, guide you through pasting the auth code, and confirm you're logged in.

> **Claude Code tip:** To skip skill file read confirmations:
> ```bash
> claude config set allowedPaths "~/.claude/skills" --global
> ```

### Auto-Capture

Auto-capture (silently saving notable facts, decisions, and insights to your
DeepVista knowledge base as you work) ships with the Claude Code plugin —
install it from inside Claude Code with `/plugin install deepvista@deepvista-ai`.

For Cursor / OpenCode / OpenClaw, the `deepvista` skill's reference docs
include the same capture prompts that you can paste into your agent's global
instructions file.

### Skill Reference

One skill, `deepvista`, with per-subcommand detail under `skills/deepvista/reference/`.

| Reference file | What it covers |
|-------|---------------------------|
| `reference/shared.md` | Auth, profiles, global flags, exit codes, agent registration |
| `reference/notes.md` | Note capture, CRUD, `+quick` |
| `reference/vistabase-card.md` | Knowledge-base cards (`card` / `vistabase`) — create, search, pin, edit, grep |
| `reference/session.md` | Agent session transcripts — init, tick, finalize |
| `reference/chat.md` | Chat sessions and NDJSON stream format |
| `reference/skill.md` | Structured Skill workflows — list, run, phase, complete |
| `reference/skill-create-from-note.md` | Synthesize a Skill from one or more notes |
| `reference/skill-analyze-notes.md` | Pattern: search → read → synthesize notes |
| `reference/skill-research-to-skill.md` | Pattern: research the KB, then run a Skill |
| `reference/skill-import-files.md` | Bulk-import a folder as file cards |
| `reference/tasks.md` | Run work dispatched to this machine — `tasks run` / `setup` |
| `reference/openclaw.md` | Auto-capture rules for OpenClaw agents |

The agent loads only the index at first; when a subcommand is needed, it reads the matching reference file on demand.

---

## Use Cases

### 🎧 Capture Insights from Podcasts

Build a searchable knowledge base from founder interviews:

```
I just listened to the Lenny's Podcast episode with Brian Chesky about founder mode.
Save this to my knowledge base as a note titled "Brian Chesky — Founder Mode".
```

### 🔬 Research and Synthesize

Once you've captured 10–20 notes, ask your agent to find patterns:

```
Search for cards about growth and early-stage execution,
then run my Research Synthesis skill focused on:
what separates high-growth founders, common 0→1 mistakes.
```

### 📘 Build a Founder Playbook

```
I have a new startup idea to evaluate. Idea: [your idea].
1. Search my knowledge base for any idea validation frameworks
2. Find my idea evaluation Skill
3. Run it with the above context
```

Export as a reusable, shareable skill:

```
Export my founder playbook Skill as a SKILL.md file so I can share it with my team.
```

### More Skill Patterns

| Skill | How to invoke |
|-------|---------------|
| **Research synthesis** | "Search my KB for [topic] and run my Research Synthesis Skill" |
| **Weekly review** | "Run my weekly review — surface pinned cards and capture key learnings" |
| **Interview debrief** | "I just finished a user interview. Run my Interview Debrief Skill" |
| **Decision memo** | "Help me think through this decision using my knowledge base" |
| **Competitive analysis** | "Run a competitive analysis on [company/space] using everything I've captured" |

---

## Commands

Primary resources:

```
deepvista card       # Knowledge cards (all types) — alias: `vistabase`
deepvista skill      # Executable workflows
deepvista chat       # Conversational AI agent
deepvista notes      # Hand-written notes (cards with type=note)
```

Supporting commands:

```
deepvista agents     # Agent identity heartbeat (auto-registers on first sync)
deepvista session    # Agent conversation transcripts (init / tick / finalize)
deepvista tasks      # Run work dispatched to this machine (task cards, queued commands)
deepvista schedule   # Manage the recurring daily-planning job (opt-in)
deepvista auth       # Authenticate with DeepVista
deepvista config     # Manage CLI profiles (local, staging, production, …)
deepvista upgrade    # Check for and install CLI + skill updates
```

### card — Knowledge cards

```bash
deepvista card list [--type TYPE] [--status pinned|archived|normal] [--limit N]
deepvista card get <card_id>
deepvista card create --type TYPE --title "Title" [--content "..."] [--tags '["t1"]']
deepvista card update <card_id> [--title "..."] [--content "..."]
deepvista card delete <card_id>
deepvista card +search "query text" [--type TYPE] [--limit 10]
deepvista card +similar <card_id>
deepvista card +pin <card_id>
deepvista card +archive <card_id>
```

Card types: `person` · `organization` · `message` · `email` · `todo` · `topic` · `keypoint` · `file` · `note` · `session` · `skill` · `run_log` · `schedule_job` · `task` · `conversation_starter` · `artifact`

> `note` is reserved for human-authored notes; `artifact` is the agent's fallback for its own output when no structured type fits (DV-1573).

> `deepvista vistabase` is a backward-compatible alias for `deepvista card` — every `card` subcommand works under `vistabase` too.

### skill — Executable workflows

```bash
deepvista skill list [--limit N]
deepvista skill get <skill_id>
deepvista skill run <skill_id> [--input "context"]
deepvista skill phase open <skill_id> "Phase N: <title>"
deepvista skill phase done <skill_id> "Phase N: <title>" [--artifact-card-id ID]... [--next-phase "Phase N+1: …"]
deepvista skill phase pause <skill_id> --reason "<short sentence>"
deepvista skill complete <skill_id> --review "<retrospective bullets>"
```

`skill run` prints a JSON header + the workflow's SKILL.md body + a host runtime contract on stdout, and the host agent (Claude Code / OpenClaw / Cursor) drives the run via the `phase` shims and `complete`.

### chat — AI agent

```bash
deepvista chat sessions [--limit N] [--offset N] [--search "query"]
deepvista chat get <chat_id>
deepvista chat delete <chat_id>
deepvista chat +send "your message" [--chat-id ID] [--new]   # streams NDJSON
```

### notes — Quick note management

Convenience alias for `card` commands filtered to `type=note`.

```bash
deepvista notes list [--limit N]
deepvista notes get <note_id>
deepvista notes create --title "Title" [--content "..."]
deepvista notes update <note_id> [--title "..."] [--content "..."]
deepvista notes delete <note_id>
deepvista notes +quick "Quick note from a single line of text"
```

### session — Agent transcripts

A rolling context card that captures one agent run — created on SessionStart, ticked per turn, finalized on Stop.

```bash
deepvista session init <session_id>
deepvista session tick <session_id>
deepvista session finalize <session_id>
```

### tasks — Work dispatched to this machine

Polls for work assigned to this machine's agents and runs task cards headless via `claude -p`.

```bash
deepvista tasks list
deepvista tasks run [--run-once] [--poll-interval N] [--total-time N] [--max-parallel N]
deepvista tasks note <task_id> "<progress note>"
deepvista tasks clean [--dry-run] [<task_id>...]
deepvista tasks setup [--interval N] [--remove]   # install/remove a polling crontab entry
```

### schedule — Recurring daily-planning job

```bash
deepvista schedule list
deepvista schedule activate
deepvista schedule deactivate
deepvista schedule delete <job_id>
```

Run `deepvista <command> --help` for the full options of any group, including `agents`, `auth`, `config`, and `upgrade`. Auth, profiles, and the agent heartbeat are also covered in `skills/deepvista/reference/shared.md`.

---

## Install Options

### From PyPI

```bash
pip install deepvista-cli
pipx install deepvista-cli
uv tool install deepvista-cli
```

### From GitHub

```bash
pip install git+https://github.com/DeepVista-AI/deepvista-cli.git
uv tool install git+https://github.com/DeepVista-AI/deepvista-cli.git
```

### As a Claude Code plugin (recommended for Claude Code users)

The plugin is the canonical way to use DeepVista from Claude Code. It wires the
DeepVista skill catalog into Claude Code on every `SessionStart` and ships the
auto-capture hook. Install in this order:

```bash
# 1. Install the CLI (required — the plugin calls it)
uv tool install deepvista-cli    # or: pip install deepvista-cli
deepvista auth login

# 2. Then, inside Claude Code:
#    /plugin marketplace add DeepVista-AI/deepvista-cli
#    /plugin install deepvista@deepvista-ai
```

Without the CLI on `PATH`, the plugin's SessionStart hook exits silently —
you'll see no errors but no skills either.

### For development

```bash
uv sync
uv pip install -e .
uv run deepvista --help
```

### Uninstall

```bash
curl -sSL https://raw.githubusercontent.com/DeepVista-AI/deepvista-cli/main/uninstall.sh | bash
```

Removes the CLI, all skills from agent directories, and auto-capture blocks from config files.

---

## Authentication

```bash
deepvista auth login                   # opens browser (default)
deepvista auth login --code XXXX-XXXX  # headless / non-interactive
deepvista auth status                  # check current auth
deepvista auth logout                  # clear tokens
```

For headless environments, visit the web app at `/cli`, sign in, and paste the code.

## Profiles

```bash
deepvista config set local   --api-url http://localhost:8080
deepvista config set staging --api-url https://api-staging.deepvista.ai
deepvista --profile local card list
deepvista config list
```

Resolution order (first wins): CLI flags → named profile → built-in default

## Global Flags

| Flag | Default | Description |
|------|---------|-------------|
| `--format json\|table` | `json` | Output format |
| `--verbose` | off | Show HTTP request/response details |
| `--dry-run` | off | Show what would be sent, don't execute |
| `--api-url URL` | `https://api.deepvista.ai` | Override backend URL |
| `--profile NAME` | `default` | Use a named config profile |
| `--version` | | Show version and exit |

> Global flags must come **before** the resource name: `deepvista --profile local card list`

---

## Reference

<details>
<summary><strong>Output Format</strong></summary>

- **JSON** (default): structured JSON to stdout — agents parse this
- **Table**: `--format table` for human-readable output
- **Errors**: `{"error": {"code": N, "message": "...", "detail": "..."}}` on stderr
- **Streaming**: NDJSON for `chat +send` and `skill run` (one JSON object per line)

</details>

<details>
<summary><strong>Exit Codes</strong></summary>

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | API error |
| 2 | Auth error (not logged in / token expired) |
| 3 | Validation error (bad arguments) |
| 4 | Network error |
| 5 | Internal error |

</details>

<details>
<summary><strong>Environment Variables</strong></summary>

| Variable | Description |
|----------|-------------|
| `DEEPVISTA_CONFIG_DIR` | Config directory (default: `~/.config/deepvista`) |

</details>

<details>
<summary><strong>Project Structure</strong></summary>

```
deepvista-cli/
├── deepvista_cli/
│   ├── main.py              # CLI entry point
│   ├── config.py            # Config + profiles
│   ├── auth/                # Login, token storage, callback server
│   ├── client/              # HTTP client, SSE streaming
│   ├── commands/            # card, skill, chat, notes, agents, session, tasks, schedule, auth, config, upgrade
│   └── output/              # JSON + table formatters
└── skills/                  # SKILL.md files for agent integration
```

</details>

---

## 🤝 Contributing

We welcome contributions! Whether it's bug reports, feature requests, documentation updates, or code — open an [issue](https://github.com/DeepVista-AI/deepvista-cli/issues) or submit a PR.

## 👥 Community

- 🌟 [Star us on GitHub](https://github.com/DeepVista-AI/deepvista-cli) — helps us grow
- 🐛 [Report issues](https://github.com/DeepVista-AI/deepvista-cli/issues)
- 📦 [PyPI package](https://pypi.org/project/deepvista-cli/)
- 🌐 [DeepVista Web App](https://deepvista.ai)

---

## Support Us

If you find DeepVista CLI useful, please ⭐ **star this repo** — it helps more people discover it!

[![GitHub Stars](https://img.shields.io/github/stars/DeepVista-AI/deepvista-cli?style=social)](https://github.com/DeepVista-AI/deepvista-cli)

## License

DeepVista CLI is open source. See [LICENSE](./LICENSE) for details.
