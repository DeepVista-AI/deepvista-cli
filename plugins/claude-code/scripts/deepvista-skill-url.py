#!/usr/bin/env python3
"""DeepVista skill-URL announcer — Claude Code PreToolUse hook on the Skill tool.

When a synced DeepVista catalog stub (``dv-*``) is invoked, looks up the
skill's server id from its ``SKILL.md`` frontmatter and emits a system
reminder telling Claude to show the user the skill's ``app.deepvista.ai``
URL before it runs.

PreToolUse stdout is not surfaced to the user (see Claude Code hooks docs),
so the URL is injected via ``hookSpecificOutput.additionalContext`` and the
reminder instructs the agent to print it.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    skill = (payload.get("tool_input") or {}).get("skill") or ""
    # Strip any plugin namespace (e.g. "deepvista:dv-foo" -> "dv-foo").
    skill = skill.rsplit(":", 1)[-1].strip()
    if not skill.startswith("dv-"):
        return 0

    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT", "")
    if not plugin_root:
        return 0

    skill_md = Path(plugin_root) / "skills" / skill / "SKILL.md"
    try:
        head = skill_md.read_text(encoding="utf-8")[:4096]
    except OSError:
        return 0

    match = re.search(r"^x-deepvista-id:\s*(.+?)\s*$", head, re.MULTILINE)
    if not match:
        return 0
    skill_id = match.group(1).strip().strip('"').strip("'")
    if not skill_id:
        return 0

    url = f"https://app.deepvista.ai/skills/{skill_id}"
    json.dump(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "additionalContext": (
                    f"Before running this DeepVista skill, tell the user they can view it on DeepVista: {url}"
                ),
            }
        },
        sys.stdout,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
