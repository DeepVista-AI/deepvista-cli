---
description: Force a resync of the DeepVista skill catalog
---

Force a fresh sync of the DeepVista skill catalog, bypassing the throttle, and
report what changed.

Run:

```bash
DEEPVISTA_FORCE_SYNC=1 ${CLAUDE_PLUGIN_ROOT}/scripts/deepvista-sync.sh
deepvista skill sync --target "${CLAUDE_PLUGIN_ROOT}/skills" --force --dry-run
```

Report to the user:

- **Skills** — added / updated / removed stubs under
  `${CLAUDE_PLUGIN_ROOT}/skills/`.

Claude Code's live change detection picks up new stubs in the current session:
skills appear in `/skills` as "locked by plugin".

If the first command prints "deepvista CLI not on PATH", tell the user to
install the DeepVista CLI (`uv tool install deepvista-cli`) and authenticate
(`deepvista auth login`), then run `/refresh-skills` again.
