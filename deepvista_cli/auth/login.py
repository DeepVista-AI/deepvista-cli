"""Login flow for the DeepVista CLI.

Flow:
  1. `deepvista auth login` opens browser to /auth/cli and exits
  2. User authenticates in browser
  3. Browser page shows a ready-to-paste command: `deepvista auth login --code <base64>`
  4. User copies the full command and pastes it into the terminal
  5. CLI decodes the code and stores tokens locally
"""

from __future__ import annotations

import base64
import json
import time
import webbrowser

import click

from deepvista_cli.auth.tokens import TokenSet, save_tokens


def login_interactive(site_url: str = "https://app.deepvista.ai") -> None:
    """Open browser to the login page and exit.

    The browser page will show the full `deepvista auth login --code <b64>`
    command for the user to copy and paste back into the terminal.
    """
    login_url = f"{site_url}/auth/cli"

    click.echo("", err=True)
    click.echo("  Opening browser to: " + login_url, err=True)
    click.echo("", err=True)
    click.echo("  After logging in, copy the command shown on the page", err=True)
    click.echo("  and paste it into your terminal.", err=True)
    click.echo("", err=True)

    webbrowser.open(login_url)


def login_with_code(code: str) -> TokenSet:
    """Decode and store a base64-encoded auth code from the /auth/cli page.

    The code is base64(JSON) containing:
      access_token, refresh_token, expires_at, user.id, user.email
    """
    try:
        # Handle padding — base64 may have been copy-pasted without trailing =
        padded = code + "=" * (4 - len(code) % 4) if len(code) % 4 else code
        payload = json.loads(base64.b64decode(padded))
    except Exception:
        raise click.ClickException("Invalid auth code. Make sure you copied the entire code from the browser.")

    if not isinstance(payload, dict) or "access_token" not in payload:
        raise click.ClickException(
            "Auth code is missing required fields. Make sure you copied the code from the /auth/cli page."
        )

    user = payload.get("user", {})
    tokens = TokenSet(
        access_token=payload["access_token"],
        refresh_token=payload.get("refresh_token", ""),
        expires_at=float(payload.get("expires_at", time.time() + 3600)),
        user_id=user.get("id", ""),
        email=user.get("email", ""),
    )
    save_tokens(tokens)
    return tokens
