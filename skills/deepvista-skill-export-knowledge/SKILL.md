---
license: Apache-2.0
name: deepvista-skill-export-knowledge
description: "Skill: Export Skills as installable SKILL.md files for AI agents."
metadata:
  openclaw:
    category: skill
    requires:
      bins:
        - deepvista
      skills:
        - deepvista-skill
    install:
      - kind: uv
        package: deepvista-cli
        bins: [deepvista]
    homepage: https://cli.deepvista.ai
    cliHelp: "deepvista skill export --help"
---

# Export Knowledge as Skills

> **PREREQUISITE:** Load the following skill: `deepvista-skill`

Export Skills as SKILL.md files that can be installed in any AI agent (Claude Code, Cursor, OpenCode, and others).

## Steps

1. **List all Skills:**
   ```bash
   deepvista skill list
   ```

2. **For each Skill to export**, generate the SKILL.md:
   ```bash
   deepvista skill export <skill_id> --format skill
   ```

3. **Save each skill** to the agent's skills directory:
   ```bash
   mkdir -p ~/.agents/skills/<skill-name>/
   # Write the SKILL.md content from the JSON output to that directory
   ```

4. **Verify** — the skill should now be discoverable by the agent.

## Tips

- Read-only skill — only generates files, does not modify Skills.
- This is the Skill export pipeline: author workflows in DeepVista's GUI, export them as installable agent skills so anyone on your team can load them.
- The exported SKILL.md includes the full checklist and instructions in a format agents can follow directly.

## See Also

- [deepvista-skill](../deepvista-skill/SKILL.md) — Skill commands
