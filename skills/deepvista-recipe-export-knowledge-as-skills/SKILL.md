---
name: deepvista-recipe-export-knowledge-as-skills
description: "Recipe: Export Recipes as installable SKILL.md files for AI agents."
metadata:
  openclaw:
    category: recipe
    requires:
      bins:
        - deepvista
      skills:
        - deepvista-recipe
    install:
      - kind: uv
        package: deepvista-cli
        bins: [deepvista]
    homepage: https://cli.deepvista.ai
    cliHelp: "deepvista recipe export --help"
---

# Export Knowledge as Skills

> **PREREQUISITE:** Load the following skill: `deepvista-recipe`

Export Recipes as SKILL.md files that can be installed in any AI agent (Claude Code, Cursor, OpenCode, and others).

## Steps

1. **List all Recipes:**
   ```bash
   deepvista recipe list
   ```

2. **For each Recipe to export**, generate the SKILL.md:
   ```bash
   deepvista recipe export <recipe_id> --format skill
   ```

3. **Save each skill** to the agent's skills directory:
   ```bash
   mkdir -p ~/.agents/skills/<skill-name>/
   # Write the SKILL.md content from the JSON output to that directory
   ```

4. **Verify** — the skill should now be discoverable by the agent.

## Tips

- Read-only recipe — only generates files, does not modify Recipes.
- This is the Recipe-as-Skill pipeline: author workflows in DeepVista's GUI, export them as installable agent skills so anyone on your team can load them.
- The exported SKILL.md includes the full checklist and instructions in a format agents can follow directly.

## See Also

- [deepvista-recipe](../deepvista-recipe/SKILL.md) — Recipe commands
