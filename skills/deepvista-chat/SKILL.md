---
name: deepvista-chat
description: "DeepVista Chat: Send messages to the AI agent and manage chat sessions."
metadata:
  deepvista:
    category: "service"
    requires:
      bins:
        - uv
      skills:
        - deepvista-shared
    cliHelp: "deepvista chat --help"
---

# Chat

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

Read-only — get a chat session with all pages.

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

Output is NDJSON (one JSON object per line) — each line is an SSE event from the agent's streaming response.

- Use `--new` to force a fresh conversation context.
- Without `--chat-id` or `--new`, the agent may auto-select or create a session.
- The agent has access to your full knowledge base and can create/update cards during the conversation.

## Examples

```bash
# Send a message (new conversation)
deepvista chat +send "What are my open tasks?" --new

# Continue an existing conversation
deepvista chat +send "Tell me more about the first one" --chat-id chat_abc

# Ask the agent to create a note
deepvista chat +send "Create a note summarizing our ML strategy discussion"

# List recent sessions
deepvista chat sessions --limit 5

# Search sessions
deepvista chat sessions --search "roadmap"
```

## See Also

- [deepvista-shared](../deepvista-shared/SKILL.md) — Auth and global flags
