# Chat — send messages to the DeepVista AI agent

The agent can search the knowledge base, create cards, run web searches, and call
tools. Run `deepvista chat --help` or `deepvista chat <cmd> --help` for full flag
reference.

## Commands

`sessions` · `get` · `delete` · `+send`

## Agent conventions

> [!CAUTION] `+send` may cause the agent to create cards and write to vistabase.
> Confirm first. `delete` is destructive — confirm first.

Read-only: `sessions`, `get`.

## NDJSON event format (non-obvious)

`+send` streams one JSON object per line. Key fields to parse:

```json
{"type": "chat_session", "id": "abc123"}
```
First event — save `id` to continue the conversation later.

```json
{"type": "page_delta", "parts": [
  {"type": "tool_result", "output": "full text so far", "done": false}
]}
```
`output` is the **full accumulated text**, not an incremental delta. Diff against the
previous `output` to print only new content, or just overwrite.

```json
{"type": "page_delta", "parts": [
  {"type": "tool_result", "output": "final text", "done": true,
   "options": ["follow-up 1", "follow-up 2"]}
]}
```
`done: true` = final chunk. `options` may contain suggested follow-ups.

## Examples

```bash
# New conversation
deepvista chat +send "What are my open tasks?" --new

# Continue
deepvista chat +send "Tell me more about the first one" --chat-id abc123

# Search sessions
deepvista chat sessions --search "roadmap"
```

## See also

- [skill.md](skill.md) — `skill run` is a structured variant of `chat +send`
