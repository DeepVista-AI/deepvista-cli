"""Token load / save / refresh logic.

Storage: ~/.config/deepvista/credentials.{profile}.json (mode 0600)

Each credentials file supports multiple accounts:
  {
    "active": "user@example.com",
    "accounts": {
      "user@example.com": { ...token_set... },
      "other@example.com": { ...token_set... }
    }
  }

Legacy single-token files are auto-migrated on first read.

Token refresh uses the issuer URL from the JWT itself, so the CLI always
refreshes against the correct Supabase instance (production vs staging).
"""

from __future__ import annotations

import base64
import json
import logging
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

import httpx
from filelock import FileLock

from deepvista_cli.config import CONFIG_DIR
from deepvista_cli.config import credentials_path as _default_creds_path

logger = logging.getLogger(__name__)

REFRESH_BUFFER_SECONDS = 60  # refresh when <60s remaining


def _extract_issuer(access_token: str) -> str | None:
    """Extract the `iss` claim from a JWT without verifying the signature.

    The issuer looks like ``https://xyz.supabase.co/auth/v1`` and tells us
    which Supabase instance issued the token — needed so we refresh against
    the correct endpoint (production vs staging vs branch deploys).
    """
    try:
        payload_b64 = access_token.split(".")[1]
        # Fix padding
        padded = payload_b64 + "=" * (4 - len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded))
        return payload.get("iss")
    except Exception:
        return None


@dataclass
class TokenSet:
    access_token: str
    refresh_token: str
    expires_at: float  # unix timestamp
    user_id: str = ""
    email: str = ""
    issuer: str = ""  # e.g. "https://xyz.supabase.co/auth/v1"
    api_key: str = ""  # Supabase anon key — needed for token refresh

    @property
    def is_expired(self) -> bool:
        return time.time() >= (self.expires_at - REFRESH_BUFFER_SECONDS)

    @property
    def account_key(self) -> str:
        """Stable key for this account: email if available, else user_id."""
        return self.email or self.user_id

    def to_dict(self) -> dict:
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_at": self.expires_at,
            "user_id": self.user_id,
            "email": self.email,
            "issuer": self.issuer,
            "api_key": self.api_key,
        }

    @classmethod
    def from_dict(cls, data: dict) -> TokenSet:
        return cls(
            access_token=data["access_token"],
            refresh_token=data["refresh_token"],
            expires_at=float(data.get("expires_at", 0)),
            user_id=data.get("user_id", ""),
            email=data.get("email", ""),
            issuer=data.get("issuer", ""),
            api_key=data.get("api_key", ""),
        )


# ---------------------------------------------------------------------------
# Multi-account file storage
# ---------------------------------------------------------------------------


def _write_credentials_file(data: dict, path: Path) -> None:
    """Atomically write credentials JSON to *path* (mode 0600)."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=CONFIG_DIR, prefix=".credentials.", suffix=".tmp")
    try:
        os.chmod(tmp_path, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(json.dumps(data, indent=2))
        os.replace(tmp_path, path)
    except Exception:
        os.unlink(tmp_path)
        raise


def _load_credentials_file(path: Path) -> dict | None:
    """Load and return the raw credentials JSON, or None."""
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        logger.warning("Corrupt credentials file at %s", path)
        return None


def _is_legacy_format(data: dict) -> bool:
    """True if *data* is a legacy single-token file (has access_token at top level)."""
    return "access_token" in data and "accounts" not in data


def _migrate_legacy(data: dict, path: Path) -> dict:
    """Migrate a legacy single-token file to multi-account format in place."""
    tokens = TokenSet.from_dict(data)
    key = tokens.account_key or "default"
    migrated = {
        "active": key,
        "accounts": {key: tokens.to_dict()},
    }
    _write_credentials_file(migrated, path)
    logger.debug("Migrated legacy credentials to multi-account format at %s", path)
    return migrated


# ---------------------------------------------------------------------------
# Public multi-account helpers
# ---------------------------------------------------------------------------


def load_all_accounts(path: Path | None = None) -> tuple[str | None, dict[str, TokenSet]]:
    """Load all accounts from a credentials file.

    Returns (active_key, {key: TokenSet}).  If the file doesn't exist or is
    empty, returns (None, {}).
    """
    creds = path or _default_creds_path()
    data = _load_credentials_file(creds)
    if data is None:
        return None, {}

    if _is_legacy_format(data):
        data = _migrate_legacy(data, creds)

    accounts: dict[str, TokenSet] = {}
    for key, token_data in data.get("accounts", {}).items():
        try:
            accounts[key] = TokenSet.from_dict(token_data)
        except (KeyError, TypeError):
            logger.warning("Skipping corrupt account entry: %s", key)

    active = data.get("active")
    if active and active not in accounts:
        active = next(iter(accounts), None)

    return active, accounts


def save_account(tokens: TokenSet, path: Path | None = None, *, make_active: bool = True) -> None:
    """Add or update an account in the credentials file.

    If *make_active* is True (the default), this account becomes the active one.
    """
    creds = path or _default_creds_path()
    active, accounts = load_all_accounts(creds)
    key = tokens.account_key
    if not key:
        key = "default"
    accounts[key] = tokens

    if make_active or active is None:
        active = key

    data = {
        "active": active,
        "accounts": {k: v.to_dict() for k, v in accounts.items()},
    }
    _write_credentials_file(data, creds)
    logger.debug("Account %s saved to %s", key, creds)


def switch_active_account(account_key: str, path: Path | None = None) -> TokenSet:
    """Set a different account as active. Raises KeyError if not found."""
    creds = path or _default_creds_path()
    _active, accounts = load_all_accounts(creds)
    if account_key not in accounts:
        raise KeyError(account_key)

    data = {
        "active": account_key,
        "accounts": {k: v.to_dict() for k, v in accounts.items()},
    }
    _write_credentials_file(data, creds)
    return accounts[account_key]


def remove_account(account_key: str, path: Path | None = None) -> bool:
    """Remove a specific account. Returns True if it existed.

    If the removed account was active, the first remaining account becomes active.
    """
    creds = path or _default_creds_path()
    active, accounts = load_all_accounts(creds)
    if account_key not in accounts:
        return False

    del accounts[account_key]

    if not accounts:
        # Last account removed — delete the file entirely.
        if creds.exists():
            creds.unlink()
        return True

    if active == account_key:
        active = next(iter(accounts))

    data = {
        "active": active,
        "accounts": {k: v.to_dict() for k, v in accounts.items()},
    }
    _write_credentials_file(data, creds)
    return True


# ---------------------------------------------------------------------------
# Backward-compatible single-token API (used by HTTP client & auth commands)
# ---------------------------------------------------------------------------


def save_tokens(tokens: TokenSet, path: Path | None = None) -> None:
    """Persist tokens as the active account (multi-account aware)."""
    save_account(tokens, path, make_active=True)


def load_tokens(path: Path | None = None) -> TokenSet | None:
    """Load the *active* account's tokens from a credentials file."""
    active, accounts = load_all_accounts(path)
    if active and active in accounts:
        return accounts[active]
    if accounts:
        return next(iter(accounts.values()))
    return None


def delete_tokens(path: Path | None = None) -> None:
    """Remove all stored credentials for a profile."""
    creds = path or _default_creds_path()
    if creds.exists():
        creds.unlink()


def refresh_access_token(tokens: TokenSet) -> TokenSet:
    """Exchange a refresh token for a new token set via Supabase GoTrue.

    Uses the issuer URL and api_key from the stored token set, so the CLI
    never needs to know Supabase coordinates directly.
    """
    if not tokens.issuer or not tokens.api_key:
        raise ValueError(
            "Cannot refresh: missing issuer or api_key in stored credentials. "
            "Please re-authenticate with: deepvista auth login"
        )

    url = f"{tokens.issuer}/token?grant_type=refresh_token"
    resp = httpx.post(
        url,
        json={"refresh_token": tokens.refresh_token},
        headers={
            "apikey": tokens.api_key,
            "Content-Type": "application/json",
        },
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    user = data.get("user", {})
    return TokenSet(
        access_token=data["access_token"],
        refresh_token=data["refresh_token"],
        expires_at=time.time() + data.get("expires_in", 3600),
        user_id=user.get("id", ""),
        email=user.get("email", ""),
        issuer=_extract_issuer(data["access_token"]) or tokens.issuer,
        api_key=tokens.api_key,
    )


def get_valid_token(path: Path | None = None) -> TokenSet | None:
    """Load the active account's tokens and auto-refresh if expired."""
    creds = path or _default_creds_path()
    tokens = load_tokens(creds)
    if tokens is None:
        return None

    if tokens.is_expired and tokens.refresh_token:
        lock_path = creds.with_suffix(".lock")
        with FileLock(str(lock_path), timeout=10):
            # Re-read inside the lock in case a parallel invocation already refreshed.
            tokens = load_tokens(creds) or tokens
            if tokens.is_expired:
                try:
                    refreshed = refresh_access_token(tokens)
                    save_account(refreshed, creds, make_active=True)
                    tokens = refreshed
                except httpx.HTTPStatusError as e:
                    logger.error("Token refresh failed: HTTP %s", e.response.status_code)
                    return None
                except (httpx.ConnectError, ValueError) as e:
                    logger.error("Token refresh error: %s", e)
                    return None

    return tokens if tokens.access_token else None
