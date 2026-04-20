---
license: Apache-2.0
name: deepvista-skill-research-to-skill
description: "Skill: Search your knowledge base, synthesize findings, and run a Skill workflow."
metadata:
  openclaw:
    category: skill
    requires:
      bins:
        - deepvista
      skills:
        - deepvista-vistabase
        - deepvista-skill
    install:
      - kind: uv
        package: deepvista-cli
        bins: [deepvista]
    homepage: https://cli.deepvista.ai
    cliHelp: "deepvista card +search --help"
---

# Research to Skill

> **PREREQUISITE:** Load the following skills: `deepvista-vistabase`, `deepvista-skill`

Search your knowledge base for relevant context, synthesize it, then run a Skill workflow with that context as input.

## Steps

1. **Search for relevant cards:**
   ```bash
   deepvista card +search "your research topic" --limit 10
   ```

2. **Read the most relevant cards** (pick IDs from search results):
   ```bash
   deepvista card get <card_id_1>
   deepvista card get <card_id_2>
   ```

3. **Summarize findings** into a context string for the Skill.

4. **List available Skills** to find the right workflow:
   ```bash
   deepvista skill list
   ```

5. **Confirm with the user** which Skill to run and what context to pass, then run it:
   ```bash
   deepvista skill run <skill_id> --input "Based on my research: <summary of findings>"
   ```

6. **Check run status:**
   ```bash
   deepvista skill status <run_chat_id>
   ```

## Tips

- Steps 1–4 are read-only. Step 5 (`skill run`) is the only write operation — always confirm with the user before executing it.
- The Skill run has access to the full knowledge base; the `--input` flag focuses the run, it doesn't limit what the agent can see.
- After a run starts, the agent creates a linked chat session — continue the conversation using `deepvista chat +send --chat-id <run_chat_id>`.

## See Also

- [deepvista-vistabase](../deepvista-vistabase/SKILL.md) — card search and retrieval
- [deepvista-skill](../deepvista-skill/SKILL.md) — Skill list, run, and status
