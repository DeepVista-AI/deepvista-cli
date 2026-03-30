---
name: deepvista-recipe-export-knowledge-as-skills
description: "Recipe: Export multiple VistaBooks as installable SKILL.md files for AI agents."
metadata:
  deepvista:
    category: "recipe"
    requires:
      bins:
        - uv
      skills:
        - deepvista-vistabook
    cliHelp: "deepvista vistabook +export --help"
---

# Export Knowledge as Skills

> **PREREQUISITE:** Load the following skills: `deepvista-vistabook`

Export multiple VistaBooks as SKILL.md files that can be installed in any AI agent (Claude Code, OpenCode, OpenClaw, Codex).

## Steps

1. **List all VistaBooks:**
   ```bash
   deepvista --profile local vistabook list
   ```

2. **For each VistaBook to export**, generate the SKILL.md:
   ```bash
   deepvista --profile local vistabook +export <vistabook_id_1> --format skill
   deepvista --profile local vistabook +export <vistabook_id_2> --format skill
   ```

3. **Save each skill** to the agent's skills directory:
   ```bash
   mkdir -p ~/.agents/skills/<skill-name>/
   # Extract the SKILL.md content from the JSON output and save it
   ```

4. **Verify installation** — the skills should now be discoverable by the agent.

## Tips

- Read-only recipe — only generates files, does not modify VistaBooks.
- This is the VistaBook-as-Skill pipeline: author workflows in DeepVista's GUI, share as agent skills.
- Skills can also be distributed via `npx skills add` for the broader agent ecosystem.
