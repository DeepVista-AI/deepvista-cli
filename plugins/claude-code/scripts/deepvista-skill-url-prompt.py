#!/usr/bin/env python3
"""DeepVista skill-URL announcer — Claude Code UserPromptSubmit hook.

Slash commands like ``/deepvista:dv-foo`` or ``/dv-foo`` are dispatched by
Claude Code's slash-command pipeline and do not pass through the agent's
Skill tool, so the companion PreToolUse hook does not fire for them. This
hook scans the submitted prompt for a DeepVista slash invocation, looks
up the skill's server id from its ``SKILL.md`` frontmatter, and injects
the same imperative system reminder so the agent surfaces the
``app.deepvista.ai`` URL on its very first line.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

_SLASH_RE = re.compile(r"(?<!\w)/(?:[\w-]+:)?(dv-[\w-]+)")


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    prompt = payload.get("prompt") or ""
    if not isinstance(prompt, str):
        return 0

    match = _SLASH_RE.search(prompt)
    if not match:
        return 0
    skill = match.group(1)

    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT", "")
    if not plugin_root:
        return 0

    skill_md = Path(plugin_root) / "skills" / skill / "SKILL.md"
    try:
        head = skill_md.read_text(encoding="utf-8")[:4096]
    except OSError:
        return 0

    id_match = re.search(r"^x-deepvista-id:\s*(.+?)\s*$", head, re.MULTILINE)
    if not id_match:
        return 0
    skill_id = id_match.group(1).strip().strip('"').strip("'")
    if not skill_id:
        return 0

    url = f"https://app.deepvista.ai/skills/{skill_id}"
    json.dump(
        {
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": (
                    "IMPORTANT: Before running this skill, your VERY FIRST line of "
                    "output to the user MUST be exactly:\n\n"
                    f"📘 View this skill on DeepVista: {url}\n\n"
                    "Do not paraphrase, do not delay, do not skip. Then continue."
                ),
            }
        },
        sys.stdout,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
