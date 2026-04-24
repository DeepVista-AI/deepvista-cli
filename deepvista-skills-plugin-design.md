# DeepVista Skills Plugin — Tech Design (v2)

Status: draft · Last updated: 2026-04-24

## Goal

Distribute the DeepVista remote skill catalog to Claude Code (and, with minimal glue, opencode / Cursor / Codex / any agent that reads `~/.claude/skills/`) so that users always have an up-to-date, discoverable catalog of named skills without manual install steps per skill.

Two orthogonal needs:

1. **Discovery** — the agent and user must *see* the catalog (name + description) without invoking anything.
2. **Freshness** — skill *bodies* must reflect the server's current state at invocation time, not at install time.

## Non-goals

- Real-time skill registry mutation mid-response (Claude Code's live change detector handles file-level updates, but we don't need sub-turn latency).
- Replacing or masking user-authored skills in `~/.claude/skills/`.
- Authoring skills locally — the catalog is server-managed.
- Building a generic skill marketplace — DeepVista server is the single source.

## Background: what we verified (April 2026)

The v1 draft of this doc made two incorrect assumptions that this revision fixes.

| Claim in v1 | Reality |
|---|---|
| SessionStart hook writes are snapshotted out; skills appear next session only. | **False.** Claude Code has live change detection — adding, editing, or removing a `SKILL.md` under `~/.claude/skills/`, a project `.claude/skills/`, or an `--add-dir` skills dir is picked up within the current session. The only restart case is first-time creation of the skills root dir. |
| Write catalog files into `${CLAUDE_PLUGIN_ROOT}/skills/`. | **Risky.** Plugins installed from a marketplace are git-cached and auto-updated by default; hook-written files inside the plugin root can be clobbered on the next update pull. We write catalog state to `~/.claude/skills/deepvista-catalog/` instead, outside any plugin root. |

Other relevant facts that shape the design:

- **Lazy body loading works natively.** Claude Code skill bodies support `` !`shell command` `` preprocessing: the command is executed at skill-invocation time (not registration time) and its stdout replaces the placeholder before the body is sent to the model. We exploit this: stubs carry name + description only; the real body is fetched at invocation by `deepvista skill load <name>`.
- **SessionStart hooks support `type: command` and `type: mcp_tool` only** — a shell-out is fine.
- **An empty SKILL.md body is not sufficient.** Frontmatter alone doesn't make a skill invokable; the body carries the instructions. Our stubs therefore ship a minimal body (the lazy-load directive + an instruction fallback).
- **MCP prompts are not a fit.** They don't appear in `/skills` UI in Claude Code; opencode exposes MCP *tools* only (not prompts); Cursor's prompt UX has known bugs. Filesystem `SKILL.md` tree is the most portable unit today.
- **Cross-agent compatibility is cheap.** Both opencode (v1.0.190+) and Cursor (v2.4+) explicitly read `~/.claude/skills/` and `~/.agents/skills/` alongside their native paths. Writing stubs once to `~/.claude/skills/deepvista-catalog/` covers Claude Code, opencode, Cursor, and Codex simultaneously.

## Design

### Three layers

```
┌────────────────────────────────────────────────────────────────┐
│ Layer 1 — Base manpage skill (static, always-on)              │
│   ~/.agents/skills/deepvista/       <- primary                 │
│   ~/.claude/skills/deepvista/       <- symlink for back-compat │
│   Installed by: `deepvista init` (or pip/uv post-install)      │
│                                                                │
│ Layer 2 — Catalog stubs (dynamic, refreshed each session)     │
│   ~/.claude/skills/deepvista-catalog/<name>/SKILL.md           │
│   Frontmatter: name + description (+ license)                  │
│   Body: `!\`deepvista skill load <name>\``                     │
│   Refreshed by: `deepvista skill sync --stubs`                 │
│                                                                │
│ Layer 3 — Claude Code plugin (thin glue for auto-refresh)     │
│   plugin.json + hooks/hooks.json (SessionStart → sync)         │
│   commands/refresh-skills.md (manual `/refresh-skills`)        │
│   Installed by: `/plugin install deepvista@<marketplace>`      │
└────────────────────────────────────────────────────────────────┘
```

Layer 1 is the DeepVista CLI's own manpage — a single consolidated skill that already exists in-repo under `skills/deepvista/` with per-subcommand reference files under `skills/deepvista/reference/*.md`. This skill is what tells the agent how to *use* the CLI itself.

Layer 2 is the per-skill remote catalog — thin stubs, one dir per skill, each stub fetches its own body at invocation time.

Layer 3 is the only Claude-Code-specific piece. It exists solely to fire `deepvista skill sync --stubs` on `SessionStart`. Users on opencode get an equivalent plugin (`session.created` hook). Users on Cursor / Codex run `deepvista skill sync` from a cron job or shell init.

### Layer 1 — Base manpage skill

Already shipped. Installed via `deepvista init`, which:

1. Writes the consolidated skill to `~/.agents/skills/deepvista/` (neutral path).
2. Creates symlinks `~/.claude/skills/deepvista` → `~/.agents/skills/deepvista` and `~/.cursor/skills/deepvista` → same, for agents that don't yet read the neutral path.
3. Is idempotent: re-running upgrades the copy in `~/.agents/skills/deepvista/`.

The existing `~/.claude/skills/deepvista/` on developer machines is replaced by the symlink on `deepvista init`.

No plugin needed for this layer. Every agent that reads any of `{~/.agents, ~/.claude, ~/.cursor, ~/.codex}/skills/` gets the manpage.

### Layer 2 — Catalog stubs

Stub layout:

```
~/.claude/skills/deepvista-catalog/
├── .last_sync              # unix timestamp of last successful sync
├── .catalog.json           # snapshot of server response for diffing
├── <skill-name>/
│   └── SKILL.md            # stub: frontmatter + lazy-load directive
└── ...
```

Stub file (`SKILL.md`):

```markdown
---
name: deepvista-catalog-<skill-name>
description: <description from server, ≤200 chars>
license: Apache-2.0
---

<!-- DeepVista remote skill. Body is fetched at invocation time. -->

!`deepvista skill load <skill-name>`

<!--
If the !-preprocessor is not supported by this agent (e.g. older opencode),
run `deepvista skill load <skill-name>` and follow the printed instructions.
-->
```

Why a `deepvista-catalog-` name prefix: it namespaces catalog skills away from the user's own skills in the same dir, and makes intent obvious in `/skills` UI.

Why a comment fallback: for agents that don't process `` !`cmd` `` preprocessing (and for defensive behaviour when `deepvista` is not on PATH in a given sandboxed session), a Claude model reading the body will still follow the plain-English instruction to run the command.

### Layer 3 — Claude Code plugin

```
deepvista-plugin/
├── plugin.json
├── hooks/
│   └── hooks.json           # SessionStart → scripts/sync.sh
├── scripts/
│   └── sync.sh              # wraps `deepvista skill sync --stubs`
├── commands/
│   └── refresh-skills.md    # /refresh-skills slash command
└── README.md
```

`plugin.json`:

```json
{
  "name": "deepvista",
  "version": "0.1.0",
  "description": "Remote-managed skill catalog from DeepVista",
  "author": "DeepVista"
}
```

`hooks/hooks.json`:

```json
{
  "hooks": {
    "SessionStart": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "${CLAUDE_PLUGIN_ROOT}/scripts/sync.sh"
          }
        ]
      }
    ]
  }
}
```

`scripts/sync.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

STUB_DIR="$HOME/.claude/skills/deepvista-catalog"
LOG_FILE="$HOME/.deepvista/logs/sync.log"
MAX_AGE_MINUTES=60

mkdir -p "$STUB_DIR" "$(dirname "$LOG_FILE")"

# Throttle: skip if synced recently
if [ -f "$STUB_DIR/.last_sync" ]; then
  last=$(stat -f %m "$STUB_DIR/.last_sync" 2>/dev/null \
       || stat -c %Y "$STUB_DIR/.last_sync")
  now=$(date +%s)
  age=$(( (now - last) / 60 ))
  if [ "$age" -lt "$MAX_AGE_MINUTES" ]; then
    exit 0
  fi
fi

# Never fail the session on sync error. Stubs from the previous sync are still usable.
if command -v deepvista >/dev/null 2>&1; then
  deepvista skill sync --stubs \
    --target "$STUB_DIR" \
    --limit 30 \
    --quiet >>"$LOG_FILE" 2>&1 \
    && touch "$STUB_DIR/.last_sync" \
    || true
else
  echo "[$(date -u +%FT%TZ)] deepvista CLI not on PATH, skipping" >>"$LOG_FILE"
fi

exit 0
```

`commands/refresh-skills.md`:

```markdown
---
description: Force resync of the DeepVista catalog (stubs only)
---

Run `${CLAUDE_PLUGIN_ROOT}/scripts/sync.sh` but force a sync even if throttled
(`DEEPVISTA_FORCE_SYNC=1`). Report the number of added / updated / removed stubs.
Tell the user the catalog is now live in the current session (live change
detection picks up new SKILL.md files immediately).
```

## CLI changes required

Two new subcommands. Both thin wrappers over existing HTTP client (`deepvista_cli/client/http.py`).

### `deepvista skill sync`

```
deepvista skill sync [--stubs | --full] [--target <dir>] [--limit N] [--dry-run] [--quiet]
```

- `--stubs` (default): write thin stubs (frontmatter + lazy-load directive). Fast, small.
- `--full`: fetch full SKILL.md bodies. For offline use.
- `--target`: install dir. Default `~/.claude/skills/deepvista-catalog/`.
- `--limit`: cap number of skills (honours server ordering: pinned → recent).
- `--dry-run`: compute diff vs on-disk catalog, print summary, exit.
- Idempotent: writes `.catalog.json` snapshot, diffs against it, adds/updates/removes stubs.

Server endpoint: reuses `/get_context_cards` (already called by `skill list` per `deepvista_cli/commands/skill.py:51`). May add server-side `limit` / `pinned_only` filter for the "top N" use case.

### `deepvista skill load <name>`

```
deepvista skill load <name> [--format skill-md|text]
```

- Prints the full SKILL.md body for a named catalog skill to stdout.
- Used by stub bodies at invocation time.
- Cached locally with short TTL (~5 min) to avoid thundering-herd when the same skill is invoked repeatedly in a session.
- Server endpoint: `/get_context_card` (single card fetch, already used by `skill get`).

### `deepvista init`

Extend existing init (if present) or add:

- Installs Layer 1 manpage skill to `~/.agents/skills/deepvista/`.
- Symlinks into `~/.claude/skills/` and `~/.cursor/skills/`.
- Optionally registers a first-time sync by running `deepvista skill sync --stubs`.
- Prints instructions for plugin install (`/plugin install ...`) or shell-init hook (for non-plugin agents).

## Session lifecycle (Claude Code)

1. User starts `claude`.
2. Plugin manifests load. Skill registry scans `~/.claude/skills/` (picks up existing catalog + base manpage) and `${CLAUDE_PLUGIN_ROOT}/skills/` (empty — plugin ships no skills of its own).
3. `SessionStart` hooks fire. `scripts/sync.sh` → `deepvista skill sync --stubs`.
4. Sync writes/updates/removes stub dirs under `~/.claude/skills/deepvista-catalog/`.
5. **Live change detection** picks up the new stubs in the current session — no restart, no one-session lag.
6. User invokes a catalog skill by name.
7. Claude reads the stub SKILL.md → `` !`deepvista skill load <name>` `` runs → full body is injected into context → Claude executes.

## Failure modes

| Failure | Behaviour |
|---|---|
| Network down at SessionStart | `sync.sh` exits 0; previous sync's stubs still live. |
| `deepvista` CLI not on PATH | `sync.sh` logs, exits 0. Layer 1 manpage (if already installed) still works. |
| User not authenticated | CLI writes empty catalog, logs auth hint. `/refresh-skills` after `deepvista auth login` recovers. |
| Corrupt / partial SKILL.md | Claude Code skips invalid entries; other stubs load. Sync recomputes on next run. |
| Server removed a skill | Sync deletes the stub dir. Live change detection removes it from registry. |
| `skill load` fails at invocation time | Preprocessor output is an error string; model sees the fallback comment and reports to user. |
| Plugin auto-update clobbers plugin files | Catalog is outside the plugin root → unaffected. Plugin code update is safe (only hook/slash files). |

## Freshness & throttling

- Default throttle: 60 min since last `.last_sync` timestamp. Tunable via env (`DEEPVISTA_SYNC_THROTTLE_MIN`).
- Forced sync bypasses throttle (`DEEPVISTA_FORCE_SYNC=1` or `/refresh-skills`).
- Body cache (for `skill load`) TTL: 5 min. Stored at `~/.deepvista/cache/bodies/<hash>.md`.
- No hot-reload of the skill registry itself is needed — live change detection handles it.

## Cross-agent compatibility

| Agent | Layer 1 path | Layer 2 path | Layer 3 (auto-refresh) |
|---|---|---|---|
| Claude Code | `~/.claude/skills/deepvista/` (symlink) | `~/.claude/skills/deepvista-catalog/` | Plugin + SessionStart hook |
| opencode | `~/.agents/skills/deepvista/` (native) or `~/.claude/skills/deepvista/` (compat) | `~/.claude/skills/deepvista-catalog/` (compat) or `~/.agents/skills/deepvista-catalog/` | Separate opencode plugin w/ `session.created` hook |
| Cursor | `~/.agents/skills/deepvista/` or `~/.claude/skills/deepvista/` (v2.4+ compat) | `~/.claude/skills/deepvista-catalog/` | Cron / shell init calls `deepvista skill sync` |
| Codex | `~/.codex/skills/deepvista/` (+ `~/.claude/skills/` compat) | `~/.codex/skills/deepvista-catalog/` | Cron / shell init |
| Generic | `~/.agents/skills/deepvista/` | `~/.agents/skills/deepvista-catalog/` | `deepvista skill sync` in `~/.profile` |

`deepvista init --target <agent>` writes the right symlinks and prints the right auto-refresh recipe per target.

## Distribution

- **Local dev:** clone → `/plugin install /path/to/deepvista-plugin`
- **Marketplace:** publish to `DeepVista-AI/deepvista-marketplace`; users install via `/plugin install deepvista@deepvista-marketplace`
- **CLI manpage skill + CLI itself:** `uv pip install deepvista-cli` (or PyPI `pip install`), then `deepvista init` installs Layer 1.
- **opencode plugin:** parallel repo `DeepVista-AI/deepvista-opencode` or directory `plugins/opencode/` in this repo.

## Security

- `sync.sh` writes only inside `~/.claude/skills/deepvista-catalog/` and `~/.deepvista/`.
- Catalog fetched over HTTPS via existing DeepVista auth (Bearer JWT, `X-DeepVista-Origin` metadata).
- Lazy-loaded bodies flow through the same auth. Body cache is keyed by skill ID + content hash.
- No arbitrary code execution beyond what any skill body declares — the trust boundary is exactly "DeepVista server is trusted to ship skill bodies," which is identical to any plugin skill trust model.
- Users can audit the live body with `deepvista skill load <name>` before invoking.

## Open questions

1. **Body caching policy.** 5 min TTL, or no cache (always fetch)? Cache makes repeated invocation fast; no cache maximises freshness. Recommend 5 min with cache-bust via `/refresh-skills`.
2. **Per-user filtering.** Server-side via `/get_context_cards` filters (role, team, pinned-only), or client-side via plugin config? Recommend server-side — honours existing auth scope.
3. **"Top N" heuristic.** Server ordering (pinned → most-used → most-recent)? Configurable via `--order` flag? For v1, server default + `--limit 30` is enough.
4. **Stub body fallback when `!cmd` is unsupported.** Current design includes a plain-instruction comment; acceptable?
5. **`~/.agents/skills/` as primary.** Neutral path, but Claude Code doesn't natively read it (needs symlink). Recommend writing to `~/.claude/skills/` as the physical location (it's the one every agent reads) and making `~/.agents/skills/` a symlink, *not* the other way around — inverts what Layer 1 does above. Revisit.
6. **Versioning of stubs.** Include server's `updated_at` in stub frontmatter so users can see staleness? Low cost, high signal.

## Implementation plan (rough)

Phase 1 — CLI plumbing (blocks everything else)
- [ ] Add `deepvista skill sync` (subcommand + HTTP client method).
- [ ] Add `deepvista skill load`.
- [ ] Extend `deepvista init` to write Layer 1 symlinks.
- [ ] Tests: sync diff logic, stub format, load cache.

Phase 2 — Claude Code plugin
- [ ] `plugins/claude-code/` dir in this repo with `plugin.json`, `hooks/hooks.json`, `scripts/sync.sh`, `commands/refresh-skills.md`.
- [ ] Marketplace manifest.
- [ ] Smoke test: fresh machine → `/plugin install` → stubs appear in `/skills`.

Phase 3 — cross-agent
- [ ] `plugins/opencode/` with `session.created` hook.
- [ ] Docs: cron recipe for Cursor / Codex.
- [ ] `deepvista init --target opencode|cursor|codex` wiring.

Phase 4 — polish
- [ ] Body-cache TTL config.
- [ ] `--dry-run` for sync.
- [ ] `updated_at` in stub frontmatter.
- [ ] Server: `limit` / `pinned_only` on `/get_context_cards` if not already.
