# project — scope the CLI to a project

Every DeepVista entity is scoped to a **project**. The CLI resolves each request
to a *working project* and sends it as the `X-Project-Id` header; emitted web
links are prefixed with `/project/{id}/…` so they resolve in the app. When no
working project is set the backend falls back to your default project (unchanged
legacy behavior).

The working project is **client-side scoping only** — `project use` does not
touch your server-side default project (no `set_default`/`activate`).

## Commands

```bash
deepvista project list           # list owned + shared projects (id, name, role)
deepvista project current        # the project the backend resolves right now
deepvista project show [<id>]    # metadata for a project (defaults to current)
deepvista project use <id>       # set the working project for this profile
deepvista project clear          # unset the working project
```

`project use <id>` validates that `<id>` is accessible (it must appear in
`project list`); an unknown/inaccessible id exits with code 3.

## Resolution order

Highest precedence wins:

1. `--project <id>` — global flag (before the resource) **or** the per-command
   override on `card`/`notes`/`chat`/`skill` `list`/`get`/`create`/`send`.
2. `DEEPVISTA_PROJECT_ID` environment variable.
3. The profile's persisted working project (`project use`).
4. None → the backend resolves your default project.

```bash
# one-off override for a single call (per-command flag)
deepvista card list --project 1234-…

# one-off override for the whole invocation (global flag, before the resource)
deepvista --project 1234-… card list

# scope an entire shell session
export DEEPVISTA_PROJECT_ID=1234-…
```

The working project is stored in the active profile in
`~/.config/deepvista/config.json`, alongside `api_url`/`auth_url`. Switching
profiles (`--profile`) switches working project too.

## Out of scope

Creating, deleting, or sharing projects from the CLI is not supported yet — use
the web app. `project use` only selects an existing project.
