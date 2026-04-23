# Changelog

All notable changes to `deepvista-cli` and its bundled skills are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Sections are ordered newest first — `deepvista upgrade` reads this file to show
users what's new between the version they have installed and the latest release.

## Unreleased

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
