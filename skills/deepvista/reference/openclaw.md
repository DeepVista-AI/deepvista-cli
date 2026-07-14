# OpenClaw — auto-capture notable facts as context cards

OpenClaw is DeepVista's companion agent. The auto-capture rule saves notable user
statements to DeepVista **as context cards** without asking for confirmation on
every capture — the opposite of other write commands in this skill.

**Notes are human-driven, context cards are agent-driven.** A `note`
(`type=note`) is only ever created when the user explicitly asks to save or
write a note (see [notes.md](notes.md)) — never by auto-capture. Everything
OpenClaw notices on its own during a conversation is a context card of some
other `--type` (DV-1484). Auto-capture must never call `deepvista notes` —
use `deepvista card create` exclusively.

Use when the user is running OpenClaw (or another agent with this rule installed)
and expects captures to happen silently in the background.

## When to capture (no confirmation)

Save anything in these categories automatically, as the indicated card `--type`:

- **Personal or professional facts** (role, company, team, background) — `--type person`
  (or `--type organization` for company-level facts).
- **Decisions reached** — include the reasoning if the user stated it. `--type keypoint`.
- **Key insights / learnings / observations.** `--type keypoint`.
- **Action items / commitments / deadlines.** `--type todo`.
- **Meeting or conversation highlights** — use bullets; include participants. `--type topic`.
- **Relationships** — who works with whom, reporting lines, collaborations. `--type person`
  (or `--type organization`).

If a statement doesn't clearly fit one of these, prefer `--type keypoint` as the
default catch-all rather than reaching for `--type note`.

## When NOT to capture

- Passwords, API keys, tokens, credentials of any kind.
- Pure questions ("how do I …", "what's the status of …").
- Small talk / greetings / confirmations.
- Agent commands directed at the assistant itself ("run this", "stop", "retry").
- Anything the user explicitly asks you not to save.
- **Anything the user explicitly asks to be saved as a note** — that's a `note`,
  route it to [notes.md](notes.md) instead (still an explicit write, confirm as normal).

When in doubt, err on the side of not capturing and let the user prompt you.

## Capture commands

Single-line fact:

```bash
deepvista card create --type <type> --title "<short title>" --content "<exact user statement or tight paraphrase>"
```

- Preserve original wording when practical. Paraphrase only to fix pronouns
  (`I` → `<user name>`) or clarify who a referent is.
- Keep `--title` short (first ~50 chars of the statement is a good budget) —
  there's no length validation on `card create` the way `notes +quick` has.

Structured fact (multi-line, or when the user shares formatted content):

```bash
deepvista card create --type <type> \
  --title "<short title>" \
  --content-file <path>
```

For content dictated in-conversation, write it to a tempfile first:

```bash
cat > /tmp/capture-$$.md <<'EOF'
<markdown content here>
EOF
deepvista card create --type <type> --title "…" --content-file /tmp/capture-$$.md
rm /tmp/capture-$$.md
```

## Prerequisites

Check authentication before the first capture of a session:

```bash
deepvista auth status
```

If unauthenticated, prompt the user to run `deepvista auth login` — don't try to
capture silently into a broken auth state.

## Optional — heartbeat

If the user runs `deepvista agents sync --type openclaw` once (it auto-registers
on first run), the CLI will heartbeat after each agent turn. Set up is one-time;
not required for capture to work.

## Duplicate captures (DV-1367)

The server blocks exact/near-duplicate person and organization cards at write
time (title match or high embedding similarity creates an update instead of a
new card), but that's a safety net, not a substitute for good capture
discipline — it can still miss a duplicate that's phrased differently enough.
When capturing a person or organization, prefer
`deepvista card +search "<name>" --type person` (or `--type organization`)
first and reuse an existing card instead of creating a new one for the same
entity. Any duplicates that do slip through can be resolved later via
Vistabase's manual "Merge duplicate" card action — there is no automatic
background cleanup (yet).

## See also

- [vistabase-card.md](vistabase-card.md) — the underlying `card create` command and full `--type` list
- [notes.md](notes.md) — explicit, human-requested notes (never auto-captured)
- [shared.md](shared.md) — auth, agent registration
