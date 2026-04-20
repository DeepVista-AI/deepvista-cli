# Export a Skill as a portable `SKILL.md`

Turn a DeepVista Skill into a file another agent (Claude Code, Cursor, OpenCode,
OpenClaw, etc.) can install. Pure read-only pipeline — nothing on the DeepVista side
is modified.

Use when the user says: "export a skill", "save this skill as a file", "make this
skill portable", "share a skill with another agent".

## Workflow

1. **Find the Skill id** (read-only):
   ```bash
   deepvista skill list
   ```

2. **Export** (read-only — produces a single `SKILL.md` on stdout):
   ```bash
   deepvista skill export <skill_id> --format skill
   ```

3. **Install** into the agent of choice. This is a local filesystem write on the
   user's machine, not a DeepVista write — confirm the target path but otherwise
   safe:

   ```bash
   mkdir -p ~/.agents/skills/<skill-name>/
   deepvista skill export <skill_id> --format skill \
     > ~/.agents/skills/<skill-name>/SKILL.md
   ```

   For Claude Code: `~/.claude/skills/<skill-name>/SKILL.md`.
   For Cursor: `~/.cursor/skills/<skill-name>/SKILL.md`.

## What the exported `SKILL.md` contains

- Frontmatter (`name`, `description`, and DeepVista-specific metadata)
- The full checklist — every phase, every step, in order
- Any inline instructions the author added

The name inside the file matches the target directory name (an agent-skills-spec
requirement — see https://agentskills.io/specification).

## See also

- [skill.md](skill.md) — the `skill export` command (also documented there)
- [skill-research-to-skill.md](skill-research-to-skill.md) — the opposite direction:
  run an existing DeepVista Skill with curated context
