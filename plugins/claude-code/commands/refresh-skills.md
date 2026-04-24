---
description: Force a resync of the DeepVista remote skill catalog
---

Force a fresh sync of the DeepVista catalog, bypassing the throttle, and
report what changed.

Run:

```bash
DEEPVISTA_FORCE_SYNC=1 ${CLAUDE_PLUGIN_ROOT}/scripts/sync.sh
deepvista skill sync --force --dry-run
```

Report the added / updated / removed skills to the user. Claude Code's live
change detection picks up new stubs in the current session — the user does
not need to restart.

If the first command prints "deepvista CLI not on PATH", tell the user to
install the DeepVista CLI (`uv tool install deepvista-cli`) and authenticate
(`deepvista auth login`), then run `/refresh-skills` again.
