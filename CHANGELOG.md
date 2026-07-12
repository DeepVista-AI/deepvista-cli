# Changelog

All notable changes to `deepvista-cli` and its bundled skills are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Sections are ordered newest first — `deepvista upgrade` reads this file to show
users what's new between the version they have installed and the latest release.

## Unreleased

### Changed
- **Machine identity is project-scoped** — uniqueness is
  `(project_id, machine_fingerprint)`. Local cache:
  `machines/<fingerprint>__<project_id>.json`. Same device in two projects →
  two Machine rows. Project members can see teammate Machines; only the
  registering user syncs/claims. `agent_role` is not sent on register;
  `agent_type` is soft `last_seen_tool`. Adopting `AGENT_ALREADY_REGISTERED`
  requires a matching fingerprint.

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

## [3.1.0](https://github.com/DeepVista-AI/deepvista-cli/compare/v3.0.0...v3.1.0) (2026-07-12)


### Features

* project-scoped Machines (fingerprint + project_id) ([#197](https://github.com/DeepVista-AI/deepvista-cli/issues/197)) ([07da470](https://github.com/DeepVista-AI/deepvista-cli/commit/07da470d324ed2779bbc047b9032775bfa3c8d5b))

## [3.0.0](https://github.com/DeepVista-AI/deepvista-cli/compare/v2.0.0...v3.0.0) (2026-07-11)


### Miscellaneous Chores

* release 3.0.0 ([#195](https://github.com/DeepVista-AI/deepvista-cli/issues/195)) ([d1c99e0](https://github.com/DeepVista-AI/deepvista-cli/commit/d1c99e0196a779f9eb4b3416db0be089287394b3))

## [2.0.0](https://github.com/DeepVista-AI/deepvista-cli/compare/v1.2.0...v2.0.0) (2026-07-06)


### ⚠ BREAKING CHANGES

* simplify the CLI surface (84 → 69 commands, −1,470 lines) ([#189](https://github.com/DeepVista-AI/deepvista-cli/issues/189))

### Features

* **DV-1428:** stream task-card execution incrementally, report live progress ([#185](https://github.com/DeepVista-AI/deepvista-cli/issues/185)) ([7f081b5](https://github.com/DeepVista-AI/deepvista-cli/commit/7f081b598085d52280fb84c4396d573672b6cb5a))
* **DV-1429:** tasks clean, auto-detect agent --type, prune stale agents ([#183](https://github.com/DeepVista-AI/deepvista-cli/issues/183)) ([38252e7](https://github.com/DeepVista-AI/deepvista-cli/commit/38252e71b33275bc7976037192a082c7f2ccb391))
* run task queue jobs in parallel (max 5) ([#193](https://github.com/DeepVista-AI/deepvista-cli/issues/193)) ([b22a727](https://github.com/DeepVista-AI/deepvista-cli/commit/b22a7275a59aef3e69896846a86ddfb263d43a24))
* simplify the CLI surface (84 → 69 commands, −1,470 lines) ([#189](https://github.com/DeepVista-AI/deepvista-cli/issues/189)) ([5056442](https://github.com/DeepVista-AI/deepvista-cli/commit/50564429a84ff044967cab8db831e282b5fac67b))


### Bug Fixes

* **tasks:** use single-quoted f-string to avoid escaped double quotes in task note hint ([#181](https://github.com/DeepVista-AI/deepvista-cli/issues/181)) ([297de78](https://github.com/DeepVista-AI/deepvista-cli/commit/297de78ee188cd9dcd9b4031b5b29b76733b160d))


### Documentation

* **DV-1434:** fix schedule command docstring to reference schedule_job cards ([#182](https://github.com/DeepVista-AI/deepvista-cli/issues/182)) ([d01f98d](https://github.com/DeepVista-AI/deepvista-cli/commit/d01f98d03a21256ee96ee4cae8b78f81c4b44a85))

## [1.2.0](https://github.com/DeepVista-AI/deepvista-cli/compare/v1.1.0...v1.2.0) (2026-06-27)


### Features

* **DV-1324:** add dv CLI alias ([#177](https://github.com/DeepVista-AI/deepvista-cli/issues/177)) ([f1973a3](https://github.com/DeepVista-AI/deepvista-cli/commit/f1973a35b488477df187ff2ccb5c0662b2f3efa8))

## [1.1.0](https://github.com/DeepVista-AI/deepvista-cli/compare/v1.0.0...v1.1.0) (2026-06-26)


### Features

* **DV-1277:** clean session-card title + link task runs to their chat ([#169](https://github.com/DeepVista-AI/deepvista-cli/issues/169)) ([b4de0c7](https://github.com/DeepVista-AI/deepvista-cli/commit/b4de0c7435bf89f475a25443e80524ab1da8420a))
* **skill:** add phase need-input for :::dvNeedIntervention mermaid state ([#166](https://github.com/DeepVista-AI/deepvista-cli/issues/166)) ([ade6edf](https://github.com/DeepVista-AI/deepvista-cli/commit/ade6edf8a462199ce8b59119e7eb0d662ad94fc6))


### Bug Fixes

* **DV-1357:** move agent heartbeat into the Claude Code plugin ([#174](https://github.com/DeepVista-AI/deepvista-cli/issues/174)) ([41c4339](https://github.com/DeepVista-AI/deepvista-cli/commit/41c43390afaab06c90c103c5526e44f3f3f35ad8))
* reconcile _ensure_agents_for_projects return type (pyright) ([#173](https://github.com/DeepVista-AI/deepvista-cli/issues/173)) ([c134e42](https://github.com/DeepVista-AI/deepvista-cli/commit/c134e42abc39325cf2814126be7d249ba667f464))

## [1.0.0](https://github.com/DeepVista-AI/deepvista-cli/compare/v0.6.0...v1.0.0) (2026-06-25)


### ⚠ BREAKING CHANGES

* **DV-1281:** CLI help/docs cleanup — drop deprecated aliases, remove TUI, collapse vistabase into card ([#167](https://github.com/DeepVista-AI/deepvista-cli/issues/167))

### Features

* **DV-1247:** `tasks` group runs web-chat task cards via claude -p ([#165](https://github.com/DeepVista-AI/deepvista-cli/issues/165)) ([4c95aed](https://github.com/DeepVista-AI/deepvista-cli/commit/4c95aedb99104f3567b10e1d77f8c3b668627177))
* **DV-1281:** CLI help/docs cleanup — drop deprecated aliases, remove TUI, collapse vistabase into card ([#167](https://github.com/DeepVista-AI/deepvista-cli/issues/167)) ([b7f308b](https://github.com/DeepVista-AI/deepvista-cli/commit/b7f308be5a03421c9b08eab1622209a94826b72d))
* **DV-1294:** make the CLI a project-scoped client ([#170](https://github.com/DeepVista-AI/deepvista-cli/issues/170)) ([708d107](https://github.com/DeepVista-AI/deepvista-cli/commit/708d10739aa0ccf11319379a76fdea6cf646c493))

## [0.6.0](https://github.com/DeepVista-AI/deepvista-cli/compare/v0.5.0...v0.6.0) (2026-06-22)


### Features

* **DV-1079:** poll by default in task_queue run with single-instance lock ([#162](https://github.com/DeepVista-AI/deepvista-cli/issues/162)) ([eef464e](https://github.com/DeepVista-AI/deepvista-cli/commit/eef464e3ab6cb1591130b79903238a1a7327bc61))


### Documentation

* add direct import path for downloaded skill markdown files ([#160](https://github.com/DeepVista-AI/deepvista-cli/issues/160)) ([31b35b9](https://github.com/DeepVista-AI/deepvista-cli/commit/31b35b9608e75759547d1bb803cc04b3bed2fea1))

## [0.5.0](https://github.com/DeepVista-AI/deepvista-cli/compare/v0.4.0...v0.5.0) (2026-06-04)


### Features

* **DV-936:** task_queue run/list/setup commands ([#155](https://github.com/DeepVista-AI/deepvista-cli/issues/155)) ([0d90691](https://github.com/DeepVista-AI/deepvista-cli/commit/0d9069106d14068d657e16415be80dec95f12085))

## [0.4.0](https://github.com/DeepVista-AI/deepvista-cli/compare/v0.3.0...v0.4.0) (2026-06-03)


### Features

* **DV-941:** add windows install script and trampoline troubleshooting docs ([#156](https://github.com/DeepVista-AI/deepvista-cli/issues/156)) ([eed7335](https://github.com/DeepVista-AI/deepvista-cli/commit/eed7335ffdc1dfcfd84523ed0e77be066b7fe9c3))
* **DV-942:** print next-step hints after auth login ([#157](https://github.com/DeepVista-AI/deepvista-cli/issues/157)) ([0fca6c9](https://github.com/DeepVista-AI/deepvista-cli/commit/0fca6c9309623ee690c2c9e16870d528b558fd80))

## [0.3.0](https://github.com/DeepVista-AI/deepvista-cli/compare/v0.2.0...v0.3.0) (2026-05-31)


### Features

* **DV-871:** move daily-planning to server; add schedule command ([#151](https://github.com/DeepVista-AI/deepvista-cli/issues/151)) ([7c317e7](https://github.com/DeepVista-AI/deepvista-cli/commit/7c317e7d6f71763f6622354b8581ead8b10ef8ea))


### Bug Fixes

* **types:** mark output_error as NoReturn to fix Pyright errors in schedule.py ([#153](https://github.com/DeepVista-AI/deepvista-cli/issues/153)) ([7ac8b12](https://github.com/DeepVista-AI/deepvista-cli/commit/7ac8b12f1b10a94cd6dbe8533b122a2cf8489228))

## [0.2.0](https://github.com/DeepVista-AI/deepvista-cli/compare/v0.1.18...v0.2.0) (2026-05-28)


### Features

* **DV-853:** productionize the deepvista subagents ([#147](https://github.com/DeepVista-AI/deepvista-cli/issues/147)) ([45e9ba1](https://github.com/DeepVista-AI/deepvista-cli/commit/45e9ba17de08243fe84be3de6826c72116360351))
* **session:** skip session init for configured CWD patterns (DV-862) ([#148](https://github.com/DeepVista-AI/deepvista-cli/issues/148)) ([df74381](https://github.com/DeepVista-AI/deepvista-cli/commit/df743810ae6dec7c4a520c43d82f1eeae421762b))

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
