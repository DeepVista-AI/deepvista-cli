# Session — agent conversation transcripts

`deepvista session` is the dedicated CLI surface for recording an agent run
as a rolling context card (`type=session`). Distinct from:

- **`notes`** — explicit user-authored knowledge.
- **`card`**  — incidental info recorded mid-conversation.

Run `deepvista session --help` or `deepvista session <cmd> --help` for full
flag reference.

## Commands

`init` · `tick` · `finalize`

> [!CAUTION] All three are write commands. `init` creates a card on first
> call; `tick` and `finalize` update it. Safe to invoke from hook scripts
> (`SessionStart`, `Stop`, `SessionEnd`).

## Lifecycle

1. **`session init`** — idempotent. Creates a card with
   `type=session` keyed by the agent's session id, tagged `cc-session:<id>`,
   `agent:<type>`, and `project:<dir>`. Caches the card id locally at
   `$XDG_STATE_HOME/deepvista/sessions/<session_id>.json`. Safe to call on
   every `SessionStart`.
2. **`session tick`** — parses the transcript JSONL, extracts turns past
   the cached `last_turn_index`, appends a summary block per turn, and bumps
   the frontmatter `turn_count` / `version`. The update is tagged
   `reason="session-tick"` so version history stays readable.
3. **`session finalize`** — flips `status: complete` in the frontmatter and
   queues enrichment via `/index_notes`. Pair with the optional final
   `--transcript` flush.

Existing rolling notes created by `deepvista notes session-*` (pre-DV-742,
`type=note`) are still recovered on `init` (legacy-tag fallback) so an
in-flight session keeps ticking through the new commands.

## Examples

```bash
# SessionStart hook
deepvista session init \
  --session-id "$CLAUDE_SESSION_ID" \
  --transcript "$CLAUDE_TRANSCRIPT_PATH" \
  --cwd "$PWD"

# Stop hook
deepvista session tick \
  --session-id "$CLAUDE_SESSION_ID" \
  --transcript "$CLAUDE_TRANSCRIPT_PATH"

# SessionEnd hook
deepvista session finalize --session-id "$CLAUDE_SESSION_ID"
```

## Skipping nested sub-agent sessions

`session init` short-circuits when `--cwd` matches any pattern in
`session_skip_cwd_patterns` (a top-level list in
`~/.config/deepvista/config.json`). This stops the SessionStart hook from
recording sub-agent sessions whose CWD is not a real working directory — e.g.
**claude-mem's observer sub-claude** runs with
`cwd=~/.claude-mem/observer-sessions` and only quotes file paths from the
*primary* session; recording it pollutes the vistabase with bogus File cards.

Defaults skip `*/.claude-mem/observer-sessions[/*]`. Patterns are
fnmatch-style Unix shell globs (`*` matches across `/`). To override, edit
`~/.config/deepvista/config.json` by hand — add a top-level
`session_skip_cwd_patterns` list. An explicit empty list disables skipping.

```jsonc
{
  "default": { "api_url": "https://api.deepvista.ai" },
  "session_skip_cwd_patterns": [
    "*/.claude-mem/observer-sessions",
    "*/.claude-mem/observer-sessions/*",
    "*/scratchpad/*"
  ]
}
```

When a session is skipped, `init` emits
`{"skipped": true, "reason": "cwd matches session_skip_cwd_patterns", ...}`
and creates no card. Downstream `tick` / `finalize` self-no-op because no
card was cached (exit 3 "Unknown session", silenced by the hook scripts).

## See also

- [notes.md](notes.md) — explicit user-authored knowledge.
- [vistabase-card.md](vistabase-card.md) — generic card CRUD (`--type person|todo|…`).
