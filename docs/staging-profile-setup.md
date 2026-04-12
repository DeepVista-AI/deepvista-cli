# Setting Up a Staging Profile

The DeepVista CLI supports named profiles so you can target different environments (production, staging, local) without juggling flags every time.

## Quick Start

```bash
# 1. Create the staging profile
deepvista config set staging \
  --api-url https://staging-api.deepvista.ai \
  --auth-url https://staging.deepvista.ai

# 2. Login on staging
deepvista --profile staging auth login

# 3. Verify
deepvista --profile staging auth status
```

## Why You Need Both `--api-url` and `--auth-url`

The CLI uses two separate URLs:

| Setting      | Purpose                                      | Default                        |
|-------------|----------------------------------------------|--------------------------------|
| `api_url`   | Where API calls (notes, recipes, etc.) go    | `https://api.deepvista.ai`     |
| `auth_url`  | Where the browser opens for OAuth login      | `https://app.deepvista.ai`     |

If you only set `--api-url`, the login flow still opens `app.deepvista.ai` (production) — and you'll authenticate against production instead of staging.

## Common Pitfall

Running `deepvista --profile staging auth login` **before** creating the profile silently falls back to production defaults. The login appears to succeed, but the tokens come from production.

**If this happened to you:**

```bash
# Clear the bad tokens
deepvista --profile staging auth logout

# Create the profile properly
deepvista config set staging \
  --api-url https://staging-api.deepvista.ai \
  --auth-url https://staging.deepvista.ai

# Login again
deepvista --profile staging auth login
```

## Where Things Are Stored

- **Profiles:** `~/.config/deepvista/config.json`
- **Credentials:** `~/.config/deepvista/credentials.<profile>.json`
  - e.g. `credentials.staging.json` for the staging profile

Each profile gets its own credentials file, so staging and production tokens never overwrite each other.

## Useful Commands

```bash
# List all profiles
deepvista config list

# Show a specific profile's settings
deepvista config show staging

# List accounts on a profile
deepvista --profile staging auth list

# Switch active account within a profile
deepvista --profile staging auth switch alice@example.com

# Delete a profile
deepvista config delete staging
```

## Setting Up a Local Profile

Same pattern for local development:

```bash
deepvista config set local \
  --api-url http://localhost:8080 \
  --auth-url http://localhost:3000

deepvista --profile local auth login
```
