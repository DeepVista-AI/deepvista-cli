# Memory — deprecated alias for `vistabase`

`deepvista memory` is an alias for `deepvista vistabase`. Same endpoints, same output,
same read-only semantics. The canonical name is `vistabase`; `memory` survives for
backward compatibility only.

## Alias mapping

| Old | Canonical |
|---|---|
| `deepvista memory show` | `deepvista vistabase show` |
| `deepvista memory search "<query>"` | `deepvista vistabase search "<query>"` |

Both accept the same flags (`--limit`, `--format`, `--profile`, etc.).

## When users say "memory"

- "Show my memory" / "what do you remember about me" / "search my memory" — route to
  `deepvista vistabase show` or `deepvista vistabase search "<query>"`. Either name
  works; prefer `vistabase` in any new examples you write.
- "Save this to memory" / "remember this for later" — **not** a vistabase operation
  from the CLI. Route to [notes.md](notes.md) (explicit note) or let the chat hook in
  [openclaw.md](openclaw.md) pick it up automatically.

## See also

- [vistabase.md](vistabase.md) — canonical reference
- [chat.md](chat.md) — the only way to write into vistabase
