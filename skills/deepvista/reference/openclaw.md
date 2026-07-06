# OpenClaw — auto-capture notable facts

OpenClaw is DeepVista's companion agent. The auto-capture rule saves notable user
statements to DeepVista without asking for confirmation on every capture — the
opposite of other write commands in this skill.

Use when the user is running OpenClaw (or another agent with this rule installed)
and expects captures to happen silently in the background.

## When to capture (no confirmation)

Save anything in these categories automatically:

- **Personal or professional facts** — role, company, team, background.
- **Decisions reached** — include the reasoning if the user stated it.
- **Key insights / learnings / observations.**
- **Action items / commitments / deadlines.**
- **Meeting or conversation highlights** — use bullets; include participants.
- **Relationships** — who works with whom, reporting lines, collaborations.

## When NOT to capture

- Passwords, API keys, tokens, credentials of any kind.
- Pure questions ("how do I …", "what's the status of …").
- Small talk / greetings / confirmations.
- Agent commands directed at the assistant itself ("run this", "stop", "retry").
- Anything the user explicitly asks you not to save.

When in doubt, err on the side of not capturing and let the user prompt you.

## Capture commands

Single-line fact:

```bash
deepvista notes +quick "<exact user statement or tight paraphrase>"
```

- Preserve original wording when practical. Paraphrase only to fix pronouns
  (`I` → `<user name>`) or clarify who a referent is.
- The first ~50 chars become the title.

Structured fact (multi-line, or when the user shares formatted content):

```bash
deepvista notes create \
  --title "<short title>" \
  --content-file <path>
```

For content dictated in-conversation, write it to a tempfile first:

```bash
cat > /tmp/capture-$$.md <<'EOF'
<markdown content here>
EOF
deepvista notes create --title "…" --content-file /tmp/capture-$$.md
rm /tmp/capture-$$.md
```

## Prerequisites

Check authentication before the first capture of a session:

```bash
deepvista auth status
```

If unauthenticated, prompt the user to run `deepvista auth login` — don't try to
capture silently into a broken auth state.

## Optional — heartbeat / dedup

If the user runs `deepvista agents sync --type openclaw` once (it auto-registers
on first run), the CLI will heartbeat after each agent turn and the server will
flag near-duplicate captures during periodic maintenance. Set up is one-time;
not required for capture to work.

## See also

- [notes.md](notes.md) — the underlying `+quick` and `create` commands
- [shared.md](shared.md) — auth, agent registration
