---
name: install-deepvista-cli
description: |
  Install the DeepVista CLI. Load when the `deepvista` binary is missing from
  PATH (hooks/commands return "command not found" or silently no-op), when the
  user asks how to install DeepVista, or when `deepvista auth login` hasn't
  been run yet. Ships with the DeepVista Claude Code plugin so the install
  path stays discoverable even before the CLI is present.
---

# Install the DeepVista CLI

The DeepVista Claude Code plugin requires the `deepvista` CLI to be installed
separately. Without it, the plugin's `SessionStart` hook exits silently and
the skill catalog won't sync — so `/skills` shows no DeepVista entries.

## Install

```bash
uv tool install deepvista-cli   # preferred
# or
pip install deepvista-cli
```

## Authenticate

```bash
deepvista auth login      # opens a browser for OAuth
deepvista auth status     # verify
```

## Trigger a first sync

Once the CLI is installed and authenticated, force the plugin's sync without
waiting for the next session start:

```
/refresh-skills
```

This writes skill stubs under `${CLAUDE_PLUGIN_ROOT}/skills/`.

## Full reference

The canonical install + auth + profile reference lives with the CLI itself:
[`skills/deepvista/reference/shared.md`](https://github.com/DeepVista-AI/deepvista-cli/blob/main/skills/deepvista/reference/shared.md).
Load it for profile switching, headless-auth codes, credential paths, and
global-flag rules.
