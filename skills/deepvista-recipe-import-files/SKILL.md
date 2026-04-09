---
name: deepvista-recipe-import-files
description: |
  Recipe: Import files from the current directory (recursively) as context cards in DeepVista.
  TRIGGER when: user wants to import files as cards, "index this folder", "add files to DeepVista", "import codebase as context", "upload files as knowledge cards", "add all files in this directory to my knowledge base", or any request to bulk-import local files into DeepVista.
  DO NOT TRIGGER when: user wants to create a single note or card manually; or when working with non-file card types.
metadata:
  openclaw:
    category: recipe
    requires:
      bins:
        - deepvista
      skills:
        - deepvista-shared
    install:
      - kind: uv
        package: deepvista-cli
        bins: [deepvista]
    homepage: https://cli.deepvista.ai
    cliHelp: "deepvista card create --help"
---

# Import Files as Context Cards

> **PREREQUISITE:** Read [deepvista-shared](../deepvista-shared/SKILL.md) for auth, profiles, and global flags.

Walk the current directory recursively, read each file, and create a DeepVista context card with `type=file` for each one. The result is a searchable knowledge base of all files in the project.

> [!CAUTION] Bulk write operation — confirm with the user before starting. Ask whether they want to filter by extension, skip certain directories, or limit the number of files imported.

## Steps

### 1. Clarify scope with the user

Before running, confirm:
- **Directory**: current working directory (or a subdirectory they specify)
- **File filter**: all files, or specific extensions (e.g. `*.py`, `*.md`, `*.ts`)?
- **Exclusions**: skip common noise directories by default (`node_modules`, `.git`, `__pycache__`, `.venv`, `dist`, `build`, `.next`)
- **Limit**: warn if more than 50 files are matched — ask before proceeding

### 2. Discover files

Use the Glob or Bash tool to list all matching files recursively, excluding noise directories. Example shell command for reference:

```bash
find . -type f \
  -not -path '*/.git/*' \
  -not -path '*/node_modules/*' \
  -not -path '*/__pycache__/*' \
  -not -path '*/.venv/*' \
  -not -path '*/dist/*' \
  -not -path '*/build/*' \
  -not -path '*/.next/*' \
  | sort
```

For extension filtering, add `-name "*.py"` (or the relevant extension).

### 3. Read and create cards

For each file discovered:

1. **Read the file content** using the Read tool (skip binary files — if content is not valid UTF-8 text, skip with a note to the user).

2. **Create a card** with type `file`, using the relative file path as the title.

   **Always use `--content-file`** to read the file directly from disk — never paste file content inline via `--content`:

```bash
deepvista card create \
  --type file \
  --title "<relative/path/to/file>" \
  --content-file "<absolute/path/to/file>" \
  --tags '["imported"]'
```

- Use the relative path from the root of the scanned directory as the title (e.g. `src/utils/helpers.py`).
- Use `--content-file` with the **absolute** file path so the CLI reads the file directly from disk. This guarantees the full, exact content is stored — no summarization or truncation by the agent.
- Add `--tags '["imported"]'` so the user can find all imported cards with `deepvista card +search "imported"`.
- If the user wants to tag by language or project name, add those tags too.

3. **Report progress**: after each card is created, print the card ID and title. If creation fails, log the error and continue with the next file — do not abort the whole batch.

### 4. Summarize results

After processing all files, report:
- Total files found
- Total cards created successfully
- Any files skipped (binary, too large, or errors)

Example summary:

```
Import complete.
  ✓ 34 cards created
  - 2 files skipped (binary)
  - 1 file skipped (error: content too large)

Search your imported files:
  deepvista card +search "<query>" --type file
```

### 5. Verify (optional)

The user can search across the newly imported files:

```bash
deepvista card +search "<keyword>" --type file
```

## Tips

- **Large repos**: For repos with hundreds of files, import only the most relevant directories (e.g. `src/`) rather than the entire tree.
- **Re-import / updates**: There is no deduplication — running the recipe twice will create duplicate cards. Warn the user if they are re-importing a directory they may have imported before.
- **Tags for organization**: Encourage the user to pass a project-specific tag (e.g. `["imported", "my-project"]`) so they can filter cards per project later.
- **Skip lock files and generated files**: Suggest skipping `*.lock`, `*.min.js`, `*.map`, `package-lock.json`, `yarn.lock` by default.

## Examples

```bash
# After creating a card, view it in the app:
# https://app.deepvista.ai/cards/<id>

# Search imported files
deepvista card +search "authentication" --type file

# List all imported file cards
deepvista card list --type file
```

## See Also

- [deepvista-shared](../deepvista-shared/SKILL.md) — Auth and global flags
- [deepvista-vistabase](../deepvista-vistabase/SKILL.md) — Search and manage all card types
- [deepvista-notes](../deepvista-notes/SKILL.md) — Create notes (type=note) for summaries
