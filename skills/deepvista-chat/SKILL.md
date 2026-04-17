---
name: deepvista-chat
description: "DeepVista Chat: Send messages to the AI agent and manage chat sessions."
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
    cliHelp: "deepvista chat --help"
---

# Chat


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

Chat with the DeepVista AI agent. The agent can search your knowledge base, create cards, run web searches, and execute tools.

## Commands

### sessions

```bash
deepvista chat sessions [--limit N] [--offset N] [--search "query"]
```

Read-only — list chat sessions.

### get

```bash
deepvista chat get <chat_id>
```

Read-only — returns session metadata (`id`, `summary`, `created_at`, `status`). Full message history is not returned by this endpoint.

### delete

```bash
deepvista chat delete <chat_id>
```

> [!CAUTION] Destructive command — confirm with user before executing.

### +send

```bash
deepvista chat +send "your message" [--chat-id ID] [--new]
```

> [!CAUTION]
> This is a **write** command — creates/updates chat sessions and the agent may create cards, search the web, and take other actions. Confirm with the user before executing.

| Flag | Required | Default | Description |
|------|----------|---------|-------------|
| `<message>` | Yes | — | Your message to the agent |
| `--chat-id` | No | — | Continue an existing chat session |
| `--new` | No | false | Force start a new conversation |

Output is **NDJSON** — one JSON object per line, streamed as the agent responds.

## SSE Event Format

`+send` streams events in this structure. Parse `page_delta` events to get the agent's response text:

```json
{"type": "chat_session", "id": "abc123", ...}
{"type": "page", "page": {"user_instruction": "...", ...}}
{"type": "page_delta", "parts": [
  {"type": "tool_result", "output": "partial response text...", "done": false}
], "page_index": 0}
{"type": "page_delta", "parts": [
  {"type": "tool_result", "output": "full response text", "done": true, "options": ["follow-up 1", "follow-up 2"]}
]}
```

Key fields:
- `type: "chat_session"` — first event; contains the `id` of the session
- `type: "page_delta"` — carries the streamed response
- `parts[].type: "tool_result"` — the agent's text; `output` is the **full accumulated text so far** (not an incremental delta)
- `parts[].done: true` — final chunk; `options` may contain suggested follow-up prompts

## Examples

```bash
# Send a message (new conversation)
deepvista chat +send "What are my open tasks?" --new

# Continue an existing conversation
deepvista chat +send "Tell me more about the first one" --chat-id abc123

# Ask the agent to create a note
deepvista chat +send "Create a note summarizing our ML strategy discussion"

# List recent sessions
deepvista chat sessions --limit 5

# Search sessions by summary
deepvista chat sessions --search "roadmap"
```

## See Also

- [deepvista-shared](../deepvista-shared/SKILL.md) — Auth and global flags
- [deepvista-vistabase](../deepvista-vistabase/SKILL.md) — View implicit context accumulated from Chat
