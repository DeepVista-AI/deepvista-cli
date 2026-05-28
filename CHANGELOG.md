# Changelog

All notable changes to `deepvista-cli` and its bundled skills are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Sections are ordered newest first — `deepvista upgrade` reads this file to show
users what's new between the version they have installed and the latest release.

## Unreleased

### Added
- **Managed agents become Claude Code subagents** (DV-836). New `deepvista
  agents export` turns each distinct managed-agent role (DV-832 `agent_role`)
  into a Claude Code plugin agent definition, so roles are callable inline —
  e.g. `@marketing summarize this week`. The plugin's `SessionStart` hook
  (`deepvista-sync.sh`, which also runs the skill-catalog sync) writes one
  `dv-<role>.md` per role into `${CLAUDE_PLUGIN_ROOT}/agents/`, mirroring the
  skill-catalog sync: idempotent, throttled, and safe (exits 0 on any
  failure). Generated files carry an
  `x-deepvista-agent` marker and a `dv-` prefix so they are gitignored and
  hand-curated agents of the same name always win. The `misc` default role is
  skipped. Tunable via `DEEPVISTA_AGENT_SYNC_THROTTLE_MIN` / `_LIMIT`.
- **Custom agent system prompts** (DV-836). `agents register` / `agents update`
  accept `--system-prompt-file`, storing the contents as the agent's
  `config.soul`. When set, `agents export` bakes that prompt in as the generated
  subagent's body (verbatim); the role-template body is the fallback when no soul
  is set. Frontmatter (routing, tools, model, preloaded `deepvista` skill) stays
  templated either way.

### Fixed
- **Agent registration is now self-healing** (DV-751). `deepvista agents
  sync` (the Claude Code Stop hook) auto-registers an agent on the first run
  if none exists locally, so SOUL / MEMORY pushes start working without a
  separate `agents register` step after `auth login`. If the backend reports
  `AGENT_NOT_FOUND` for a stale local agent_id, the CLI clears the local
  record, re-registers, and retries the sync once. `agents register` now
  adopts a pre-existing server-side row instead of failing when the local
  file is missing.

## [0.1.18](https://github.com/DeepVista-AI/deepvista-cli/compare/v0.1.17...v0.1.18) (2026-05-28)


### Documentation

* add CONTRIBUTING.md covering PR workflow and the release-please prose trap ([#145](https://github.com/DeepVista-AI/deepvista-cli/issues/145)) ([a9012d9](https://github.com/DeepVista-AI/deepvista-cli/commit/a9012d9cf45de695c754a0c89deb3f80e63e8b48))

## [0.1.17](https://github.com/DeepVista-AI/deepvista-cli/compare/v0.1.16...v0.1.17) (2026-05-28)


### Miscellaneous Chores

* verify release-please pipeline ([#142](https://github.com/DeepVista-AI/deepvista-cli/issues/142)) ([70fdc62](https://github.com/DeepVista-AI/deepvista-cli/commit/70fdc62b7ee4e511cb180a8c45a14a3f9f1b88ac))

## v0.1.11

### Added
- **Host-mode workflow execution for `skill run`** (DV-694). New
  `--mode {host,deepvista,auto}` flag, defaulting to `host`. Host mode prints
  a structured run packet (header + workflow SKILL.md body + host-mode
  runtime contract) on stdout so the host agent (Claude Code / OpenClaw /
  Cursor) drives the workflow itself via the new `skill phase
  {open,done,pause,run-on-deepvista}` shims and `skill complete`. Deepvista
  mode preserves today's `/imagine` behaviour. Auto mode inspects each
  phase's `tool_plan` and routes server-routable phases to `/imagine` while
  keeping the rest host-local. Phase shims mutate the parent Skill card's
  description directly via `/update_context_card`, so the server-side schema
  is unchanged.
- **`skills-refresh` lint check** (DV-724). New
  `deepvista lint --check skills-refresh --time-range <duration>` mode that
  folds recently-updated notes into the workflow skill library — updating
  existing skills and creating new ones where warranted. Accepts
  `<int><s|m|h|d|w>` durations (e.g. `30m`, `4h`, `1d`, `2w`) and emits a
  deterministic ISO-8601 UTC cutoff to the agent. Excluded from `--check
  all` (write-intensive) and gated behind the `--fix`-style confirmation
  prompt unless `-y` is passed.

### Fixed
- **`vistabase` URL in skill docs uses path-based routing** (DV-703).
  Switched the documented URL form to the path-based scheme to match the
  rest of the CLI's URL output.

### Changed
- **`skill create-from-note` drops the `persona` kind** (DV-750). The server-side
  persona maker (`deepvista-make-persona-skill`) was removed in #2022, so the
  CLI no longer offers `persona` as a `--kind`. `--kind workflow` is the only
  remaining choice (still repeatable, default). The trigger phrase emitted by
  the CLI is now always *"Create a workflow skill from this note."* and the
  chat agent routes it to `deepvista-skill-workflow`. The `skills-refresh` lint
  check (DV-724) drops its persona-candidate branch for the same reason.

### Removed
- `skills/deepvista/reference/persona-knowledge-worker.md` — the underlying
  `deepvista-persona-knowledge-worker` skill was removed from the backend in
  #2022 (DV-695), so the routing pointer in the consolidated `deepvista`
  skill no longer leads anywhere useful. Daily-loop guidance is still
  discoverable through the per-subcommand reference files.

## v0.1.10

### Changed
- **`skill create-from-note` delegates prompt to the server** (DV-585). The
  ~150-line synthesis prompt previously embedded in
  `deepvista_cli/commands/skill.py` is gone; the CLI now emits only
  `<contextCard>` chips plus a short trigger phrase
  (`"Create a persona skill and a workflow skill from this note."`). The chat
  agent matches the phrase against the existing server-side
  `deepvista-make-persona-skill` / `deepvista-make-workflow-skill` SKILL.md
  files, which are now the single source of truth for frontmatter rules,
  mermaid requirements, and `upsert_context_card` instructions. Same UX, no
  more drift between client and server prompts.

### Added
- **Session-scoped conversation notes** (DV-449 M1/M2). One rolling DeepVista
  note per Claude Code session, updated every conversation turn with
  heuristic per-turn summaries. Frontmatter records agent, project dir, git
  branch/commit, turn count, and version. New subcommands:
  `deepvista notes session-init` (idempotent create-or-get by session_id),
  `session-tick` (append newest turn, bump version), `session-finalize`
  (mark complete, queue enrichment). Three shell hooks for Claude Code:
  `hooks/deepvista-session-{start,turn,end}.sh` — non-blocking, silent
  fallback when the CLI is missing.
- **Version history for notes** (DV-449 M2). `deepvista notes history`
  lists prior versions, `notes diff <id> <a> <b>` shows a unified diff,
  `notes restore <id> <version>` rolls back (itself reversible). Backed by
  the server-side `context_card_versions` audit table that captures every
  note update via trigger.
- **Session-note lookup uses server-side `tag_contains`** instead of
  client-side scan of recent notes — O(1) resolution of
  `cc-session:<session_id>` tag via the existing `/get_context_cards`
  filter.

## v0.1.2

### Changed
- **Skill pack collapsed to one consolidated `deepvista` skill** (DV-385, issue #75
  follow-up). Replaces the 12 top-level `deepvista-*` skills with a single
  `skills/deepvista/` directory: an index `SKILL.md` that covers every trigger
  phrase, plus per-subcommand detail under `skills/deepvista/reference/*.md`
  (13 files). Agents load the index first and pull the matching reference file on
  demand. `install.sh` removes the legacy `deepvista-*` directories on upgrade so
  users don't end up with both.

### Removed
- 12 legacy per-subcommand skill directories (`deepvista-chat`, `deepvista-notes`,
  `deepvista-openclaw`, `deepvista-persona-knowledge-worker`, `deepvista-shared`,
  `deepvista-skill`, `deepvista-skill-analyze-notes`, `deepvista-skill-export-knowledge`,
  `deepvista-skill-import-files`, `deepvista-skill-research-to-skill`,
  `deepvista-vistabase`, `deepvista-vistabase-card`). All content preserved under
  the consolidated skill.
- `INSTALL_PROMPT.md` — unreferenced and drifting (still mentioned
  `deepvista-vistabook` after the rename). The install flow is already documented
  in `README.md` and `install.sh`.
- Stale ClawHub and MIT license references from `README.md` and `CLAUDE.md` (license
  has been Apache-2.0 for a while; ClawHub publish was removed in #78).


## v0.1.1

First non-alpha release. Graduates from `0.1.0aN` (PEP 440 alpha) to a plain
semver. No `0.1.0` stable was ever published to PyPI — the jump is intentional
to keep the PyPI version and the git `v0.1.0` artifact (which was tagged at the
a24 commit and only exists on GitHub) from colliding.

- Auto-update flow for the CLI and bundled skills, modeled after `gstack`
  (DV-378). Skills now run `deepvista upgrade check` when they load; if a newer
  version is on PyPI, the agent is instructed to tell the user and offer to
  install it. New subcommands:
  - `deepvista upgrade check` — fast cached check (exit 1 when an update is
    available) for agent preambles. Emits `UPGRADE_AVAILABLE <old> <new>` on
    stdout.
  - `deepvista upgrade install` — interactive upgrade that fetches the
    changelog between the installed and latest versions and summarizes what's
    new before asking for confirmation.
  - `deepvista upgrade snooze` — defer the nag with escalating backoff
    (1d → 2d → 7d).
  - `deepvista upgrade disable` / `enable` — hard opt-out.
  - `deepvista upgrade status` — show cached state.
- `CHANGELOG.md` at the repo root — read by `upgrade install` to render
  release notes to users and agents.
- Every shipped skill now has an `## On Load` preamble that runs
  `deepvista upgrade check` once per hour so agents can react to new releases
  without blocking on the network.

## v0.1.0a27

### Added
- GitHub skills publishing via `gh skill publish` (issue #75). Release workflow
  now creates a semver-tagged GitHub Release (e.g. `v0.1.0a27` → `v0.1.0-alpha.27`)
  so skills install with `gh skill install deepvista/deepvista-cli@v0.1.0-alpha.27`.
  Agent Skills spec compliance is validated on every PR via
  `gh skill publish --dry-run` in CI.

### Removed
- ClawHub publish step from the release workflow.

## v0.1.0a23

- Agent control plane CLI commands (DV-368).

## v0.1.0a22

- Renamed `recipe` to `skill` across the CLI (DV-360).

## v0.1.0a21

- Minor fixes and README polish.

## v0.1.0a20

- Badges in README for PyPI, ClawHub, and skills.sh.
- Fix: prevent `Not a directory` error in install script.
- Fix: add URL to wrapped entity responses (DV-292).

## v0.1.0a19

- OpenClaw auto-capture support.
- Display URL instead of ID in CLI output.
- Origin metadata sent with `/imagine` requests (DV-257).
- Switched to path-based routing for URLs.

## v0.1.0a18 and earlier

See the Git history for pre-CHANGELOG releases:
<https://github.com/DeepVista-AI/deepvista-cli/commits/main>.
