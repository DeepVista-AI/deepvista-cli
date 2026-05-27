---
description: Force a resync of the DeepVista catalog — skills and agent roles
---

Force a fresh sync of the DeepVista catalog — both skill stubs **and** agent
definitions — bypassing both throttles, and report what changed.

Run:

```bash
DEEPVISTA_FORCE_SYNC=1 ${CLAUDE_PLUGIN_ROOT}/scripts/deepvista-sync.sh
deepvista skill sync --target "${CLAUDE_PLUGIN_ROOT}/skills" --force --dry-run
deepvista agents export --target "${CLAUDE_PLUGIN_ROOT}/agents" --force --dry-run
```

Report to the user, in two sections:

- **Skills** — added / updated / removed stubs under
  `${CLAUDE_PLUGIN_ROOT}/skills/`.
- **Agents** — added / updated / removed `dv-<role>.md` subagents under
  `${CLAUDE_PLUGIN_ROOT}/agents/`.

Claude Code's live change detection picks up both in the current session:
skills appear in `/skills` as "locked by plugin", and each role becomes
callable inline as `@<role>`.

If the first command prints "deepvista CLI not on PATH", tell the user to
install the DeepVista CLI (`uv tool install deepvista-cli`) and authenticate
(`deepvista auth login`), then run `/refresh-skills` again.
