"""Token load / save / refresh logic.

Storage: ~/.config/deepvista/credentials.json (mode 0600)

Token refresh uses Supabase GoTrue refresh endpoint — no browser needed.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

import httpx
from filelock import FileLock

from deepvista_cli.config import CONFIG_DIR, SUPABASE_ANON_KEY, SUPABASE_URL
from deepvista_cli.config import credentials_path as _default_creds_path

logger = logging.getLogger(__name__)

REFRESH_BUFFER_SECONDS = 60  # refresh when <60s remaining


@dataclass
class TokenSet:
    access_token: str
    refresh_token: str
    expires_at: float  # unix timestamp
    user_id: str = ""
    email: str = ""

    @property
    def is_expired(self) -> bool:
        return time.time() >= (self.expires_at - REFRESH_BUFFER_SECONDS)

    def to_dict(self) -> dict:
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_at": self.expires_at,
            "user_id": self.user_id,
            "email": self.email,
        }

    @classmethod
    def from_dict(cls, data: dict) -> TokenSet:
        return cls(
            access_token=data["access_token"],
            refresh_token=data["refresh_token"],
            expires_at=float(data.get("expires_at", 0)),
            user_id=data.get("user_id", ""),
            email=data.get("email", ""),
        )


# ---------------------------------------------------------------------------
# File storage
# ---------------------------------------------------------------------------


def save_tokens(tokens: TokenSet, path: Path | None = None) -> None:
    """Persist tokens to a per-profile credentials file (mode 0600).

    Writes atomically via a temp file so the credentials file is never
    world-readable, even briefly (avoids TOCTOU between write and chmod).
    """
    creds = path or _default_creds_path()
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=CONFIG_DIR, prefix=".credentials.", suffix=".tmp")
    try:
        os.chmod(tmp_path, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(json.dumps(tokens.to_dict(), indent=2))
        os.replace(tmp_path, creds)
    except Exception:
        os.unlink(tmp_path)
        raise
    logger.debug("Tokens saved to %s", creds)


def load_tokens(path: Path | None = None) -> TokenSet | None:
    """Load tokens from a per-profile credentials file."""
    creds = path or _default_creds_path()
    if creds.exists():
        try:
            data = json.loads(creds.read_text())
            return TokenSet.from_dict(data)
        except (json.JSONDecodeError, KeyError):
            logger.warning("Corrupt credentials file at %s", creds)
    return None


def delete_tokens(path: Path | None = None) -> None:
    """Remove stored tokens for a profile."""
    creds = path or _default_creds_path()
    if creds.exists():
        creds.unlink()


def refresh_access_token(refresh_token: str) -> TokenSet:
    """Exchange a refresh token for a new token set via Supabase GoTrue.

    POST {SUPABASE_URL}/auth/v1/token?grant_type=refresh_token
    """
    url = f"{SUPABASE_URL}/auth/v1/token?grant_type=refresh_token"
    resp = httpx.post(
        url,
        json={"refresh_token": refresh_token},
        headers={
            "apikey": SUPABASE_ANON_KEY,
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
    )


def get_valid_token(path: Path | None = None) -> TokenSet | None:
    """Load tokens and auto-refresh if expired. Returns None if not authenticated."""
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
                    tokens = refresh_access_token(tokens.refresh_token)
                    save_tokens(tokens, creds)
                except httpx.HTTPStatusError as e:
                    logger.error("Token refresh failed: HTTP %s", e.response.status_code)
                    return None
                except httpx.ConnectError:
                    logger.error("Cannot reach Supabase for token refresh")
                    return None

    return tokens if tokens.access_token else None
