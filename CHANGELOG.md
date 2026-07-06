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

## [1.0.0](https://github.com/DeepVista-AI/deepvista-cli/compare/v0.1.17...v1.0.0) (2026-07-06)


### ⚠ BREAKING CHANGES

* simplify the CLI surface (84 → 69 commands, −1,470 lines) ([#189](https://github.com/DeepVista-AI/deepvista-cli/issues/189))
* **DV-1281:** CLI help/docs cleanup — drop deprecated aliases, remove TUI, collapse vistabase into card ([#167](https://github.com/DeepVista-AI/deepvista-cli/issues/167))

### Features

* **DV-1079:** poll by default in task_queue run with single-instance lock ([#162](https://github.com/DeepVista-AI/deepvista-cli/issues/162)) ([eef464e](https://github.com/DeepVista-AI/deepvista-cli/commit/eef464e3ab6cb1591130b79903238a1a7327bc61))
* **DV-1247:** `tasks` group runs web-chat task cards via claude -p ([#165](https://github.com/DeepVista-AI/deepvista-cli/issues/165)) ([4c95aed](https://github.com/DeepVista-AI/deepvista-cli/commit/4c95aedb99104f3567b10e1d77f8c3b668627177))
* **DV-1277:** clean session-card title + link task runs to their chat ([#169](https://github.com/DeepVista-AI/deepvista-cli/issues/169)) ([b4de0c7](https://github.com/DeepVista-AI/deepvista-cli/commit/b4de0c7435bf89f475a25443e80524ab1da8420a))
* **DV-1281:** CLI help/docs cleanup — drop deprecated aliases, remove TUI, collapse vistabase into card ([#167](https://github.com/DeepVista-AI/deepvista-cli/issues/167)) ([b7f308b](https://github.com/DeepVista-AI/deepvista-cli/commit/b7f308be5a03421c9b08eab1622209a94826b72d))
* **DV-1294:** make the CLI a project-scoped client ([#170](https://github.com/DeepVista-AI/deepvista-cli/issues/170)) ([708d107](https://github.com/DeepVista-AI/deepvista-cli/commit/708d10739aa0ccf11319379a76fdea6cf646c493))
* **DV-1324:** add dv CLI alias ([#177](https://github.com/DeepVista-AI/deepvista-cli/issues/177)) ([f1973a3](https://github.com/DeepVista-AI/deepvista-cli/commit/f1973a35b488477df187ff2ccb5c0662b2f3efa8))
* **DV-1428:** stream task-card execution incrementally, report live progress ([#185](https://github.com/DeepVista-AI/deepvista-cli/issues/185)) ([7f081b5](https://github.com/DeepVista-AI/deepvista-cli/commit/7f081b598085d52280fb84c4396d573672b6cb5a))
* **DV-1429:** tasks clean, auto-detect agent --type, prune stale agents ([#183](https://github.com/DeepVista-AI/deepvista-cli/issues/183)) ([38252e7](https://github.com/DeepVista-AI/deepvista-cli/commit/38252e71b33275bc7976037192a082c7f2ccb391))
* **DV-853:** productionize the deepvista subagents ([#147](https://github.com/DeepVista-AI/deepvista-cli/issues/147)) ([45e9ba1](https://github.com/DeepVista-AI/deepvista-cli/commit/45e9ba17de08243fe84be3de6826c72116360351))
* **DV-871:** move daily-planning to server; add schedule command ([#151](https://github.com/DeepVista-AI/deepvista-cli/issues/151)) ([7c317e7](https://github.com/DeepVista-AI/deepvista-cli/commit/7c317e7d6f71763f6622354b8581ead8b10ef8ea))
* **DV-936:** task_queue run/list/setup commands ([#155](https://github.com/DeepVista-AI/deepvista-cli/issues/155)) ([0d90691](https://github.com/DeepVista-AI/deepvista-cli/commit/0d9069106d14068d657e16415be80dec95f12085))
* **DV-941:** add windows install script and trampoline troubleshooting docs ([#156](https://github.com/DeepVista-AI/deepvista-cli/issues/156)) ([eed7335](https://github.com/DeepVista-AI/deepvista-cli/commit/eed7335ffdc1dfcfd84523ed0e77be066b7fe9c3))
* **DV-942:** print next-step hints after auth login ([#157](https://github.com/DeepVista-AI/deepvista-cli/issues/157)) ([0fca6c9](https://github.com/DeepVista-AI/deepvista-cli/commit/0fca6c9309623ee690c2c9e16870d528b558fd80))
* **session:** skip session init for configured CWD patterns (DV-862) ([#148](https://github.com/DeepVista-AI/deepvista-cli/issues/148)) ([df74381](https://github.com/DeepVista-AI/deepvista-cli/commit/df743810ae6dec7c4a520c43d82f1eeae421762b))
* simplify the CLI surface (84 → 69 commands, −1,470 lines) ([#189](https://github.com/DeepVista-AI/deepvista-cli/issues/189)) ([5056442](https://github.com/DeepVista-AI/deepvista-cli/commit/50564429a84ff044967cab8db831e282b5fac67b))
* **skill:** add phase need-input for :::dvNeedIntervention mermaid state ([#166](https://github.com/DeepVista-AI/deepvista-cli/issues/166)) ([ade6edf](https://github.com/DeepVista-AI/deepvista-cli/commit/ade6edf8a462199ce8b59119e7eb0d662ad94fc6))
* task improvements — timeout, phase notes, workflow resume, and web-agent polling ([#176](https://github.com/DeepVista-AI/deepvista-cli/issues/176)) ([d10ae1f](https://github.com/DeepVista-AI/deepvista-cli/commit/d10ae1fc5a8a291438b3eedd870fa59b797bcf3a))


### Bug Fixes

* **DV-1357:** move agent heartbeat into the Claude Code plugin ([#174](https://github.com/DeepVista-AI/deepvista-cli/issues/174)) ([41c4339](https://github.com/DeepVista-AI/deepvista-cli/commit/41c43390afaab06c90c103c5526e44f3f3f35ad8))
* reconcile _ensure_agents_for_projects return type (pyright) ([#173](https://github.com/DeepVista-AI/deepvista-cli/issues/173)) ([c134e42](https://github.com/DeepVista-AI/deepvista-cli/commit/c134e42abc39325cf2814126be7d249ba667f464))
* **tasks:** use single-quoted f-string to avoid escaped double quotes in task note hint ([#181](https://github.com/DeepVista-AI/deepvista-cli/issues/181)) ([297de78](https://github.com/DeepVista-AI/deepvista-cli/commit/297de78ee188cd9dcd9b4031b5b29b76733b160d))
* **types:** mark output_error as NoReturn to fix Pyright errors in schedule.py ([#153](https://github.com/DeepVista-AI/deepvista-cli/issues/153)) ([7ac8b12](https://github.com/DeepVista-AI/deepvista-cli/commit/7ac8b12f1b10a94cd6dbe8533b122a2cf8489228))


### Documentation

* add CONTRIBUTING.md covering PR workflow and the release-please prose trap ([#145](https://github.com/DeepVista-AI/deepvista-cli/issues/145)) ([a9012d9](https://github.com/DeepVista-AI/deepvista-cli/commit/a9012d9cf45de695c754a0c89deb3f80e63e8b48))
* add direct import path for downloaded skill markdown files ([#160](https://github.com/DeepVista-AI/deepvista-cli/issues/160)) ([31b35b9](https://github.com/DeepVista-AI/deepvista-cli/commit/31b35b9608e75759547d1bb803cc04b3bed2fea1))
* **DV-1434:** fix schedule command docstring to reference schedule_job cards ([#182](https://github.com/DeepVista-AI/deepvista-cli/issues/182)) ([d01f98d](https://github.com/DeepVista-AI/deepvista-cli/commit/d01f98d03a21256ee96ee4cae8b78f81c4b44a85))

## [0.1.17](https://github.com/DeepVista-AI/deepvista-cli/compare/v1.2.1...v0.1.17) (2026-07-01)


### ⚠ BREAKING CHANGES

* **DV-1281:** CLI help/docs cleanup — drop deprecated aliases, remove TUI, collapse vistabase into card ([#167](https://github.com/DeepVista-AI/deepvista-cli/issues/167))

### Features

* add --content-file to prevent agent summarization on import (DV-250) ([#38](https://github.com/DeepVista-AI/deepvista-cli/issues/38)) ([ca16e51](https://github.com/DeepVista-AI/deepvista-cli/commit/ca16e5124f7baeba3e921d08766d68e2e04f7b27))
* add --dry-run to all stateful CLI commands ([#77](https://github.com/DeepVista-AI/deepvista-cli/issues/77)) ([c6b1325](https://github.com/DeepVista-AI/deepvista-cli/commit/c6b1325217b0f55138d4a1ed570a7d575cbeeddf))
* add /dv-workflow skill for session workflow tracking ([#119](https://github.com/DeepVista-AI/deepvista-cli/issues/119)) ([83c5746](https://github.com/DeepVista-AI/deepvista-cli/commit/83c57461f6c6ca6ed2a8aa55d813187381c7f6d4))
* add OpenClaw auto-capture support ([#59](https://github.com/DeepVista-AI/deepvista-cli/issues/59)) ([4892d74](https://github.com/DeepVista-AI/deepvista-cli/commit/4892d742cf9d9cc67efa5b1b729587713b56e44e))
* add recipe discover and install CLI commands ([#40](https://github.com/DeepVista-AI/deepvista-cli/issues/40)) ([60c7d9d](https://github.com/DeepVista-AI/deepvista-cli/commit/60c7d9d1a652225b1817bd38da77503a6be5d289))
* Agent control plane CLI commands (DV-368) ([#71](https://github.com/DeepVista-AI/deepvista-cli/issues/71)) ([e3869d2](https://github.com/DeepVista-AI/deepvista-cli/commit/e3869d2daf5ab9b76d02cfed3946a3e02d7460ab))
* auto-update flow for CLI and skills (DV-378) ([#73](https://github.com/DeepVista-AI/deepvista-cli/issues/73)) ([88bd138](https://github.com/DeepVista-AI/deepvista-cli/commit/88bd138b7304154580dcd0e7feda5ad66169dba1))
* **card:** add vistabook and vistabook_run to CARD_TYPES ([#37](https://github.com/DeepVista-AI/deepvista-cli/issues/37)) ([9a9eb0d](https://github.com/DeepVista-AI/deepvista-cli/commit/9a9eb0dfe426913e24b3d18b29f329448c4c8b96))
* **cli:** add `deepvista lint` + `notes index` (DV-419) ([#90](https://github.com/DeepVista-AI/deepvista-cli/issues/90)) ([0d11306](https://github.com/DeepVista-AI/deepvista-cli/commit/0d11306cdd948bb46a38249e6c248c8590064cb2))
* **cli:** emit mermaid flowchart in workflow skills from create-from-note ([#93](https://github.com/DeepVista-AI/deepvista-cli/issues/93)) ([394c024](https://github.com/DeepVista-AI/deepvista-cli/commit/394c024d31c9955e5fa4ce2914029d9ae39e68c8))
* **cli:** remote skill catalog + agent plugins (DV-276) ([#98](https://github.com/DeepVista-AI/deepvista-cli/issues/98)) ([4d07ea8](https://github.com/DeepVista-AI/deepvista-cli/commit/4d07ea8dd9b378df1e100e75ba13363ffd42bbef))
* **cli:** session-scoped notes + version history (DV-449) ([#96](https://github.com/DeepVista-AI/deepvista-cli/issues/96)) ([be5cd01](https://github.com/DeepVista-AI/deepvista-cli/commit/be5cd011a287524668356b2fa03cb6ca29d67c5e))
* consolidate DV-791 + DV-796 (unified agent tag + install.sh cleanup) ([#133](https://github.com/DeepVista-AI/deepvista-cli/issues/133)) ([11344f1](https://github.com/DeepVista-AI/deepvista-cli/commit/11344f1197db1c605a711454cb269d0e0b2f678e))
* display URL instead of ID in CLI output ([#36](https://github.com/DeepVista-AI/deepvista-cli/issues/36)) ([685d474](https://github.com/DeepVista-AI/deepvista-cli/commit/685d4748a7989415390ef443681a149d778594c1))
* **DV-1079:** poll by default in task_queue run with single-instance lock ([#162](https://github.com/DeepVista-AI/deepvista-cli/issues/162)) ([eef464e](https://github.com/DeepVista-AI/deepvista-cli/commit/eef464e3ab6cb1591130b79903238a1a7327bc61))
* **DV-1247:** `tasks` group runs web-chat task cards via claude -p ([#165](https://github.com/DeepVista-AI/deepvista-cli/issues/165)) ([4c95aed](https://github.com/DeepVista-AI/deepvista-cli/commit/4c95aedb99104f3567b10e1d77f8c3b668627177))
* **DV-1277:** clean session-card title + link task runs to their chat ([#169](https://github.com/DeepVista-AI/deepvista-cli/issues/169)) ([b4de0c7](https://github.com/DeepVista-AI/deepvista-cli/commit/b4de0c7435bf89f475a25443e80524ab1da8420a))
* **DV-1281:** CLI help/docs cleanup — drop deprecated aliases, remove TUI, collapse vistabase into card ([#167](https://github.com/DeepVista-AI/deepvista-cli/issues/167)) ([b7f308b](https://github.com/DeepVista-AI/deepvista-cli/commit/b7f308be5a03421c9b08eab1622209a94826b72d))
* **DV-1294:** make the CLI a project-scoped client ([#170](https://github.com/DeepVista-AI/deepvista-cli/issues/170)) ([708d107](https://github.com/DeepVista-AI/deepvista-cli/commit/708d10739aa0ccf11319379a76fdea6cf646c493))
* **DV-1324:** add dv CLI alias ([#177](https://github.com/DeepVista-AI/deepvista-cli/issues/177)) ([f1973a3](https://github.com/DeepVista-AI/deepvista-cli/commit/f1973a35b488477df187ff2ccb5c0662b2f3efa8))
* **DV-1429:** tasks clean, auto-detect agent --type, prune stale agents ([#183](https://github.com/DeepVista-AI/deepvista-cli/issues/183)) ([38252e7](https://github.com/DeepVista-AI/deepvista-cli/commit/38252e71b33275bc7976037192a082c7f2ccb391))
* **DV-280:** add edit and +grep commands to card CLI ([#54](https://github.com/DeepVista-AI/deepvista-cli/issues/54)) ([2248724](https://github.com/DeepVista-AI/deepvista-cli/commit/2248724ccb8431d4dd818548a7b680e22b2d60a4))
* **DV-694:** add host-mode workflow execution for skill run ([#113](https://github.com/DeepVista-AI/deepvista-cli/issues/113)) ([fd55f85](https://github.com/DeepVista-AI/deepvista-cli/commit/fd55f8564ccecf73a279994fceada601fdf41e77))
* **DV-724:** add skills-refresh check to `deepvista lint` ([#115](https://github.com/DeepVista-AI/deepvista-cli/issues/115)) ([a46ea07](https://github.com/DeepVista-AI/deepvista-cli/commit/a46ea076e2007dfe1da3e2d54a2ffc17bf8a5d2f))
* **DV-742:** add `deepvista session` group + clarify notes vs cards intent ([#126](https://github.com/DeepVista-AI/deepvista-cli/issues/126)) ([9881e63](https://github.com/DeepVista-AI/deepvista-cli/commit/9881e633919f235d7966b048ba7c970171e5f682))
* **DV-751:** self-healing agent registration in `agents sync` ([#125](https://github.com/DeepVista-AI/deepvista-cli/issues/125)) ([f3fe02c](https://github.com/DeepVista-AI/deepvista-cli/commit/f3fe02c9f7e68bb46249ff9b291b76736bb6f845))
* **DV-817:** format session card with accordion turns ([#134](https://github.com/DeepVista-AI/deepvista-cli/issues/134)) ([96ade72](https://github.com/DeepVista-AI/deepvista-cli/commit/96ade72b0dead0e28881aa5df8317f1258252263))
* **DV-832:** --role on agents register/update + role-aware cache ([#137](https://github.com/DeepVista-AI/deepvista-cli/issues/137)) ([a67754d](https://github.com/DeepVista-AI/deepvista-cli/commit/a67754d2514ae67c61d52712f3a58d2ddb7290b7))
* **DV-836:** managed agents as Claude Code subagents (with custom prompts) ([#139](https://github.com/DeepVista-AI/deepvista-cli/issues/139)) ([211b416](https://github.com/DeepVista-AI/deepvista-cli/commit/211b4161e61a2dae0f53ebf054a7e6093b6a43b9))
* **DV-853:** productionize the deepvista subagents ([#147](https://github.com/DeepVista-AI/deepvista-cli/issues/147)) ([45e9ba1](https://github.com/DeepVista-AI/deepvista-cli/commit/45e9ba17de08243fe84be3de6826c72116360351))
* **DV-871:** move daily-planning to server; add schedule command ([#151](https://github.com/DeepVista-AI/deepvista-cli/issues/151)) ([7c317e7](https://github.com/DeepVista-AI/deepvista-cli/commit/7c317e7d6f71763f6622354b8581ead8b10ef8ea))
* **DV-936:** task_queue run/list/setup commands ([#155](https://github.com/DeepVista-AI/deepvista-cli/issues/155)) ([0d90691](https://github.com/DeepVista-AI/deepvista-cli/commit/0d9069106d14068d657e16415be80dec95f12085))
* **DV-941:** add windows install script and trampoline troubleshooting docs ([#156](https://github.com/DeepVista-AI/deepvista-cli/issues/156)) ([eed7335](https://github.com/DeepVista-AI/deepvista-cli/commit/eed7335ffdc1dfcfd84523ed0e77be066b7fe9c3))
* **DV-942:** print next-step hints after auth login ([#157](https://github.com/DeepVista-AI/deepvista-cli/issues/157)) ([0fca6c9](https://github.com/DeepVista-AI/deepvista-cli/commit/0fca6c9309623ee690c2c9e16870d528b558fd80))
* **dv-workflow:** add production monitoring — timestamps, error states, metrics ([#121](https://github.com/DeepVista-AI/deepvista-cli/issues/121)) ([7b7c07b](https://github.com/DeepVista-AI/deepvista-cli/commit/7b7c07b531f01826475407b67f2f9a96b758e01d))
* inject skill interpretation rules into agent system prompts on install ([#76](https://github.com/DeepVista-AI/deepvista-cli/issues/76)) ([e6d1e04](https://github.com/DeepVista-AI/deepvista-cli/commit/e6d1e046e106c923a34f038aa17ce29eb8462224))
* **origin:** detect OpenClaw agent from environment and process tree ([#102](https://github.com/DeepVista-AI/deepvista-cli/issues/102)) ([3aa5fb2](https://github.com/DeepVista-AI/deepvista-cli/commit/3aa5fb21c8fc98847aacebae99a334d88b7c9d28))
* **plugin:** announce DeepVista skill URL on Skill invocation ([#130](https://github.com/DeepVista-AI/deepvista-cli/issues/130)) ([fa03dce](https://github.com/DeepVista-AI/deepvista-cli/commit/fa03dce31b0ee0bac8349c6a91aa16dcc0f6aab9))
* publish skills via gh skill publish, drop ClawHub ([#75](https://github.com/DeepVista-AI/deepvista-cli/issues/75)) ([#78](https://github.com/DeepVista-AI/deepvista-cli/issues/78)) ([a8ea923](https://github.com/DeepVista-AI/deepvista-cli/commit/a8ea9237c946d21e80f59dc2187da42eeacd7d83))
* rename memory command to vistabase ([#39](https://github.com/DeepVista-AI/deepvista-cli/issues/39)) ([e02c1c6](https://github.com/DeepVista-AI/deepvista-cli/commit/e02c1c6f4f84c7f401817c463c2c6783a002af3a))
* rename recipe to skill across CLI (DV-360) ([#69](https://github.com/DeepVista-AI/deepvista-cli/issues/69)) ([ab11657](https://github.com/DeepVista-AI/deepvista-cli/commit/ab116570c5e4768d64800062ee6c32d150a69c7b))
* secure CLI auth with localhost callback and one-time codes ([#19](https://github.com/DeepVista-AI/deepvista-cli/issues/19)) ([d3acb76](https://github.com/DeepVista-AI/deepvista-cli/commit/d3acb7692a4b17aa801d4e019072bf9177e86f61))
* send origin metadata with /imagine requests (DV-257) ([#57](https://github.com/DeepVista-AI/deepvista-cli/issues/57)) ([ed91f5f](https://github.com/DeepVista-AI/deepvista-cli/commit/ed91f5f6876df3efcee55b91a0426763e9862260))
* **session:** skip session init for configured CWD patterns (DV-862) ([#148](https://github.com/DeepVista-AI/deepvista-cli/issues/148)) ([df74381](https://github.com/DeepVista-AI/deepvista-cli/commit/df743810ae6dec7c4a520c43d82f1eeae421762b))
* **skill:** add phase need-input for :::dvNeedIntervention mermaid state ([#166](https://github.com/DeepVista-AI/deepvista-cli/issues/166)) ([ade6edf](https://github.com/DeepVista-AI/deepvista-cli/commit/ade6edf8a462199ce8b59119e7eb0d662ad94fc6))
* **skill:** add phase reset command + workflow run_hint in skill get ([#129](https://github.com/DeepVista-AI/deepvista-cli/issues/129)) ([5a55bd4](https://github.com/DeepVista-AI/deepvista-cli/commit/5a55bd41c3b0dfeb1a27b5aabaefad3b072a0ef6))
* **skills:** prepare for ClawHub publishing (DV-251) ([#45](https://github.com/DeepVista-AI/deepvista-cli/issues/45)) ([8677f11](https://github.com/DeepVista-AI/deepvista-cli/commit/8677f115218d78843143ce67318eaf70fd2dcb50))
* task improvements — timeout, phase notes, workflow resume, and web-agent polling ([#176](https://github.com/DeepVista-AI/deepvista-cli/issues/176)) ([d10ae1f](https://github.com/DeepVista-AI/deepvista-cli/commit/d10ae1fc5a8a291438b3eedd870fa59b797bcf3a))


### Bug Fixes

* add URL to wrapped entity responses (DV-292) ([#64](https://github.com/DeepVista-AI/deepvista-cli/issues/64)) ([ed1e5ba](https://github.com/DeepVista-AI/deepvista-cli/commit/ed1e5bacad565589ad18788004e2964df2b8a845))
* authenticate with clawhub before publishing ([#49](https://github.com/DeepVista-AI/deepvista-cli/issues/49)) ([92d8d95](https://github.com/DeepVista-AI/deepvista-cli/commit/92d8d9507c9b30335a6d726a3562798967aa3c51))
* cap httpx dependency to &lt;1 to avoid incompatible pre-release ([#55](https://github.com/DeepVista-AI/deepvista-cli/issues/55)) ([cdea966](https://github.com/DeepVista-AI/deepvista-cli/commit/cdea9663f45646ef6fd07c625cc1ed60bde3e2bc))
* convert PEP 440 version to semver for ClawHub ([#51](https://github.com/DeepVista-AI/deepvista-cli/issues/51)) ([c43a503](https://github.com/DeepVista-AI/deepvista-cli/commit/c43a503c4c299357f595b84d09b1158d2d69885f))
* **DV-1357:** move agent heartbeat into the Claude Code plugin ([#174](https://github.com/DeepVista-AI/deepvista-cli/issues/174)) ([41c4339](https://github.com/DeepVista-AI/deepvista-cli/commit/41c43390afaab06c90c103c5526e44f3f3f35ad8))
* **DV-703:** use path-based vistabase URL in skill docs ([#114](https://github.com/DeepVista-AI/deepvista-cli/issues/114)) ([ce28de8](https://github.com/DeepVista-AI/deepvista-cli/commit/ce28de885f6591503860e37480377fc3a6e41e11))
* **dv-workflow:** create workflow skill via create-from-note + auto-sync Stop hook ([#120](https://github.com/DeepVista-AI/deepvista-cli/issues/120)) ([ed99c35](https://github.com/DeepVista-AI/deepvista-cli/commit/ed99c358cde14b1eaab97faf6ac261b0ca5fef8c))
* enforce YAML frontmatter, Mermaid diagrams, skill-creator routing (DV-520, DV-524, DV-525) ([#103](https://github.com/DeepVista-AI/deepvista-cli/issues/103)) ([08a14a5](https://github.com/DeepVista-AI/deepvista-cli/commit/08a14a593559e25555aa5432b7b4195cf1f4f115))
* **install:** run deepvista upgrade when already installed ([#124](https://github.com/DeepVista-AI/deepvista-cli/issues/124)) ([5f89fdf](https://github.com/DeepVista-AI/deepvista-cli/commit/5f89fdffa2e2db50f53f5178197028b03892720d))
* **notes:** reject +quick input that would force title truncation ([#135](https://github.com/DeepVista-AI/deepvista-cli/issues/135)) ([4411663](https://github.com/DeepVista-AI/deepvista-cli/commit/44116630924676e33ec3bddc061985726c18647f))
* prevent 'Not a directory' error in install script ([#63](https://github.com/DeepVista-AI/deepvista-cli/issues/63)) ([b5b2ee0](https://github.com/DeepVista-AI/deepvista-cli/commit/b5b2ee0a3bcecd4a0dbe1425b4a844ed3536f077))
* **publish:** handle stable releases where PEP 440 == semver tag ([#81](https://github.com/DeepVista-AI/deepvista-cli/issues/81)) ([fb53708](https://github.com/DeepVista-AI/deepvista-cli/commit/fb537084c6e1e95c915a12a6b77d7590111e2cf3))
* reconcile _ensure_agents_for_projects return type (pyright) ([#173](https://github.com/DeepVista-AI/deepvista-cli/issues/173)) ([c134e42](https://github.com/DeepVista-AI/deepvista-cli/commit/c134e42abc39325cf2814126be7d249ba667f464))
* **skill:** enforce 1:1 alignment between mermaid nodes and Phases accordions and also force trigger for claude when user mention skill ([#106](https://github.com/DeepVista-AI/deepvista-cli/issues/106)) ([fe785b9](https://github.com/DeepVista-AI/deepvista-cli/commit/fe785b9b1ee9644560b9c6059c6b1a246130ac0a))
* **skills:** add license: Apache-2.0 to all SKILL.md frontmatter ([#83](https://github.com/DeepVista-AI/deepvista-cli/issues/83)) ([a6ecb73](https://github.com/DeepVista-AI/deepvista-cli/commit/a6ecb734c2d87fef35f166e98e45f722e9eaa9d3))
* **skill:** use human-readable title in upsert_context_card for created skills ([#108](https://github.com/DeepVista-AI/deepvista-cli/issues/108)) ([95c7101](https://github.com/DeepVista-AI/deepvista-cli/commit/95c71015bad9cdabc745e717bcd2ed4e998c6706))
* **tasks:** use single-quoted f-string to avoid escaped double quotes in task note hint ([#181](https://github.com/DeepVista-AI/deepvista-cli/issues/181)) ([297de78](https://github.com/DeepVista-AI/deepvista-cli/commit/297de78ee188cd9dcd9b4031b5b29b76733b160d))
* teach skill the correct upgrade command for agent flows ([#118](https://github.com/DeepVista-AI/deepvista-cli/issues/118)) ([fa31ce9](https://github.com/DeepVista-AI/deepvista-cli/commit/fa31ce9120f7b260916d90db33dca03d0b0405e5))
* **tui:** handle None in _short() and apply ruff formatting ([#30](https://github.com/DeepVista-AI/deepvista-cli/issues/30)) ([dbf0a21](https://github.com/DeepVista-AI/deepvista-cli/commit/dbf0a2151ec4770c16dae827f26eaa092aa3b7c5))
* **types:** mark output_error as NoReturn to fix Pyright errors in schedule.py ([#153](https://github.com/DeepVista-AI/deepvista-cli/issues/153)) ([7ac8b12](https://github.com/DeepVista-AI/deepvista-cli/commit/7ac8b12f1b10a94cd6dbe8533b122a2cf8489228))
* update URL format from query param to path-based routing ([#60](https://github.com/DeepVista-AI/deepvista-cli/issues/60)) ([122c9ef](https://github.com/DeepVista-AI/deepvista-cli/commit/122c9ef637749d456b0a41fa5fae2f43ae35db10))
* use contextCard XML tag for vistabook references in instructions ([#68](https://github.com/DeepVista-AI/deepvista-cli/issues/68)) ([b3c534b](https://github.com/DeepVista-AI/deepvista-cli/commit/b3c534b331044b242a73da901d3af9584f534d83))
* use correct clawhub publish command ([#47](https://github.com/DeepVista-AI/deepvista-cli/issues/47)) ([591b2d2](https://github.com/DeepVista-AI/deepvista-cli/commit/591b2d213382c6c2766d48275590c4f4d0088f8f))
* use correct URL patterns for recipes and notes ([#53](https://github.com/DeepVista-AI/deepvista-cli/issues/53)) ([90add72](https://github.com/DeepVista-AI/deepvista-cli/commit/90add7240831611d7083e05cc8005b0e7b0acca6))


### Documentation

* add CONTRIBUTING.md covering PR workflow and the release-please prose trap ([#145](https://github.com/DeepVista-AI/deepvista-cli/issues/145)) ([a9012d9](https://github.com/DeepVista-AI/deepvista-cli/commit/a9012d9cf45de695c754a0c89deb3f80e63e8b48))
* add direct import path for downloaded skill markdown files ([#160](https://github.com/DeepVista-AI/deepvista-cli/issues/160)) ([31b35b9](https://github.com/DeepVista-AI/deepvista-cli/commit/31b35b9608e75759547d1bb803cc04b3bed2fea1))
* **DV-1434:** fix schedule command docstring to reference schedule_job cards ([#182](https://github.com/DeepVista-AI/deepvista-cli/issues/182)) ([d01f98d](https://github.com/DeepVista-AI/deepvista-cli/commit/d01f98d03a21256ee96ee4cae8b78f81c4b44a85))
* **readme:** reframe DeepVista as a self-evolving agent team platform ([#89](https://github.com/DeepVista-AI/deepvista-cli/issues/89)) ([97a010b](https://github.com/DeepVista-AI/deepvista-cli/commit/97a010b1cc8de2734f7fd721b402f96cff41daa7))
* revamp README with star-growth patterns ([#82](https://github.com/DeepVista-AI/deepvista-cli/issues/82)) ([e8cfcfa](https://github.com/DeepVista-AI/deepvista-cli/commit/e8cfcfaa3f4e442ad126deecda71a4f86f64449c))


### Miscellaneous Chores

* verify release-please pipeline ([#142](https://github.com/DeepVista-AI/deepvista-cli/issues/142)) ([70fdc62](https://github.com/DeepVista-AI/deepvista-cli/commit/70fdc62b7ee4e511cb180a8c45a14a3f9f1b88ac))

## [1.2.1](https://github.com/DeepVista-AI/deepvista-cli/compare/v1.2.0...v1.2.1) (2026-06-27)


### Bug Fixes

* **tasks:** use single-quoted f-string to avoid escaped double quotes in task note hint ([#181](https://github.com/DeepVista-AI/deepvista-cli/issues/181)) ([297de78](https://github.com/DeepVista-AI/deepvista-cli/commit/297de78ee188cd9dcd9b4031b5b29b76733b160d))

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
