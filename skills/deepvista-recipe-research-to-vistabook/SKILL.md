---
name: deepvista-recipe-research-to-vistabook
description: "Recipe: Search your knowledge base, synthesize findings, and run a VistaBook workflow."
metadata:
  deepvista:
    category: "recipe"
    requires:
      bins:
        - uv
      skills:
        - deepvista-vistabase
        - deepvista-vistabook
    cliHelp: "deepvista vistabase +search --help"
---

# Research to VistaBook

> **PREREQUISITE:** Load the following skills: `deepvista-vistabase`, `deepvista-vistabook`

Search your knowledge base for relevant context, then run a VistaBook workflow with that context.

## Steps

1. **Search for relevant cards:**
   ```bash
   deepvista vistabase +search "your research topic" --limit 10
   ```

2. **Read the most relevant cards** (pick IDs from search results):
   ```bash
   deepvista vistabase get <card_id_1>
   deepvista vistabase get <card_id_2>
   ```

3. **Summarize findings** into a context string for the VistaBook.

4. **List available VistaBooks** to find the right workflow:
   ```bash
   deepvista vistabook list
   ```

5. **Run the VistaBook** with your research context:
   ```bash
   deepvista vistabook +run <vistabook_id> --input "Based on my research: <summary of findings>"
   ```

6. **Check run status:**
   ```bash
   deepvista vistabook +status <run_chat_id>
   ```

## Tips

- This recipe combines read operations (search, get) with a write operation (run).
- Confirm with the user before step 5 (the write step).
- The VistaBook run will have access to the full knowledge base, so the context input is for focusing the run, not the only information available.
