# Lint — LLM health checks over the vistabase

`deepvista lint` asks the DeepVista agent to audit the knowledge base for
quality issues: duplicates, contradictions, stale claims, orphan cards,
missing cross-references, and data gaps. Inspired by
[karpathy's LLM health-check idea](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f).

The agent uses `find_similar_cards`, `chat_cypher_search`, and `exa_search`
to investigate, then streams a numbered findings list back as NDJSON
(same format as `chat +send`).

## Command

### `lint` — write (agent invocation)

> [!CAUTION] Calls the DeepVista agent. With `--fix`, the agent may merge,
> update, or delete cards. Confirm with the user before executing.

```bash
deepvista lint [--check KIND]... [--fix] [--chat-id ID] [--dry-run]
```

| Flag | Default | Purpose |
|---|---|---|
| `--check KIND` | `all` | Scope: `duplicates`, `contradictions`, `stale`, `orphans`, `missing-refs`, `gaps`, `all`. Repeatable. |
| `--fix` | off | Let the agent apply fixes (merge duplicates, update stale cards, link orphans). Default is report-only. |
| `--chat-id ID` | — | Continue an existing lint session. |
| `--dry-run` | — | Print the prompt that would be sent to the agent without calling it. |

## Checks

| Check | What it looks for |
|---|---|
| `duplicates` | Near-duplicate cards (semantic). Canonical vs. loser. |
| `contradictions` | Cards whose claims conflict — newer source supersedes older. |
| `stale` | Content likely out of date relative to newer cards or general knowledge. |
| `orphans` | Cards with no inbound refs or graph relationships. |
| `missing-refs` | Concepts mentioned but lacking their own card. |
| `gaps` | Under-described entities that could be filled with a web search. |

## Examples

```bash
# Full health check, report only
deepvista lint

# Just duplicates
deepvista lint --check duplicates

# Duplicates + contradictions, let the agent fix
deepvista lint --check duplicates --check contradictions --fix

# Preview the prompt
deepvista lint --dry-run
```

## Scheduling (periodic linting)

The whole point of lint is to run it periodically so the vistabase stays
clean as it grows. Two good cadences:

- **Every 4 hours:** catch freshly-added cards before they drift.
- **Weekly:** full `--fix` pass.

### Claude Code — background /loop

```bash
# In a Claude Code session, kick off a self-pacing loop:
/loop deepvista lint --check duplicates
```

Or schedule it persistently with the `schedule` skill:

```bash
/schedule "every 4 hours" deepvista lint --check duplicates
/schedule "weekly" deepvista lint --fix
```

### Cursor Agent — cron

Cursor doesn't ship a native scheduler. Use system cron:

```cron
# Every 4 hours: lint + re-index notes
0 */4 * * *  deepvista lint --check duplicates >> ~/.deepvista/lint.log 2>&1
15 */4 * * * deepvista notes index --limit 50 >> ~/.deepvista/index.log 2>&1
```

### Any agent — `at` / launchd / systemd

`deepvista lint` is stdout-friendly (NDJSON), so pipe it into whatever job
runner you already have.

## See also

- [notes.md](notes.md) — `deepvista notes index` triggers entity extraction
  on individual notes; often paired with `lint --check missing-refs`.
- [chat.md](chat.md) — `lint` is a curated variant of `chat +send`; the
  NDJSON event format is identical.
