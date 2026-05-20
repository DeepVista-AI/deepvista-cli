# Create a workflow skill from one or more notes

`deepvista skill create-from-note` asks the DeepVista agent to read one or more
source notes (podcast episodes, interview transcripts, book chapters, research
summaries) and synthesize a **workflow** skill grounded in their content.
Run `deepvista skill create-from-note --help` for full flag reference.

The generated skill is stored as a context card of `type=skill`, linked back to
every source note via `related_context_card_ids`. Streams NDJSON identical to
`chat +send`.

## Agent conventions

> [!CAUTION] Write — the agent creates skill cards in the user's project.
> Confirm before executing, or pass `--yes` for scripted/batch use.

## Non-obvious: source selectors

Beyond passing note IDs directly, `create-from-note` supports several selectors that
let you describe *which* notes to synthesize without knowing their IDs upfront:

| Selector | What it resolves |
|---|---|
| `--from-search QUERY` | Hybrid vector + keyword search over notes |
| `--from-similar SEED_NOTE_ID` | Notes similar to a seed note (graph neighbours) |
| `--from-tag TAG` | All notes whose `tags` list contains TAG |
| `--from-grep REGEX` | Notes whose content matches a regex |
| `--from-file PATH` | Read one ID per line from a file; pass `-` for stdin |

All selectors compose — union-merged, de-duplicated, capped by `--limit N` (default 5, max 25).

Use `--dry-run` to preview resolved notes + the synthesis prompt before spending tokens.

## Examples

```bash
# Single note
deepvista skill create-from-note 0d5d1fb2-7414-4593-abc4-fb74984f4b2f

# Multiple notes
deepvista skill create-from-note 0d5d1fb2-... 8a1f2c40-... --kind workflow --yes

# Semantic selector — no prior IDs needed
deepvista skill create-from-note \
  --from-search "product-market fit signals" --limit 5 --kind workflow --yes

# Tag corpus rollup
deepvista skill create-from-note --from-tag lenny --limit 10 --yes

# Graph expansion from a seed
deepvista skill create-from-note --from-similar 0d5d1fb2-... --limit 4 --yes

# Regex selector
deepvista skill create-from-note --from-grep "DRI|operating rhythm" --yes

# Pipe from a prior search
deepvista notes list --limit 100 \
  | jq -r '.notes[] | select(.title | test("positioning"; "i")) | .id' \
  | deepvista skill create-from-note --from-file - --kind workflow --yes

# Preview first
deepvista skill create-from-note --from-tag lenny --limit 5 --dry-run
```

## After creation

Generated skills land with `status=unconfirmed`. Inspect with
[`deepvista card get <card_id>`](vistabase-card.md) and verify the SKILL.md
body before running.

## See also

- [notes.md](notes.md) — capturing source notes and re-indexing
- [skill.md](skill.md) — listing and running the generated skills
- [skill-research-to-skill.md](skill-research-to-skill.md) — broader search → synthesize → run pattern
