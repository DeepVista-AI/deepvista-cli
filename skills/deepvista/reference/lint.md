# Lint — LLM health checks over the vistabase

`deepvista lint` asks the DeepVista agent to audit the knowledge base for quality
issues. Run `deepvista lint --help` for full flag reference.

## Agent conventions

> [!CAUTION] Calls the DeepVista agent. With `--fix`, the agent may merge, update, or
> delete cards. Confirm with the user before executing. Scheduled `--fix` runs must
> pass `--yes` to accept non-interactively.

Read-only: `deepvista lint --dry-run` (prints the prompt without calling the agent).

## Check kinds

| `--check` | What it looks for |
|---|---|
| `duplicates` | Near-duplicate cards (semantic). |
| `contradictions` | Cards whose claims conflict. |
| `stale` | Content likely out of date. |
| `orphans` | Cards with no inbound refs or relationships. |
| `missing-refs` | Concepts mentioned but lacking their own card. |
| `gaps` | Under-described entities that could be enriched. |
| `all` | All of the above (default). |

## Scheduling

Lint is most useful run periodically so the vistabase stays clean as it grows.

```bash
# Claude Code — self-pacing background loop
/loop deepvista lint --check duplicates

# Persistent schedule (survives session end)
/schedule "every 4 hours" deepvista lint --check duplicates
/schedule "weekly" deepvista lint --fix --yes

# cron (any agent)
0 */4 * * *  deepvista lint --check duplicates >> ~/.config/deepvista/logs/lint.log 2>&1
```

## Examples

```bash
deepvista lint                                              # full check, report only
deepvista lint --check duplicates
deepvista lint --check duplicates --check contradictions --fix
deepvista lint --dry-run
```

## See also

- [notes.md](notes.md) — `deepvista notes index` for entity extraction on individual notes
- [chat.md](chat.md) — lint uses the same NDJSON event format as `chat +send`
