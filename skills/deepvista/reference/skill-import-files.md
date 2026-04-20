# Import files — index a folder as `type=file` cards

Recursively import local files into the knowledge base as searchable `type=file`
cards. Bulk write operation — scope and confirmation matter.

Use when the user says: "import files as cards", "index this folder", "add files to
DeepVista", "import codebase as context", "upload files as knowledge".

## Before running — confirm scope

Walk the user through this list **before** issuing any `card create` calls:

1. **Directory** — which folder, recursive?
2. **File filter** — which extensions? (e.g. `.md,.py,.ts`)
3. **Exclusions** — apply sensible defaults unless the user says otherwise:
   `.git`, `node_modules`, `__pycache__`, `.venv`, `dist`, `build`, `.next`,
   `*.lock`, `*.min.js`, `*.map`, `package-lock.json`, `yarn.lock`.
4. **Estimated count** — run `find` to count matching files. If > 50, warn the user
   and ask for explicit confirmation.
5. **Tags** — e.g. `["imported", "my-project"]` for later filtering.

> [!CAUTION] This is a bulk write. Confirm the directory, filter, exclusions, and
> count with the user before starting.

## Discovery

Use Glob or Bash — either works. Example Bash:

```bash
find /absolute/path -type f \
  \( -name "*.md" -o -name "*.py" -o -name "*.ts" \) \
  -not -path "*/.git/*" \
  -not -path "*/node_modules/*"
```

## Import loop (one card per file)

> [!CAUTION] Write.

```bash
deepvista card create --type file \
  --title "src/utils/helpers.py" \
  --content-file /absolute/path/to/src/utils/helpers.py \
  --tags '["imported","my-project"]'
```

Rules:

- **Always** use `--content-file` with an **absolute path**. Never pass content
  inline — the file is stored verbatim.
- Use the path **relative to the project root** as the title (e.g.
  `src/utils/helpers.py`). Makes later `card +search` results readable.
- Skip binaries and lock files by default.
- Report progress per card; print a final summary: total found / created / skipped.

## Re-imports

No deduplication. Running the importer twice creates duplicates. If the user is
re-running after adding files, ask whether they want to:

- only import the new files (diff against existing `card list --type file`), or
- delete the old import (`card list --type file --tags …` → `card delete` loop) and
  re-import clean.

## Verification

```bash
deepvista card list --type file
deepvista card +search "authentication" --type file
```

## See also

- [vistabase-card.md](vistabase-card.md) — direct `card create / list / delete` docs
- [skill-analyze-notes.md](skill-analyze-notes.md) — similar bulk-read pattern, the
  other direction
