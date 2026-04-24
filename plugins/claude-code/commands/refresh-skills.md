---
description: Force a resync of the DeepVista remote skill catalog
---

Force a fresh sync of the DeepVista catalog, bypassing the throttle, and
report what changed.

Run:

```bash
DEEPVISTA_FORCE_SYNC=1 ${CLAUDE_PLUGIN_ROOT}/scripts/sync.sh
deepvista skill sync --target "${CLAUDE_PLUGIN_ROOT}/skills" --force --dry-run
```

Report the added / updated / removed skills to the user. Claude Code's live
change detection picks up new stubs under `${CLAUDE_PLUGIN_ROOT}/skills/` in
the current session — they appear in `/skills` immediately as "locked by
plugin".

If the first command prints "deepvista CLI not on PATH", tell the user to
install the DeepVista CLI (`uv tool install deepvista-cli`) and authenticate
(`deepvista auth login`), then run `/refresh-skills` again.
