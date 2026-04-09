---
name: deepvista-recipe-research-to-recipe
description: "Recipe: Search your knowledge base, synthesize findings, and run a Recipe workflow."
metadata:
  openclaw:
    category: recipe
    requires:
      bins:
        - deepvista
      skills:
        - deepvista-vistabase
        - deepvista-recipe
    install:
      - kind: uv
        package: deepvista-cli
        bins: [deepvista]
    homepage: https://cli.deepvista.ai
    cliHelp: "deepvista card +search --help"
---

# Research to Recipe

> **PREREQUISITE:** Load the following skills: `deepvista-vistabase`, `deepvista-recipe`

Search your knowledge base for relevant context, synthesize it, then run a Recipe workflow with that context as input.

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

3. **Summarize findings** into a context string for the Recipe.

4. **List available Recipes** to find the right workflow:
   ```bash
   deepvista recipe list
   ```

5. **Confirm with the user** which Recipe to run and what context to pass, then run it:
   ```bash
   deepvista recipe run <recipe_id> --input "Based on my research: <summary of findings>"
   ```

6. **Check run status:**
   ```bash
   deepvista recipe status <run_chat_id>
   ```

## Tips

- Steps 1–4 are read-only. Step 5 (`recipe run`) is the only write operation — always confirm with the user before executing it.
- The Recipe run has access to the full knowledge base; the `--input` flag focuses the run, it doesn't limit what the agent can see.
- After a run starts, the agent creates a linked chat session — continue the conversation using `deepvista chat +send --chat-id <run_chat_id>`.

## See Also

- [deepvista-vistabase](../deepvista-vistabase/SKILL.md) — card search and retrieval
- [deepvista-recipe](../deepvista-recipe/SKILL.md) — Recipe list, run, and status
