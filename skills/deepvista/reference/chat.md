# Chat — send messages to the DeepVista AI agent

The agent can search the user's knowledge base, create cards, run web searches, and
call tools. All output on write streams as NDJSON.

## Commands

### `sessions` — read-only

```bash
deepvista chat sessions [--limit N] [--offset N] [--search "query"]
```

List chat sessions. `--search` matches on the session summary.

### `get` — read-only

```bash
deepvista chat get <chat_id>
```

Returns session metadata (`id`, `summary`, `created_at`, `status`). Full message
history is not included by this endpoint — use the app UI or `+send --chat-id` to
continue the conversation.

### `delete` — destructive

> [!CAUTION] Destructive. Confirm first.

```bash
deepvista chat delete <chat_id>
```

### `+send` — write

> [!CAUTION] Sends a message. The agent may create cards, call tools, and write to
> vistabase. Confirm first.

```bash
deepvista chat +send "your message" [--chat-id ID] [--new]
```

| Flag | Required | Default | Purpose |
|---|---|---|---|
| `<message>` | yes | — | Text to send |
| `--chat-id ID` | no | — | Continue an existing session |
| `--new` | no | `false` | Force a new session (ignore any cached `--chat-id`) |

## NDJSON event format

`+send` streams events as the agent responds. One JSON object per line.

```json
{"type": "chat_session", "id": "abc123", ...}
{"type": "page", "page": {"user_instruction": "...", ...}}
{"type": "page_delta", "parts": [
  {"type": "tool_result", "output": "partial response text...", "done": false}
], "page_index": 0}
{"type": "page_delta", "parts": [
  {"type": "tool_result", "output": "full response text", "done": true,
   "options": ["follow-up 1", "follow-up 2"]}
]}
```

Key fields:

- `type: "chat_session"` — first event; save `id` for continuation.
- `type: "page_delta"` → `parts[].type: "tool_result"` — the agent's text.
  `output` is the **full accumulated text so far**, not an incremental delta.
- `parts[].done: true` — final chunk. `options` may contain suggested follow-ups.

Agents parsing the stream should diff against the previous `output` to print only the
new portion, or just overwrite on each event.

## Examples

```bash
# New conversation
deepvista chat +send "What are my open tasks?" --new

# Continue
deepvista chat +send "Tell me more about the first one" --chat-id abc123

# Ask the agent to create a note
deepvista chat +send "Create a note summarizing our ML strategy discussion"

# List / search
deepvista chat sessions --limit 5
deepvista chat sessions --search "roadmap"
```

## See also

- [vistabase.md](vistabase.md) — chat is the only write path into implicit memory
- [skill.md](skill.md) — `skill run` is a structured variant of `chat +send`
