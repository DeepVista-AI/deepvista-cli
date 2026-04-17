# Changelog

All notable changes to `deepvista-cli` and its bundled skills are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Sections are ordered newest first — `deepvista upgrade` reads this file to show
users what's new between the version they have installed and the latest release.

## Unreleased

### Added
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

### Changed
- Every shipped skill now has an `## On Load` preamble that runs
  `deepvista upgrade check` once per hour so agents can react to new releases
  without blocking on the network.

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
